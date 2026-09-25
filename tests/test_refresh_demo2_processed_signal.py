from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from statistics import median
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_demo2_live_data as refresh  # noqa: E402


MASTER = ROOT / "assets/figures/demo-2/retaining-wall-sensor-processed-v2.html"


def document() -> tuple[bytes, dict[str, object], dict[str, object]]:
    master = MASTER.read_bytes()
    _, payload, _, review = refresh._processed_document(master)
    return master, deepcopy(payload), deepcopy(review)


def recompute_global_sg5(payload: dict[str, object], indexes: set[int]) -> None:
    rows = payload["global_hourly"]
    for index in indexes:
        window = rows[index - 2 : index + 3]
        available = (
            len(window) == 5
            and len({row[2] for row in window}) == 1
            and all(
                right[0] - left[0] == refresh._HOUR_MILLISECONDS
                for left, right in zip(window, window[1:])
            )
        )
        if available:
            rows[index][6] = sum(
                weight * row[5]
                for weight, row in zip(refresh._SG5_WEIGHTS, window, strict=True)
            )
            rows[index][7] = "AVAILABLE"
        else:
            rows[index][6] = None
            rows[index][7] = "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"


def recompute_thermal_sg5(payload: dict[str, object], indexes: set[int]) -> None:
    rows = payload["thermal_extended"]
    for index in indexes:
        if not 2 <= index < len(rows) - 2:
            continue
        window = rows[index - 2 : index + 3]
        available = (
            all(row[12] is True for row in window)
            and len({row[4] for row in window}) == 1
            and all(
                right[0] - left[0] == refresh._HOUR_MILLISECONDS
                for left, right in zip(window, window[1:])
            )
        )
        if available:
            for target, source in zip((22, 23, 24), (7, 9, 10), strict=True):
                rows[index][target] = sum(
                    weight * row[source]
                    for weight, row in zip(refresh._SG5_WEIGHTS, window, strict=True)
                )
            rows[index][25] = "AVAILABLE"
        else:
            rows[index][22:25] = [None, None, None]
            rows[index][25] = "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"


def recompute_daily(payload: dict[str, object]) -> None:
    hourly = payload["hourly"]
    global_hourly = payload["global_hourly"]
    old_daily = {(row[2], row[1]): row for row in payload["daily"]}
    old_global_daily = {(row[2], row[1]): row for row in payload["global_daily"]}
    groups: dict[tuple[int, str], list[int]] = {}
    for index, row in enumerate(hourly):
        groups.setdefault((row[2], row[1][:10]), []).append(index)
    daily: list[list[object]] = []
    global_daily: list[list[object]] = []
    for (origin, date), indexes in groups.items():
        rows = [hourly[index] for index in indexes]
        global_rows = [global_hourly[index] for index in indexes]
        values = [row[6] for row in rows]
        coordinate = round(median([row[0] for row in rows]))
        count = len(rows)
        med = median(values)
        q1 = refresh._quantile(values, 0.25)
        q3 = refresh._quantile(values, 0.75)
        reference = rows[0][3]
        offset = global_rows[0][4]
        daily_row = [coordinate, date, origin, count, med, q1, q3, count < 20, reference]
        global_row = [
                coordinate,
                date,
                origin,
                count,
                med + reference,
                q1 + reference,
                q3 + reference,
                med + reference + offset,
                q1 + reference + offset,
                q3 + reference + offset,
                count < 20,
            ]
        previous = old_daily.get((origin, date))
        if (
            previous is not None
            and previous[:4] == daily_row[:4]
            and previous[7:] == daily_row[7:]
            and all(
                refresh._same_number(previous[position], daily_row[position], tolerance=1e-12)
                for position in (4, 5, 6)
            )
        ):
            daily_row = previous
        previous_global = old_global_daily.get((origin, date))
        if (
            previous_global is not None
            and previous_global[:4] == global_row[:4]
            and previous_global[10] == global_row[10]
            and all(
                refresh._same_number(previous_global[position], global_row[position], tolerance=1e-12)
                for position in range(4, 10)
            )
        ):
            global_row = previous_global
        daily.append(daily_row)
        global_daily.append(global_row)
    payload["daily"] = daily
    payload["global_daily"] = global_daily


