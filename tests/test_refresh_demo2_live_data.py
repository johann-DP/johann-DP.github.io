from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refresh_demo2_live_data as refresh  # noqa: E402


def legacy(data: bytes = b'[1]') -> bytes:
    return b'<html><body><h1>validated</h1><script>Plotly.newPlot("p", ' + data + b', {"title":"fixed"});</script></body></html>'


def complement(
    payload: bytes,
    banner: bytes = b"validated prose",
    facts: tuple[bytes, bytes, bytes, bytes] = (b"0", b"0", b"0", b"+0800"),
) -> bytes:
    return (b'<html><body><p>' + banner + b'</p><div class="facts">'
            b'<div class="fact"><strong>' + facts[0] + b'</strong>a</div>'
            b'<div class="fact"><strong>' + facts[1] + b'</strong>b</div>'
            b'<div class="fact"><strong>' + facts[2] + b'</strong>c</div>'
            b'<div class="fact"><strong>' + facts[3] + b'</strong>d</div></div><p>end</p>'
            b'<script id="payload" type="application/json">' + payload + b'</script></body></html>')


def ready_candidate(parent: Path, relative: str, payload: bytes) -> Path:
    root = parent / ("a" * 64)
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    manifest = {
        "files": [
            {
                "path": relative,
                "role": "review_html_candidate",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        ],
        "release_id": root.name,
    }
    (root / "content-manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )
    (root / ".READY").write_bytes(refresh.READY_CONTENT)
    return root


class RefreshTests(unittest.TestCase):
    def test_current_ready_temperature_candidate_is_data_only_compatible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = refresh.ready_payloads(
            path.parent for path in (root / "assets/validated-releases/demo-2").glob("*/.READY")
        )
        relative = "weather/legacy/meteo_temperature.html"
        active = (root / "assets/figures/demo-2" / relative).read_bytes()
        updated = refresh.refresh_legacy(active, candidates[relative])
        self.assertEqual(refresh.legacy_data_only_skeleton(updated), refresh.legacy_data_only_skeleton(active))

    def test_legacy_current_and_append_replace_data_only(self) -> None:
        updated = refresh.refresh_legacy(legacy(b'[{"x":[1]}]'), legacy(b'[{"x":[1,2]}]'))
        self.assertIn(b'[1,2]', updated)
        self.assertIn(b'validated', updated)

    def test_divergent_skeleton_is_rejected(self) -> None:
        with self.assertRaisesRegex(refresh.RefreshError, "SKELETON_DIVERGED"):
            refresh.refresh_legacy(legacy(), legacy().replace(b"validated", b"candidate banner"))

    def test_wind_direction_is_never_staged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / "active"
            weather = active / "assets/figures/demo-2/weather/legacy"
            weather.mkdir(parents=True)
            (weather / "meteo_wind_dir.html").write_bytes(legacy(b"[old]"))
            candidate = ready_candidate(
                root,
                "weather/legacy/meteo_wind_dir.html",
                legacy(b"[new]"),
            )
            self.assertEqual(refresh.build_staging(active, [candidate]), {})
            self.assertEqual((weather / "meteo_wind_dir.html").read_bytes(), legacy(b"[old]"))

    def test_complement_keeps_master_banner_and_prose(self) -> None:
        active = complement(
            b'{"offset":"+0800","times":[1],"series":[{"values":[2],"applicable":[true]}]}'
        )
        candidate = complement(
            b'{"offset":"+0800","times":[1,2],"series":[{"values":[2,3],"applicable":[true,true]}]}',
            b"candidate banner",
            (b"1", b"2", b"19", b"+0800"),
        )
        updated = refresh.refresh_complement(active, candidate, "explorer")
        self.assertIn(b"validated prose", updated)
        self.assertNotIn(b"candidate banner", updated)
        self.assertIn("2".encode(), updated)

    def test_raw_candidate_paragraph_removed_before_proof(self) -> None:
        active = (
            b'<p class="scope">validated</p>\n  '
            b'<script id="d2-cap-payload">AAA</script>'
            b'<script>const FIGURE_METADATA = {"n":1};</script>'
        )
        candidate = (
            b'<p class="scope">validated</p>\n  '
            b'<p><strong>Candidat automatis\xc3\xa9</strong></p>\n  '
            b'<script id="d2-cap-payload">BBB</script>'
            b'<script>const FIGURE_METADATA = {"n":2};</script>'
        )
        updated = refresh.refresh_raw(active, candidate)
        self.assertIn(b"BBB", updated)
        self.assertNotIn(b"candidat automatis", updated)
        self.assertEqual(updated.count(b"validated"), 1)

    def test_raw_review_state_is_removed_from_public_metadata(self) -> None:
        active = (
            b'<p class="scope">validated</p>\n'
            b'<script id="d2-cap-payload">AAA</script>'
            b'<script>const FIGURE_METADATA = {"validation":{"classification_status":"VALID\xc3\x89"}};</script>'
        )
        candidate = (
            b'<p class="scope">validated</p>\n'
            b'<p><strong>Candidat automatis\xc3\xa9</strong></p>\n'
            b'<script id="d2-cap-payload">BBB</script>'
            b'<script>const FIGURE_METADATA = {"validation":{"automatic_master_substitution_permitted":false,'
            b'"candidate_status":"EX\xc3\x89CUT\xc3\x89_NON_VALID\xc3\x89","classification_status":"VALID\xc3\x89",'
            b'"review_required":true}};</script>'
        )
        updated = refresh.refresh_raw(active, candidate)
        self.assertNotIn(b"candidate_status", updated)
        self.assertNotIn(b"review_required", updated)
        self.assertNotIn(b"automatic_master_substitution_permitted", updated)
        self.assertIn(b'"classification_status":"VALID\xc3\x89"', updated)

    def test_manual_refresh_allows_only_source_count_and_primary_range(self) -> None:
        active = (
            b'<script>const data = [{"mode":"markers","name":"Mesures r\xc3\xa9centes",'
            b'"x":["2026-01-01"],"y":[1]},{"name":"Mod\xc3\xa8le","x":[1],"y":[2]}];'
            b'const layouts = {desktop:{"xaxis":{"range":["2026-01-01","2026-02-01"]}},'
            b'tablet:{"xaxis":{"range":["2026-01-01","2026-02-01"]}},'
            b'mobile:{"xaxis":{"range":["2026-01-01","2026-02-01"]}}};</script>'
            b'<p>1 mesures</p>'
        )
        updated = active.replace(
            b'"x":["2026-01-01"],"y":[1]',
            b'"x":["2026-01-01","2026-03-01"],"y":[1,2]',
        ).replace(b'"2026-02-01"', b'"2026-03-08"').replace(
            b"1 mesures", b"2 mesures"
        )
        self.assertEqual(refresh.refresh_manual(active, updated), updated)
        with self.assertRaisesRegex(refresh.RefreshError, "SKELETON_DIVERGED"):
            refresh.refresh_manual(active, updated.replace(b'Mod\xc3\xa8le', b'Autre mod\xc3\xa8le'))

    def test_ready_manifest_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = ready_candidate(root, "weather/legacy/meteo_wind_dir.html", b"one")
            (candidate / "weather/legacy/meteo_wind_dir.html").write_bytes(b"two")
            with self.assertRaisesRegex(refresh.RefreshError, "MANIFEST_DIVERGED"):
                refresh.ready_payloads([candidate])

    def test_ready_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = ready_candidate(root, "weather/legacy/meteo_wind_dir.html", b"one")
            alias = root / "candidate-link"
            alias.symlink_to(candidate, target_is_directory=True)
            with self.assertRaisesRegex(refresh.RefreshError, "ROOT_INVALID"):
                refresh.ready_payloads([alias])


if __name__ == "__main__":
    unittest.main()
