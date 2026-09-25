from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import import_demo2_validated_release as importer  # noqa: E402
import promote_demo2_validated_release as promoter  # noqa: E402
from tests.test_import_demo2_validated_release import build_source_bundle  # noqa: E402
from tests.test_validate_demo2_active_figures import build_active_site  # noqa: E402
from tests.test_refresh_demo2_processed_signal import (  # noqa: E402
    patch_bytes,
    successor_candidate,
)
import refresh_demo2_live_data as live_refresh  # noqa: E402


TARGET = "weather/legacy/meteo_precipitation.html"
RELEASE_PATH = "weather/legacy/meteo_precipitation.html"


def figure(data: str) -> bytes:
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Précipitations</title></head><body><div id="plot"></div>'
        f'<script>Plotly.newPlot("plot",{data},{{"title":"présentation validée"}},'
        '{"responsive":true});</script></body></html>'
    ).encode()


def manual_figure(dates: list[str], values: list[float], count: int) -> bytes:
    data = json.dumps(
        [{"name": "Mesures récentes", "mode": "markers", "x": dates, "y": values}],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    layouts = {
        mode: json.dumps(
            {"xaxis": {"range": [dates[0], dates[-1]]}, "title": "Présentation validée"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for mode in ("desktop", "tablet", "mobile")
    }
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8"></head><body>'
        f'<p>{count} mesures manuelles</p><script>const data = {data};'
        f'const layouts = {{desktop:{layouts["desktop"]},tablet:{layouts["tablet"]},'
        f'mobile:{layouts["mobile"]}}};</script></body></html>'
    ).encode()


def sensor_figure(payload: str, count: int, *, candidate: bool = False) -> bytes:
    metadata = json.dumps(
        {
            "rendering": {
                "coordinate_count": count,
                "transformations": {"downsampling_applied": True},
            }
        },
        separators=(",", ":"),
    )
    marker = "<p>Candidat automatisé de mise à jour.</p>" if candidate else ""
    return (
        '<!doctype html><html lang="fr"><body><p>Présentation validée.</p>'
        f'{marker}<script id="d2-cap-payload">{payload}</script>'
        f'<script>const FIGURE_METADATA = {metadata};</script></body></html>'
    ).encode()


def hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def set_active_payload(site: Path, target: str, payload: bytes) -> None:
    figure_root = site / "assets/figures/demo-2"
    destination = figure_root / target
    destination.write_bytes(payload)
    if target.startswith("weather/"):
        manifest_path = figure_root / "weather/content-manifest.json"
        entry_path = target.removeprefix("weather/")
    else:
        manifest_path = figure_root / "content-manifest.json"
        entry_path = target
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(item for item in manifest["files"] if item["path"] == entry_path)
    record["sha256"] = hashlib.sha256(payload).hexdigest()
    record["size_bytes"] = len(payload)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class Demo2PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.site = self.root / "site"
        self.site.mkdir()
        build_active_site(self.site)
        set_active_payload(self.site, TARGET, figure('[{"x":[1]}]'))
        self.sources = self.root / "sources"
        self.sources.mkdir(mode=0o700)
        self.figure_root = self.site / "assets/figures/demo-2"
        self.before = hashes(self.figure_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_weather(self, payload: bytes) -> str:
        source = build_source_bundle(
            self.sources,
            release_kind="weather_legacy_precipitation_review",
            logical_id="weather-rainfall",
            release_path=RELEASE_PATH,
            figure_payload=payload,
        )
        return str(importer.import_validated_release(source, site_root=self.site)["promotion_id"])

    def test_promotes_only_data_and_manifest_then_retains_exact_previous_tree(self) -> None:
        release_id = self.import_weather(figure('[{"x":[2]}]'))
        maintenance_before = (self.site / "demonstrations/fissures.html").read_bytes()

        result = promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(result["updated_master_count"], 1)
        self.assertIn(b'[{"x":[2]}]', (self.figure_root / TARGET).read_bytes())
        self.assertIn(b'"title":"pr\xc3\xa9sentation valid\xc3\xa9e"', (self.figure_root / TARGET).read_bytes())
        after = hashes(self.figure_root)
        changed = {path for path in after if after[path] != self.before[path]}
        self.assertEqual(changed, {TARGET, "weather/content-manifest.json"})
        self.assertEqual((self.site / "demonstrations/fissures.html").read_bytes(), maintenance_before)

        transaction = (
            self.site
            / "assets/validated-releases/.demo2-promotions"
            / str(result["transaction_id"])
        )
        journal = json.loads((transaction / promoter.JOURNAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], promoter.PHASE_COMMITTED)
        self.assertEqual(hashes(transaction / promoter.COUNTERPART_NAME), self.before)
        self.assertEqual(promoter.recover_transaction(str(result["transaction_id"]), site_root=self.site)["status"], "COMMITTED")

    def test_failure_after_visibility_rolls_back_the_exact_previous_tree(self) -> None:
        release_id = self.import_weather(figure('[{"x":[3]}]'))

        with patch.object(promoter, "_after_exchange", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(
                promoter.Demo2PromotionError,
                "DEMO2_PROMOTION_FAILED_ROLLED_BACK",
            ):
                promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(hashes(self.figure_root), self.before)
        transactions = [
            path
            for path in (self.site / "assets/validated-releases/.demo2-promotions").iterdir()
            if path.is_dir()
        ]
        self.assertEqual(len(transactions), 1)
        journal = json.loads((transactions[0] / promoter.JOURNAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], promoter.PHASE_ROLLED_BACK)

    def test_recovery_rolls_back_a_crash_left_in_committing_state(self) -> None:
        release_id = self.import_weather(figure('[{"x":[4]}]'))

        with patch.object(promoter, "_after_exchange", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertNotEqual(hashes(self.figure_root), self.before)
        transactions = [
            path
            for path in (self.site / "assets/validated-releases/.demo2-promotions").iterdir()
            if path.is_dir()
        ]
        self.assertEqual(len(transactions), 1)
        journal = json.loads((transactions[0] / promoter.JOURNAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], promoter.PHASE_COMMITTING)

        result = promoter.recover_transaction(transactions[0].name, site_root=self.site)

        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assertEqual(hashes(self.figure_root), self.before)

    def test_identical_data_is_idempotent_and_creates_no_transaction(self) -> None:
        release_id = self.import_weather(figure('[{"x":[1]}]'))

        result = promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(result["status"], "ALREADY_ACTIVE")
        self.assertEqual(result["updated_master_count"], 0)
        transaction_root = self.site / "assets/validated-releases/.demo2-promotions"
        self.assertFalse(any(path.is_dir() for path in transaction_root.iterdir()))

    def test_rejects_manual_raw_release_without_touching_active_tree(self) -> None:
        source = build_source_bundle(self.sources)
        release_id = str(importer.import_validated_release(source, site_root=self.site)["promotion_id"])

        with self.assertRaisesRegex(
            promoter.Demo2PromotionError,
            "DEMO2_PROMOTION_RELEASE_KIND_FORBIDDEN",
        ):
            promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(hashes(self.figure_root), self.before)

    def test_rejects_internal_chart_wording_without_touching_active_tree(self) -> None:
        release_id = self.import_weather(
            figure('[{"x":[2],"name":"Candidat de revue"}]')
        )

        with self.assertRaisesRegex(
            promoter.Demo2PromotionError,
            "DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN",
        ):
            promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(hashes(self.figure_root), self.before)

    def test_rejects_missing_maintenance_before_preparing_any_replacement(self) -> None:
        release_id = self.import_weather(figure('[{"x":[2]}]'))
        (self.site / "demonstrations/fissures.html").write_text("Disponible", encoding="utf-8")

        with self.assertRaisesRegex(
            promoter.Demo2PromotionError,
            "DEMO2_PROMOTION_ACTIVE_TREE_INVALID",
        ):
            promoter.promote_validated_releases([release_id], site_root=self.site)

        self.assertEqual(hashes(self.figure_root), self.before)

    def test_promotes_prepared_output_from_build_staging_path(self) -> None:
        prepared = figure('[{"x":[7,8]}]')

        result = promoter.promote_prepared_outputs(
            {PurePosixPath("assets/figures/demo-2") / TARGET: prepared},
            ["weather-ready:20260915T120000Z"],
            site_root=self.site,
        )

        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(result["source_ids"], ["weather-ready:20260915T120000Z"])
        self.assertEqual((self.figure_root / TARGET).read_bytes(), prepared)
        transaction = (
            self.site
            / "assets/validated-releases/.demo2-promotions"
            / str(result["transaction_id"])
        )
        journal = json.loads((transaction / promoter.JOURNAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], promoter.PHASE_COMMITTED)
        self.assertEqual(journal["source_ids"], ["weather-ready:20260915T120000Z"])

    def test_prepared_output_rejects_wind_direction_and_pattern_masters(self) -> None:
        for target in (
            "weather/legacy/meteo_wind_dir.html",
            "retaining-wall-extrema-hours.html",
            "retaining-wall-median-day.html",
        ):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    promoter.Demo2PromotionError,
                    "DEMO2_PROMOTION_TARGET_FROZEN",
                ):
                    promoter.promote_prepared_outputs(
                        {target: b"<!doctype html><html></html>"},
                        ["source:1"],
                        site_root=self.site,
                    )
        self.assertEqual(hashes(self.figure_root), self.before)

    def test_prepared_output_rejects_internal_data_wording(self) -> None:
        with self.assertRaisesRegex(
            promoter.Demo2PromotionError,
            "DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN",
        ):
            promoter.promote_prepared_outputs(
                {TARGET: figure('[{"name":"Candidat de revue","x":[2]}]')},
                ["source:2"],
                site_root=self.site,
            )
        self.assertEqual(hashes(self.figure_root), self.before)

    def test_promotes_prepared_manual_data_without_changing_its_template(self) -> None:
        target = "fissure-recente-meme-format.html"
        active = manual_figure(["2026-01-01", "2026-01-02"], [30.0, 30.1], 2)
        prepared = manual_figure(
            ["2026-01-01", "2026-01-02", "2026-01-03"],
            [30.0, 30.1, 30.2],
            3,
        )
        set_active_payload(self.site, target, active)

        result = promoter.promote_prepared_outputs(
            {target: prepared},
            ["manual-fissure2:sha256"],
            site_root=self.site,
        )

        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual((self.figure_root / target).read_bytes(), prepared)

    def test_sensor_release_removes_only_candidate_paragraph(self) -> None:
        active = sensor_figure("OLD", 1)
        candidate = sensor_figure("NEW", 2, candidate=True)

        merged = promoter.merge_data_only(active, candidate, "sensor")

        self.assertIn(b"NEW", merged)
        self.assertNotIn("Candidat automatisé".encode(), merged)
        self.assertIn("Présentation validée".encode(), merged)

    def test_promotes_prepared_processed_payload_without_template_change(self) -> None:
        target = "retaining-wall-sensor-processed-v2.html"
        active = (self.figure_root / target).read_bytes()
        payload, review = successor_candidate()
        prepared = live_refresh.refresh_processed(
            active,
            patch_bytes(payload, review, snapshot="a" * 64, generation="b" * 64),
        )

        result = promoter.promote_prepared_outputs(
            {PurePosixPath("assets/figures/demo-2") / target: prepared},
            ["processed-signal:sha256"],
            site_root=self.site,
        )

        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual((self.figure_root / target).read_bytes(), prepared)
        self.assertEqual(
            live_refresh.processed_data_only_skeleton(prepared),
            live_refresh.processed_data_only_skeleton(active),
        )


if __name__ == "__main__":
    unittest.main()