def recompute_review(payload: dict[str, object], review: dict[str, object]) -> None:
    rows = payload["thermal_extended"]
    paired = [index for index, row in enumerate(rows) if row[13] != "NOT_APPLIED"]
    if paired:
        last = paired[-1]
        review["lastPairedTemperatureSourceHour"] = rows[last][1]
        review["lastPairedTemperatureC"] = rows[last][8]
        trailing = rows[last + 1 :]
    else:
        review["lastPairedTemperatureSourceHour"] = None
        review["lastPairedTemperatureC"] = None
        trailing = rows
    reasons: dict[str, int] = {}
    for row in trailing:
        if row[14]:
            reasons[row[14]] = reasons.get(row[14], 0) + 1
    review["trailingUnpairedHourCount"] = len(trailing)
    review["trailingReasons"] = reasons
    months: dict[str, list[list[object]]] = {}
    for row in rows:
        if row[12] is True:
            months.setdefault(row[1][:7], []).append(row)
    review["monthlyThermalAdjustments"] = [
        {
            "month": month,
            "n": len(month_rows),
            "medianTemperature": median([row[8] for row in month_rows]),
            "medianAdjustment": median([-row[9] for row in month_rows]),
        }
        for month, month_rows in months.items()
    ]


def recompute_dynamic(payload: dict[str, object], review: dict[str, object]) -> None:
    recompute_daily(payload)
    coverage = refresh._derived_thermal_coverage(payload)
    payload["thermal_coverage"] = coverage
    hourly_by_origin: list[list[list[object]]] = [[] for _ in range(37)]
    for row in payload["hourly"]:
        hourly_by_origin[row[2]].append(row)
    for origin, rows, item in zip(
        payload["origins"], hourly_by_origin, coverage, strict=True
    ):
        origin["n"] = len(rows)
        origin["start"] = rows[0][1]
        origin["end"] = rows[-1][1]
        origin["thermal"] = {
            key: value
            for key, value in item.items()
            if key != "analysis_origin_regime_id"
        }
        origin["thermal_available"] = item["normalized_hour_count"] > 0
    metadata = payload["metadata"]
    counts = metadata["counts"]
    counts.update(
        {
            "daily": len(payload["daily"]),
            "events": len(payload["events"]),
            "hourly": len(payload["hourly"]),
            "low_cycle_hours": sum(row[7] < 20 for row in payload["hourly"]),
            "origin_starts": len(payload["origin_starts"]),
            "origins": len(payload["origins"]),
            "partial_days": sum(row[7] is True for row in payload["daily"]),
            "resumptions": len(payload["resumptions"]),
            "thermal": len(payload["thermal"]),
            "thermal_in_domain": sum(row[17] is True for row in payload["thermal"]),
            "thermal_origins": len({row[4] for row in payload["thermal"]}),
            "thermal_out_of_domain": sum(
                row[17] is False for row in payload["thermal"]
            ),
        }
    )
    metadata["coverage_end"] = payload["hourly"][-1][1]
    metadata["delivery_revision"] = refresh._PROCESSED_DELIVERY_REVISION
    centered = [row[6] for row in payload["hourly"]]
    metadata["full_y_range_mm"] = [min(centered), max(centered)]
    low = refresh._quantile(centered, 0.005)
    high = refresh._quantile(centered, 0.995)
    metadata["robust_y_range_mm"] = [low, high]
    metadata["robust_outside_hourly_point_count"] = sum(
        value < low or value > high for value in centered
    )
    totals = {
        name: sum(item[name] for item in coverage)
        for name in (
            "clock_ambiguous_hour_count",
            "exploitable_hour_count",
            "extended_hour_count",
            "historical_hour_count",
            "low_cycle_hour_count",
            "measured_hour_count",
            "no_temperature_hour_count",
            "normalized_hour_count",
            "out_of_domain_hour_count",
        )
    }
    extension = metadata["thermal_extension"]
    extension["coverage_totals"] = totals
    extension["row_count"] = len(payload["thermal_extended"])
    identities = [
        abs(row[24] - (row[22] - row[23]))
        for row in payload["thermal_extended"]
        if row[25] == "AVAILABLE"
    ]
    extension["sg5_identity_max_abs_error_mm"] = max(identities, default=0.0)
    recompute_review(payload, review)


def metadata_update(payload: dict[str, object]) -> dict[str, object]:
    metadata = payload["metadata"]
    update = {
        name: deepcopy(metadata[name])
        for name in refresh._PROCESSED_DYNAMIC_METADATA_KEYS
    }
    update["thermal_extension"] = {
        name: deepcopy(metadata["thermal_extension"][name])
        for name in refresh._PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS
    }
    return update


