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


def responsive_legacy(
    data: bytes,
    mobile_data: bytes,
    range_end: bytes,
    shapes: bytes,
    *,
    title: bytes = b"fixed",
) -> bytes:
    return (
        b'<html><body><h1>validated</h1><script>const desktopLayout = {"shapes":'
        + shapes
        + b',"title":"'
        + title
        + b'","xaxis":{"range":["2023-12-17",'
        + range_end
        + b']},"xaxis2":{"range":["2023-12-17",'
        + range_end
        + b']}};const mobileLayout = {"shapes":'
        + shapes
        + b',"title":"'
        + title
        + b'","xaxis":{"range":["2023-12-17",'
        + range_end
        + b']},"xaxis2":{"range":["2023-12-17",'
        + range_end
        + b']}};const mobileData = '
        + mobile_data
        + b';Plotly.newPlot("p", '
        + data
        + b', desktopLayout);</script></body></html>'
    )


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
                "role": refresh.PATTERN_ROLES.get(
                    relative, "review_html_candidate"
                ),
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


def ready_candidates(parent: Path, payloads: dict[str, bytes]) -> Path:
    root = parent / ("b" * 64)
    records = []
    for relative, payload in sorted(payloads.items()):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        records.append(
            {
                "path": relative,
                "role": refresh.PATTERN_ROLES.get(
                    relative, "review_html_candidate"
                ),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        )
    manifest = {"files": records, "release_id": root.name}
    (root / "content-manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )
    (root / ".READY").write_bytes(refresh.READY_CONTENT)
    return root


def active_patterns() -> dict[str, bytes]:
    root = Path(__file__).resolve().parents[1] / "assets/figures/demo-2"
    return {name: (root / name).read_bytes() for name in refresh.PATTERN_TARGETS}


def rewrite_pattern(
    document: bytes,
    *,
    payload_change=None,
    metadata_change=None,
    candidate_cards: bytes | None = None,
) -> bytes:
    match, payload, metadata_span, metadata, cards = refresh._pattern_document(document)
    payload = json.loads(json.dumps(payload))
    metadata = json.loads(json.dumps(metadata))
    if payload_change is not None:
        payload_change(payload)
    if metadata_change is not None:
        metadata_change(metadata)
    return refresh._replace_ranges(
        document,
        (
            (match.start(2), match.end(2), refresh._canonical_json(payload)),
            (*metadata_span, refresh._canonical_json(metadata)),
            (
                cards.start(),
                cards.end(),
                candidate_cards if candidate_cards is not None else cards.group(0),
            ),
        ),
    )


class RefreshTests(unittest.TestCase):
    def test_highest_interior_peak_ignores_boundaries_and_selects_densest(self) -> None:
        self.assertIsNone(refresh._highest_interior_peak([4.0, 3.0, 2.0, 1.0]))
        self.assertEqual(
            refresh._highest_interior_peak([0.0, 2.0, 0.0, 3.0, 0.0]),
            3,
        )

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

    def test_dynamic_time_layout_and_mobile_data_are_refreshed_atomically(self) -> None:
        active = responsive_legacy(
            b'[{"x":["old"]}]',
            b'[{"r":[1]}]',
            b'"2026-08-16"',
            b'[{"x0":"2026-07-01"}]',
        )
        candidate = responsive_legacy(
            b'[{"x":["new"]}]',
            b'[{"r":[1,2]}]',
            b'"2026-09-27"',
            b'[{"x0":"2026-07-01"},{"x0":"2026-09-01"}]',
        )
        updated = refresh.refresh_legacy(active, candidate)
        self.assertIn(b'[{"x":["new"]}]', updated)
        self.assertIn(b'[{"r":[1,2]}]', updated)
        self.assertIn(b'"2026-09-27"', updated)
        self.assertIn(b'"2026-09-01"', updated)
        self.assertEqual(
            refresh.legacy_data_only_skeleton(updated),
            refresh.legacy_data_only_skeleton(active),
        )

    def test_non_dynamic_legacy_layout_change_is_rejected(self) -> None:
        active = responsive_legacy(b"[1]", b"null", b'"2026-08-16"', b"[]")
        candidate = responsive_legacy(
            b"[2]", b"null", b'"2026-09-27"', b"[]", title=b"changed"
        )
        with self.assertRaisesRegex(refresh.RefreshError, "SKELETON_DIVERGED"):
            refresh.refresh_legacy(active, candidate)

        numeric_active = active.replace(
            b'["2023-12-17","2026-08-16"]', b"[0,10]"
        )
        numeric_candidate = candidate.replace(
            b'["2023-12-17","2026-09-27"]', b"[0,20]"
        ).replace(b'"changed"', b'"fixed"')
        with self.assertRaisesRegex(refresh.RefreshError, "SKELETON_DIVERGED"):
            refresh.refresh_legacy(numeric_active, numeric_candidate)

    def test_wind_direction_is_staged_with_desktop_and_mobile_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / "active"
            weather = active / "assets/figures/demo-2/weather/legacy"
            weather.mkdir(parents=True)
            current = responsive_legacy(
                b'[{"r":[1]}]', b'[{"r":[10]}]', b'"2026-08-16"', b"[]"
            )
            updated = responsive_legacy(
                b'[{"r":[1,2]}]',
                b'[{"r":[10,20]}]',
                b'"2026-09-27"',
                b"[]",
            )
            (weather / "meteo_wind_dir.html").write_bytes(current)
            candidate = ready_candidate(
                root,
                "weather/legacy/meteo_wind_dir.html",
                updated,
            )
            staged = refresh.build_staging(active, [candidate])
            target = refresh.FIGURES / "weather/legacy/meteo_wind_dir.html"
            self.assertEqual(staged[target], updated)
            self.assertEqual((weather / "meteo_wind_dir.html").read_bytes(), current)

    def test_pattern_refresh_requires_the_complete_pair(self) -> None:
        patterns = active_patterns()
        with tempfile.TemporaryDirectory() as temporary:
            candidate = ready_candidate(
                Path(temporary),
                refresh.PATTERN_MEDIAN,
                patterns[refresh.PATTERN_MEDIAN],
            )
            with self.assertRaisesRegex(
                refresh.RefreshError, "REFRESH_PATTERN_PAIR_INCOMPLETE"
            ):
                refresh.build_staging(
                    Path(__file__).resolve().parents[1], [candidate]
                )

    def test_pattern_ready_pair_requires_exact_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = ready_candidates(root, active_patterns())
            manifest_path = candidate / "content-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["role"] = "review_html_candidate"
            manifest_path.write_text(
                json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                refresh.RefreshError, "REFRESH_PATTERN_ROLE_INVALID"
            ):
                refresh.build_staging(
                    Path(__file__).resolve().parents[1], [candidate]
                )

    def test_pattern_refresh_preserves_static_metadata(self) -> None:
        patterns = active_patterns()

        def mutate_method(metadata: dict[str, object]) -> None:
            metadata["method"] = {"unexpected": "mutation"}

        patterns[refresh.PATTERN_MEDIAN] = rewrite_pattern(
            patterns[refresh.PATTERN_MEDIAN], metadata_change=mutate_method
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_STATIC_METADATA_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active_patterns(), patterns)

    def test_pattern_refresh_rejects_unknown_candidate_status(self) -> None:
        active = active_patterns()

        def mutate_status(metadata: dict[str, object]) -> None:
            metadata["review_status"] = "AUTOMATICALLY_ACCEPTED"

        candidate = {
            name: rewrite_pattern(payload, metadata_change=mutate_status)
            for name, payload in active.items()
        }
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_CANDIDATE_STATUS_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_script_injection_in_bootstrap(self) -> None:
        active = active_patterns()

        def inject_script(metadata: dict[str, object]) -> None:
            metadata["bootstrap"]["review_note"] = (
                "</script><script>alert(7)</script>"
            )

        candidate = {
            name: rewrite_pattern(payload, metadata_change=inject_script)
            for name, payload in active.items()
        }
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_JSON_TREE_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_mixed_case_script_close_in_payload(self) -> None:
        active = active_patterns()

        def inject_script(payload: dict[str, object]) -> None:
            payload["source_naive_time"][0] = (
                "</ScRiPt><script>alert(7)</ScRiPt>"
            )
            payload["step_source_naive_time"][0] = payload["source_naive_time"][0]

        candidate = dict(active)
        candidate[refresh.PATTERN_MEDIAN] = rewrite_pattern(
            active[refresh.PATTERN_MEDIAN], payload_change=inject_script
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_JSON_TREE_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_false_half_hour_labels(self) -> None:
        active = active_patterns()

        def alter_labels(payload: dict[str, object]) -> None:
            payload["source_naive_time"][0] = "00:15"
            payload["step_source_naive_time"][0] = "00:15"

        candidate = dict(active)
        candidate[refresh.PATTERN_MEDIAN] = rewrite_pattern(
            active[refresh.PATTERN_MEDIAN], payload_change=alter_labels
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_source_and_day_count_regressions(self) -> None:
        active = active_patterns()

        def regress_records(metadata: dict[str, object]) -> None:
            metadata["counts"]["source_record_count"] -= 1
            metadata["counts"]["excluded_both_timestamp_and_value_record_count"] -= 1

        record_regression = {
            name: rewrite_pattern(payload, metadata_change=regress_records)
            for name, payload in active.items()
        }
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_COUNT_REGRESSION"
        ):
            refresh.refresh_pattern_pair(active, record_regression)

        def regress_one_slot(payload: dict[str, object]) -> None:
            payload["day_count"][0] -= 1
            payload["day_count"][1] += 1

        day_regression = dict(active)
        day_regression[refresh.PATTERN_MEDIAN] = rewrite_pattern(
            active[refresh.PATTERN_MEDIAN], payload_change=regress_one_slot
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_DAY_COUNT_REGRESSION"
        ):
            refresh.refresh_pattern_pair(active, day_regression)

    def test_pattern_refresh_rejects_pair_and_payload_count_divergence(self) -> None:
        active = active_patterns()

        def diverge_pair(metadata: dict[str, object]) -> None:
            metadata["counts"]["source_record_count"] += 1

        pair_divergence = dict(active)
        pair_divergence[refresh.PATTERN_MEDIAN] = rewrite_pattern(
            active[refresh.PATTERN_MEDIAN], metadata_change=diverge_pair
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_PAIR_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active, pair_divergence)

        def diverge_payload_count(metadata: dict[str, object]) -> None:
            metadata["counts"]["profile_day_slot_cell_count"] += 1

        count_divergence = {
            name: rewrite_pattern(payload, metadata_change=diverge_payload_count)
            for name, payload in active.items()
        }
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_COUNTS_PAYLOAD_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active, count_divergence)

    def test_pattern_refresh_rejects_hour_outside_day_domain(self) -> None:
        active = active_patterns()

        def set_invalid_hour(payload: dict[str, object]) -> None:
            payload["minimum"]["hours"][0] = 99.0

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=set_invalid_hour
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_HOUR_DOMAIN_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_negative_kde_density(self) -> None:
        active = active_patterns()

        def set_negative_density(payload: dict[str, object]) -> None:
            payload["maximum"]["hour_kde"]["density"][0] = -0.01

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=set_negative_density
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_truncated_kde_grid(self) -> None:
        active = active_patterns()

        def truncate_grid(payload: dict[str, object]) -> None:
            kde = payload["maximum"]["hour_kde"]
            kde["grid_hours"] = kde["grid_hours"][:1]
            kde["density"] = kde["density"][:1]

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=truncate_grid
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_mode_diverging_from_primary_kde_peak(self) -> None:
        active = active_patterns()

        def move_mode(payload: dict[str, object]) -> None:
            payload["minimum"]["primary_hour_cluster"]["kde_mode_hours"] = 10.0
            payload["minimum"]["timing"]["central_time_hours"] = 10.0

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=move_mode
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_KDE_MODE_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_kde_grid_with_wrong_endpoint(self) -> None:
        active = active_patterns()

        def move_endpoint(payload: dict[str, object]) -> None:
            payload["maximum"]["hour_kde"]["grid_hours"][0] = 0.001

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=move_endpoint
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_KDE_MODE_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_rejects_incorrect_circular_cluster_partition(self) -> None:
        active = active_patterns()

        def swap_partition_members(payload: dict[str, object]) -> None:
            item = payload["maximum"]
            item["retained_hours"][0], item["outside_hours"][0] = (
                item["outside_hours"][0],
                item["retained_hours"][0],
            )

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=swap_partition_members
        )
        with self.assertRaisesRegex(
            refresh.RefreshError, "REFRESH_PATTERN_CLUSTER_PARTITION_DIVERGED"
        ):
            refresh.refresh_pattern_pair(active, candidate)

    def test_pattern_refresh_builds_public_cards_and_validated_metadata(self) -> None:
        active = active_patterns()

        def extend_counts(metadata: dict[str, object]) -> None:
            metadata["counts"]["source_record_count"] += 1
            metadata["counts"]["excluded_both_timestamp_and_value_record_count"] += 1
            metadata["counts"]["profile_day_slot_cell_count"] += 1

        def extend_median(payload: dict[str, object]) -> None:
            payload["day_count"][18] += 1

        candidate_cards = (
            b'<section class="cards" aria-label="Rep\xc3\xa8res statistiques">'
            b"<div class=\"card\">cluster bootstrap candidat</div></section>"
        )
        candidate = {
            name: rewrite_pattern(
                payload,
                payload_change=(extend_median if name == refresh.PATTERN_MEDIAN else None),
                metadata_change=extend_counts,
                candidate_cards=candidate_cards,
            )
            for name, payload in active.items()
        }

        refreshed = refresh.refresh_pattern_pair(active, candidate)

        median_document = refresh._pattern_document(
            refreshed[refresh.PATTERN_MEDIAN]
        )
        extrema_document = refresh._pattern_document(
            refreshed[refresh.PATTERN_EXTREMA]
        )
        self.assertEqual(median_document[3]["review_status"], "VALIDÉ")
        self.assertEqual(extrema_document[3]["review_status"], "VALIDÉ")
        candidate_median = refresh._pattern_document(
            candidate[refresh.PATTERN_MEDIAN]
        )[1]
        day_counts = candidate_median["day_count"]
        expected_range = f"{min(day_counts)} à {max(day_counts)} jours".encode()
        self.assertIn(expected_range, median_document[4].group(0))
        self.assertNotIn(b"cluster", median_document[4].group(0).lower())
        self.assertNotIn(b"bootstrap", extrema_document[4].group(0).lower())
        self.assertEqual(
            median_document[3]["method"],
            refresh._pattern_document(active[refresh.PATTERN_MEDIAN])[3]["method"],
        )

    def test_pattern_refresh_labels_an_interval_crossing_midnight(self) -> None:
        active = active_patterns()

        def wrap_interval(payload: dict[str, object]) -> None:
            interval = payload["minimum"]["timing"]["ci95"]
            interval["arc_start_hours"] = 23.8
            interval["arc_end_hours"] = 0.2
            interval["wraps_midnight"] = True

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=wrap_interval
        )

        refreshed = refresh.refresh_pattern_pair(active, candidate)

        cards = refresh._pattern_document(
            refreshed[refresh.PATTERN_EXTREMA]
        )[4].group(0)
        self.assertIn("(par minuit)".encode(), cards)

    def test_pattern_refresh_preserves_24h_as_non_wrapping_upper_bound(self) -> None:
        active = active_patterns()

        def end_at_24(payload: dict[str, object]) -> None:
            interval = payload["maximum"]["timing"]["ci95"]
            interval["arc_start_hours"] = 23.7
            interval["arc_end_hours"] = 24.0
            interval["wraps_midnight"] = False

        candidate = dict(active)
        candidate[refresh.PATTERN_EXTREMA] = rewrite_pattern(
            active[refresh.PATTERN_EXTREMA], payload_change=end_at_24
        )

        refreshed = refresh.refresh_pattern_pair(active, candidate)

        cards = refresh._pattern_document(
            refreshed[refresh.PATTERN_EXTREMA]
        )[4].group(0)
        self.assertIn("à 24 h 00".encode(), cards)
        self.assertNotIn("(par minuit)".encode(), cards)

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
