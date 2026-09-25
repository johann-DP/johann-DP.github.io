from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_demo2_active_figures as validator  # noqa: E402


def _entry(path: str, role: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "role": role,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _html(label: str) -> bytes:
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{label}</title></head><body>{label}</body></html>"
    ).encode()


def build_active_site(root: Path) -> None:
    figure_root = root / "assets/figures/demo-2"
    root_payloads = {path: _html(path) for path in validator.ROOT_ENTRIES}
    root_payloads["01-historical-crack-analysis-compacted-v2.png"] = b"png"
    root_payloads["diagrams/structural-monitoring-layout.svg"] = b"<svg/>"
    root_payloads["retaining-wall-sensor-source-values.html"] = _html(
        "temps source naïf — fuseau à confirmer ; valeur source — unité à confirmer ; "
        "Aucune correction, conversion, interpolation, jointure, causalité ni diagnostic ; "
        '<script src="weather/assets/plotly-2.35.2.min.js"></script>'
    )
    weather_payloads = {path: _html(path) for path in validator.WEATHER_ENTRIES}
    weather_payloads["assets/plotly-2.35.2.min.js"] = b"plotly-runtime"
    weather_payloads["assets/plotly-2.35.2.min.js.LICENSE.txt"] = b"plotly-license"

    for relative, payload in root_payloads.items():
        destination = figure_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    for relative, payload in weather_payloads.items():
        destination = figure_root / "weather" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    (figure_root / validator.ROOT_MANIFEST_RELATIVE).write_text(
        json.dumps(
            {
                "files": [
                    _entry(path, validator.ROOT_ENTRIES[path], root_payloads[path])
                    for path in validator.ROOT_ENTRIES
                ],
                "manifest_version": 2,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (figure_root / validator.WEATHER_MANIFEST_RELATIVE).write_text(
        json.dumps(
            {
                "files": [
                    _entry(path, validator.WEATHER_ENTRIES[path], weather_payloads[path])
                    for path in validator.WEATHER_ENTRIES
                ],
                "manifest_version": 1,
                "validation": dict(validator.WEATHER_VALIDATION),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "demonstrations").mkdir(parents=True)
    (root / "demonstrations/fissures.html").write_text(
        '<!doctype html><body data-maintenance="true">'
        "Démonstration 2 · En maintenance</body>",
        encoding="utf-8",
    )
    (root / "demonstrations.html").write_text(
        '<!doctype html><a class="demonstrations-page__card-link" '
        'href="demonstrations/fissures.html"><span>En maintenance</span>'
        "<span>Consulter la version en maintenance</span></a>",
        encoding="utf-8",
    )


class Demo2ActiveFigureValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        build_active_site(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_rotated_content_when_schema_inventory_and_hashes_converge(self) -> None:
        target = self.root / "assets/figures/demo-2/weather/legacy/meteo_temperature.html"
        payload = _html("rotated data")
        target.write_bytes(payload)
        manifest_path = self.root / "assets/figures/demo-2/weather/content-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = next(item for item in manifest["files"] if item["path"] == "legacy/meteo_temperature.html")
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        record["size_bytes"] = len(payload)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = validator.validate_active_figure_tree(site_root=self.root)

        self.assertEqual(result["html_master_count"], 18)
        self.assertEqual(result["status"], "VERIFIED")

    def test_rejects_extra_file_even_with_valid_manifests(self) -> None:
        (self.root / "assets/figures/demo-2/unapproved.html").write_bytes(_html("extra"))

        with self.assertRaises(validator.Demo2FigureValidationError):
            validator.validate_active_figure_tree(site_root=self.root)

    def test_rejects_candidate_wording_and_missing_maintenance(self) -> None:
        target = self.root / "assets/figures/demo-2/building-geometry.html"
        payload = _html("Candidat de revue")
        target.write_bytes(payload)
        manifest_path = self.root / "assets/figures/demo-2/content-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = next(item for item in manifest["files"] if item["path"] == "building-geometry.html")
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        record["size_bytes"] = len(payload)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.root / "demonstrations/fissures.html").write_text("Disponible", encoding="utf-8")

        with self.assertRaises(validator.Demo2FigureValidationError) as caught:
            validator.validate_active_figure_tree(site_root=self.root)

        self.assertIn("terme interne visible", str(caught.exception))
        self.assertIn("doit rester En maintenance", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