def patch_bytes(
    payload: dict[str, object],
    review: dict[str, object],
    *,
    snapshot: str,
    generation: str,
) -> bytes:
    review["sensor_snapshot_sha256"] = snapshot
    closed = datetime.strptime(payload["metadata"]["coverage_end"], "%Y-%m-%d %H:%M:%S")

    def hour(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    value = {
        "protocol_version": refresh.PROCESSED_PROTOCOL_VERSION,
        "logical_asset_id": refresh.PROCESSED_LOGICAL_ASSET_ID,
        "base_payload_sha256": refresh.PROCESSED_BASE_PAYLOAD_SHA256,
        "base_template_sha256": refresh.PROCESSED_BASE_TEMPLATE_SHA256,
        "baseline_proof": deepcopy(refresh._PROCESSED_BASELINE_PROOF),
        "sensor_source": {
            "generation_sha256": generation,
            "parent_generation_sha256": "f" * 64,
            "classification": "APPEND_ACCEPTED",
            "snapshot_sha256": snapshot,
            "accepted_size_bytes": 1,
            "snapshot_line_count": 1,
            "closed_source_hour": hour(closed),
            "first_excluded_source_hour": hour(closed + timedelta(hours=1)),
            "observed_open_source_hour": hour(closed + timedelta(hours=3)),
        },
        "weather_source": {
            "current_manifest_sha256": "e" * 64,
            "generation_names": ["2" * 64, "1" * 64],
            "cumulative_analytical_groups": 1,
            "latest_literal_hour": None,
        },
        "replacements": {
            **{
                name: deepcopy(payload[name])
                for name in refresh._PROCESSED_REPLACEMENT_KEYS
                if name != "metadata"
            },
            "metadata": metadata_update(payload),
        },
        "review_diagnostics_update": {
            name: deepcopy(review[name])
            for name in refresh._PROCESSED_REVIEW_UPDATE_KEYS
        },
    }
    return refresh._canonical_json(value) + b"\n"


def append_hour(
    payload: dict[str, object],
    review: dict[str, object],
    *,
    inch: float | None = None,
) -> None:
    old_hourly = payload["hourly"][-1]
    if inch is None:
        # The producer closes N only after observing N+2. Recover that one hidden
        # support value from the already-frozen centered SG5 instead of changing
        # any published row. This fixture intentionally models only N+1/N+2.
        global_rows = payload["global_hourly"]
        center = len(global_rows) - 2
        if center < 2 or global_rows[center][7] != "AVAILABLE":
            raise AssertionError("the active tail must carry stable centered SG5 support")
        known = sum(
            weight * row[5]
            for weight, row in zip(
                refresh._SG5_WEIGHTS[:4],
                global_rows[center - 2 : center + 2],
                strict=True,
            )
        )
        next_global_value = (
            global_rows[center][6] - known
        ) / refresh._SG5_WEIGHTS[4]
        inch = (next_global_value - global_rows[-1][4]) / 25.4
    time = old_hourly[0] + refresh._HOUR_MILLISECONDS
    source_hour = (
        datetime.strptime(old_hourly[1], "%Y-%m-%d %H:%M:%S") + timedelta(hours=1)
    ).strftime("%Y-%m-%d %H:%M:%S")
    measured = inch * 25.4
    line_min = old_hourly[10] + 1
    line_max = line_min + 235
    hourly = [
        time,
        source_hour,
        36,
        -0.4318,
        inch,
        measured,
        measured + 0.4318,
        118,
        236,
        line_min,
        line_max,
        "",
    ]
    global_row = [
        time,
        source_hour,
        36,
        measured,
        9.880599999999978,
        measured + 9.880599999999978,
        None,
        "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT",
        118,
        "",
        line_min,
        line_max,
    ]
    aligned = refresh._paris_aligned_hour(source_hour, "TEST")
    thermal = [
        time,
        source_hour,
        aligned[0],
        aligned[1],
        36,
        measured,
        global_row[4],
        global_row[5],
        None,
        None,
        None,
        False,
        False,
        "NOT_APPLIED",
        "NO_EXACT_OUTDOOR_TEMPERATURE",
        "GLOBAL_HISTORICAL_ENVELOPE_UNION",
        -4.5,
        40.1,
        False,
        None,
        None,
        None,
        None,
        None,
        None,
        "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT",
        118,
        line_min,
        line_max,
    ]
    payload["hourly"].append(hourly)
    payload["global_hourly"].append(global_row)
    payload["thermal_extended"].append(thermal)
    recompute_dynamic(payload, review)


def successor_candidate() -> tuple[dict[str, object], dict[str, object]]:
    _, payload, review = document()
    append_hour(payload, review)
    return payload, review


def fill_five_temperatures(
    payload: dict[str, object], review: dict[str, object], start: int
) -> None:
    rows = payload["thermal_extended"]
    for offset in range(5):
        row = rows[start + offset]
        temperature = 20.0 + offset / 10
        component = -0.09994542923746184 * (temperature - 15.1)
        row[8] = temperature
        row[9] = component
        row[10] = row[7] - component
        row[11] = True
        row[12] = True
        row[13] = "EXTENDED_FROZEN_MODEL_EXPLORATORY"
        row[14] = ""
    recompute_thermal_sg5(payload, set(range(start - 2, start + 7)))
    recompute_dynamic(payload, review)


class ProcessedSignalRefreshTests(unittest.TestCase):
    def test_processed_initial_anchor_only_allows_provisional_tail_completion(
        self,
    ) -> None:
        _, active, active_review = document()
        stable_count = refresh._PROCESSED_BASELINE_PROOF["hourly_prefix_count"]
        initial_count = stable_count + 1
        active["hourly"] = active["hourly"][:initial_count]
        active["global_hourly"] = active["global_hourly"][:initial_count]
        active["thermal_extended"] = active["thermal_extended"][:initial_count]
        recompute_dynamic(active, active_review)

        candidate = deepcopy(active)
        candidate_review = deepcopy(active_review)
        provisional = initial_count - 1
        candidate["hourly"][provisional][10] += 1
        candidate["global_hourly"][provisional][11] += 1
        candidate["thermal_extended"][provisional][28] += 1
        recompute_dynamic(candidate, candidate_review)

        refresh._validate_processed_transition_values(
            active,
            candidate,
            active_review,
            candidate_review,
            initial_anchor=True,
        )

        altered_identity = deepcopy(candidate)
        altered_identity["hourly"][provisional][0] += refresh._HOUR_MILLISECONDS
        with self.assertRaisesRegex(refresh.RefreshError, "HISTORY_DIVERGED"):
            refresh._validate_processed_transition_values(
                active,
                altered_identity,
                active_review,
                candidate_review,
                initial_anchor=True,
            )

        altered_prefix = deepcopy(candidate)
        altered_prefix["hourly"][stable_count - 1][10] += 1
        with self.assertRaisesRegex(refresh.RefreshError, "BASELINE_PROOF_DIVERGED"):
            refresh._validate_processed_transition_values(
                active,
                altered_prefix,
                active_review,
                candidate_review,
                initial_anchor=True,
            )

    def test_processed_patch_appends_one_hour_and_freezes_existing_history(self) -> None:
        master, active_payload, _ = document()
        payload, review = successor_candidate()
        patch = patch_bytes(payload, review, snapshot="a" * 64, generation="b" * 64)

        refreshed = refresh.refresh_processed(master, patch)
        _, updated, _, _ = refresh._processed_document(refreshed)

        self.assertEqual(len(updated["hourly"]), len(active_payload["hourly"]) + 1)
        self.assertEqual(
            updated["hourly"][: len(active_payload["hourly"])],
            active_payload["hourly"],
        )
        self.assertEqual(updated["hourly"], payload["hourly"])
        self.assertEqual(
            refresh.processed_data_only_skeleton(refreshed),
            refresh.processed_data_only_skeleton(master),
        )

    def test_processed_patch_n_plus_one_applies_to_already_refreshed_master(self) -> None:
        master, active_payload, _ = document()
        first_payload, first_review = successor_candidate()
        first = refresh.refresh_processed(
            master,
            patch_bytes(
                first_payload, first_review, snapshot="a" * 64, generation="b" * 64
            ),
        )
        second_payload = deepcopy(first_payload)
        second_review = deepcopy(first_review)
        append_hour(second_payload, second_review)

        second = refresh.refresh_processed(
            first,
            patch_bytes(
                second_payload,
                second_review,
                snapshot="c" * 64,
                generation="d" * 64,
            ),
        )
        _, updated, _, _ = refresh._processed_document(second)

        self.assertEqual(len(updated["hourly"]), len(active_payload["hourly"]) + 2)
        self.assertEqual(
            updated["metadata"]["coverage_end"],
            second_payload["metadata"]["coverage_end"],
        )
        self.assertEqual(
            updated["hourly"][: len(first_payload["hourly"])],
            first_payload["hourly"],
        )

    def test_processed_patch_rejects_old_measurement_mutation(self) -> None:
        master, _, _ = document()
        payload, review = successor_candidate()
        active = refresh.refresh_processed(
            master,
            patch_bytes(payload, review, snapshot="a" * 64, generation="b" * 64),
        )
        candidate = deepcopy(payload)
        candidate_review = deepcopy(review)
        index = len(candidate["hourly"]) - 1
        row = candidate["hourly"][index]
        row[4] += 0.001
        row[5] = row[4] * 25.4
        row[6] = row[5] - row[3]
        global_row = candidate["global_hourly"][index]
        global_row[3] = row[5]
        global_row[5] = global_row[3] + global_row[4]
        thermal = candidate["thermal_extended"][index]
        thermal[5] = row[5]
        thermal[7] = global_row[5]
        recompute_global_sg5(candidate, {index - 2})
        recompute_dynamic(candidate, candidate_review)

        with self.assertRaisesRegex(refresh.RefreshError, "HISTORY_DIVERGED"):
            refresh.refresh_processed(
                active,
                patch_bytes(
                    candidate,
                    candidate_review,
                    snapshot="c" * 64,
                    generation="d" * 64,
                ),
            )

    def test_processed_patch_allows_old_origin_late_weather_and_bounded_sg5(self) -> None:
        master, _, _ = document()
        first_payload, first_review = successor_candidate()
        active = refresh.refresh_processed(
            master,
            patch_bytes(
                first_payload, first_review, snapshot="a" * 64, generation="b" * 64
            ),
        )
        candidate = deepcopy(first_payload)
        candidate_review = deepcopy(first_review)
        start = next(
            index
            for index in range(len(candidate["thermal_extended"]) - 4)
            if candidate["thermal_extended"][index][4] == 7
            and all(
                candidate["thermal_extended"][index + offset][14]
                == "NO_EXACT_OUTDOOR_TEMPERATURE"
                for offset in range(5)
            )
        )
        month = candidate["thermal_extended"][start][1][:7]
        before_month = next(
            item
            for item in first_review["monthlyThermalAdjustments"]
            if item["month"] == month
        )
        fill_five_temperatures(candidate, candidate_review, start)

        updated = refresh.refresh_processed(
            active,
            patch_bytes(
                candidate,
                candidate_review,
                snapshot="a" * 64,
                generation="c" * 64,
            ),
        )
        _, payload, _, review = refresh._processed_document(updated)
        after_month = next(
            item for item in review["monthlyThermalAdjustments"] if item["month"] == month
        )

        self.assertEqual(payload["thermal_extended"][start + 2][25], "AVAILABLE")
        self.assertEqual(
            payload["origins"][7]["thermal"]["normalized_hour_count"],
            first_payload["origins"][7]["thermal"]["normalized_hour_count"] + 5,
        )
        self.assertNotEqual(before_month, after_month)

    def test_processed_patch_rejects_paired_temperature_and_static_drift(self) -> None:
        master, payload, review = document()
        paired = next(
            index for index, row in enumerate(payload["thermal_extended"]) if row[8] is not None
        )
        payload["thermal_extended"][paired][8] += 0.1
        recompute_dynamic(payload, review)
        with self.assertRaises(refresh.RefreshError):
            refresh._validate_processed_payload(payload)

        _, payload, _ = document()
        payload["offsets"][0][10] += 0.1
        with self.assertRaisesRegex(refresh.RefreshError, "STATIC_PAYLOAD_DIVERGED"):
            refresh._validate_processed_payload(payload)

        altered = bytearray(master)
        marker = b'"O_s=O_(s-1)+last_hourly_mm_(s-1)-first_hourly_mm_s"'
        position = altered.index(marker)
        altered[position] = ord("X")
        with self.assertRaisesRegex(
            refresh.RefreshError, "STATIC_PAYLOAD_DIVERGED|PAYLOAD_INVALID"
        ):
            refresh._processed_document(bytes(altered))

    def test_processed_patch_rejects_frozen_origin_identity_mutations(self) -> None:
        for origin, field, replacement in (
            (7, "id", 8),
            (7, "start", "2025-06-01 00:00:00"),
            (7, "center_mm", 123.0),
            (36, "center_mm", 123.0),
        ):
            with self.subTest(origin=origin, field=field):
                _, payload, _ = document()
                payload["origins"][origin][field] = replacement
                with self.assertRaisesRegex(
                    refresh.RefreshError, "ORIGIN_DIVERGED|SCHEMA_DIVERGED"
                ):
                    refresh._validate_processed_payload(payload)

    def test_processed_historical_membership_is_exact_and_non_contiguous(self) -> None:
        _, payload, _ = document()
        rows = [row for row in payload["thermal_extended"] if row[4] == 9]
        classes = {row[1]: row[13] for row in rows}

        self.assertEqual(
            classes["2025-09-15 11:00:00"], "EXTENDED_FROZEN_MODEL_EXPLORATORY"
        )
        self.assertEqual(
            classes["2025-09-24 11:00:00"], "HISTORICAL_REVISION_PRESERVED"
        )
        refresh._validate_processed_payload(payload)

    def test_processed_thermal_tail_support_is_bounded_on_append(self) -> None:
        def row(index: int, *, temperature: float | None = None) -> list[object]:
            value: list[object] = [None] * 29
            value[0] = index * refresh._HOUR_MILLISECONDS
            value[1] = f"2026-01-01 {index:02d}:00:00"
            value[4] = 36
            value[8] = temperature
            value[14] = "NO_EXACT_OUTDOOR_TEMPERATURE"
            value[22:26] = [None, None, None, "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"]
            return value

        active = [row(index) for index in range(6)]
        candidate = deepcopy(active) + [row(6, temperature=20.0), row(7, temperature=20.0)]
        for index in (4, 5):
            candidate[index][22:26] = [1.0, 0.5, 0.5, "AVAILABLE"]
        refresh._validate_thermal_transition(active, candidate, initial_anchor=False)

        candidate[3][22:26] = [1.0, 0.5, 0.5, "AVAILABLE"]
        with self.assertRaisesRegex(
            refresh.RefreshError, "THERMAL_TRANSITION_INVALID"
        ):
            refresh._validate_thermal_transition(active, candidate, initial_anchor=False)

    def test_processed_late_weather_on_low_cycle_row_changes_temperature_only(self) -> None:
        old: list[object] = [None] * 29
        old[8] = None
        old[9:15] = [None, None, False, False, "NOT_APPLIED", "LOW_CYCLE_SUPPORT"]
        old[19:22] = [None, None, None]
        old[22:26] = [None, None, None, "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"]
        old[26] = 10
        candidate = deepcopy(old)
        candidate[8] = 12.3

        refresh._validate_thermal_transition([old], [candidate], initial_anchor=False)

        candidate[9] = 1.0
        with self.assertRaisesRegex(
            refresh.RefreshError, "THERMAL_TRANSITION_INVALID"
        ):
            refresh._validate_thermal_transition([old], [candidate], initial_anchor=False)

    def test_ready_inventory_accepts_only_content_addressed_processed_patch(self) -> None:
        master, _, _ = document()
        payload, review = successor_candidate()
        candidate = patch_bytes(
            payload, review, snapshot="a" * 64, generation="b" * 64
        )
        release_id = hashlib.sha256(candidate).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active_root = root / "site"
            target = active_root / refresh.FIGURES / refresh.PROCESSED_TARGET
            target.parent.mkdir(parents=True)
            target.write_bytes(master)
            release = root / release_id
            release.mkdir()
            (release / refresh.PROCESSED_PATCH).write_bytes(candidate)
            manifest = {
                "files": [
                    {
                        "path": refresh.PROCESSED_PATCH,
                        "role": refresh.PROCESSED_PATCH_ROLE,
                        "sha256": release_id,
                        "size_bytes": len(candidate),
                    }
                ],
                "release_id": release_id,
            }
            (release / refresh.CONTENT_MANIFEST).write_bytes(
                refresh._canonical_json(manifest) + b"\n"
            )
            (release / refresh.READY).write_bytes(refresh.READY_CONTENT)

            staged = refresh.build_staging(active_root, [release])

            self.assertEqual(set(staged), {refresh.FIGURES / refresh.PROCESSED_TARGET})
            (release / "extra.json").write_bytes(b"{}")
            with self.assertRaisesRegex(refresh.RefreshError, "INVENTORY_DIVERGED"):
                refresh.build_staging(active_root, [release])


if __name__ == "__main__":
    unittest.main()
