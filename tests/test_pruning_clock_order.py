from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_demo2_stage3_data as stage3  # noqa: E402


def folded_pruning():
    value = json.loads((ROOT / stage3.ROOT / "pruning.json").read_bytes())
    rows = []
    for index, hour in enumerate((1, 2, 2, 3)):
        stamp = datetime(2026, 10, 25, hour, tzinfo=timezone.utc)
        rows.append({
            "date": stamp.strftime("%Y-%m-%dT%H:%M:%S"), "timestamp_ms": stamp.timestamp() * 1000,
            "raw_mm": .1 + index / 100, "corrected_mm": None, "temperature_c": None,
            "missing_reason": "CLOCK_AMBIGUOUS_OR_NONEXISTENT" if hour == 2 else "NO_EXACT_OUTDOOR_TEMPERATURE",
            "source_line_min": 100 + index * 236, "source_line_max": 335 + index * 236,
            "source_hour_occurrence": 2 if index == 2 else 1,
        })
    value["comparator_series"] = rows
    value["comparator"].update(counts={"raw": 4, "corrected": 0, "missing_temperature": 2,
                                      "out_of_domain": 0, "other_missing": 2},
                               period={"start": rows[0]["date"], "end": rows[-1]["date"]})
    return value


class PruningClockOrderTests(unittest.TestCase):
    def test_both_distinct_source_occurrences_are_retained_without_rewriting_dates(self):
        value = folded_pruning()
        original = deepcopy(value)
        stage3._validate_pruning(value)
        self.assertEqual(value, original)
        self.assertEqual(len(value["comparator_series"]), 4)
        self.assertEqual(value["comparator_series"][1]["timestamp_ms"], value["comparator_series"][2]["timestamp_ms"])

    def test_legacy_payload_remains_valid_but_cannot_hide_a_duplicate(self):
        value = json.loads((ROOT / stage3.ROOT / "pruning.json").read_bytes())
        stage3._validate_pruning(value)
        value = folded_pruning()
        for row in value["comparator_series"]:
            for key in ("source_line_min", "source_line_max", "source_hour_occurrence"):
                row.pop(key)
        with self.assertRaisesRegex(stage3.Stage3DataError, "ORDER_INVALID"):
            stage3._validate_pruning(value)

    def test_regular_duplicate_and_third_occurrence_are_rejected(self):
        value = folded_pruning()
        for row in value["comparator_series"]:
            row["date"] = row["date"].replace("2026-10-25", "2026-10-24")
            row["timestamp_ms"] -= 86400000
        with self.assertRaisesRegex(stage3.Stage3DataError, "FOLD_INVALID"):
            stage3._validate_pruning(value)
        value = folded_pruning()
        third = value["comparator_series"][3]
        third.update(date="2026-10-25T02:00:00", timestamp_ms=value["comparator_series"][2]["timestamp_ms"],
                     source_hour_occurrence=2, missing_reason="CLOCK_AMBIGUOUS_OR_NONEXISTENT")
        with self.assertRaisesRegex(stage3.Stage3DataError, "FOLD_INVALID"):
            stage3._validate_pruning(value)

    def test_fold_requires_disjoint_source_lines_and_no_thermal_attribution(self):
        for field, bad in (("source_line_min", 335), ("source_line_min", True),
                           ("source_hour_occurrence", 1), ("temperature_c", 12.5),
                           ("missing_reason", "NO_EXACT_OUTDOOR_TEMPERATURE")):
            value = folded_pruning()
            value["comparator_series"][2][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(stage3.Stage3DataError):
                stage3._validate_pruning(value)

    def test_mixed_identity_schemas_and_backwards_order_are_rejected(self):
        value = folded_pruning()
        value["comparator_series"][0].pop("source_hour_occurrence")
        with self.assertRaisesRegex(stage3.Stage3DataError, "SCHEMA_INVALID"):
            stage3._validate_pruning(value)
        value = folded_pruning()
        value["comparator_series"][-1].update(date="2026-10-25T00:00:00", timestamp_ms=1792886400000)
        with self.assertRaisesRegex(stage3.Stage3DataError, "ORDER_INVALID"):
            stage3._validate_pruning(value)
        value = folded_pruning()
        value["comparator_series"][2].update(timestamp_ms=value["comparator_series"][2]["timestamp_ms"] + 1,
                                             source_hour_occurrence=1)
        with self.assertRaisesRegex(stage3.Stage3DataError, "SOURCE_CLOCK_CHANGED"):
            stage3._validate_pruning(value)

    def test_ambiguous_singleton_is_retained_but_never_thermally_attributed(self):
        value = folded_pruning()
        value["comparator_series"].pop(2)
        value["comparator"]["counts"].update(raw=3, other_missing=1)
        stage3._validate_pruning(value)
        value["comparator_series"][1]["temperature_c"] = 12.5
        with self.assertRaisesRegex(stage3.Stage3DataError, "FOLD_INVALID"):
            stage3._validate_pruning(value)
