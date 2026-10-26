from __future__ import annotations

from copy import deepcopy
import json
import unittest

import test_refresh_demo2_processed_signal as processed
import test_refresh_demo2_live_data as patterns

from demo2_clock_revision import (
    DELIVERY_REVISION,
    SOURCE_CLOCK_REVISION,
    project_dynamic_replacements,
    project_full_payload,
    project_review_diagnostics,
)


refresh = processed.refresh


def patch_json(value):
    return refresh._canonical_json(value) + b"\n"


def clock_patch(payload, review):
    patch = json.loads(processed.patch_bytes(
        payload, review, snapshot="a" * 64, generation="b" * 64
    ))
    if patch["protocol_version"] == 1:
        patch["protocol_version"] = 2
        patch["delivery_revision"] = DELIVERY_REVISION
        patch["replacements"] = project_dynamic_replacements(patch["replacements"])
    return patch


def clock_patterns(active):
    def migrate(metadata):
        method = metadata["method"]
        method["elapsed_clock"] = deepcopy(refresh._PATTERN_CLOCK_METHOD)
        method["temporal_ordering"] = "DERIVED_SORT_BY_H_PARIS_SOURCE_ELAPSED_THEN_SOURCE_LINE"
        method["temporal_thinning"] = (
            "KEEP_FIRST_ANALYTICAL_TIME_THEN_ROWS_WHOSE_ELAPSED_DELTA_FROM_"
            "IMMEDIATELY_PREVIOUS_ANALYTICAL_TIME_IS_AT_LEAST_10_SECONDS"
        )
        for name in refresh._PATTERN_CLOCK_COUNT_KEYS:
            metadata["counts"].setdefault(name, 0)
    return {
        name: patterns.rewrite_pattern(value, metadata_change=migrate)
        for name, value in active.items()
    }


class ClockRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master, cls.payload, cls.review = processed.document()
        cls.patch = clock_patch(cls.payload, cls.review)
        cls.revised = refresh.refresh_processed(cls.master, patch_json(cls.patch))

    def test_bounded_projection_and_original_values(self):
        _, revised, _, review = refresh._processed_document(self.revised)
        refresh._validate_baseline_proof(revised)
        self.assertEqual(revised["metadata"]["source_clock_revision"], SOURCE_CLOCK_REVISION)
        self.assertEqual(review["source_clock_revision"], SOURCE_CLOCK_REVISION)
        for key in ("hourly", "daily", "thermal", "events", "origins", "thermal_coverage"):
            self.assertEqual(revised[key], self.payload[key])
        if "source_clock_revision" not in self.payload["metadata"]:
            for key, origin_index, columns in (
                ("global_hourly", 2, (4, 5, 6)),
                ("global_daily", 2, (7, 8, 9)),
                ("thermal_extended", 4, (6, 7, 10, 22, 24)),
            ):
                for old, new in zip(self.payload[key], revised[key], strict=True):
                    expected = deepcopy(old)
                    if 34 <= old[origin_index] <= 36:
                        for column in columns:
                            if old[column] is not None:
                                expected[column] = round(float(old[column]) + 0.0508, 12)
                    self.assertEqual(expected, new)
        boundary = next(row for row in revised["offsets"] if row[3] == 34)
        self.assertIs(boundary[4], False)
        self.assertEqual(boundary[9], 0.0)
        self.assertAlmostEqual(boundary[10], next(row[10] for row in revised["offsets"] if row[3] == 33), places=10)

    def test_repeated_refresh_is_byte_identical(self):
        self.assertEqual(
            refresh.refresh_processed(self.revised, patch_json(self.patch)),
            self.revised,
        )

    def test_unknown_or_false_clock_attestation_fails_closed(self):
        for field, value in (("version", True), ("trusted_utc", True), ("id", "other")):
            with self.subTest(field=field):
                patch = deepcopy(self.patch)
                patch["replacements"]["metadata"]["source_clock_revision"][field] = value
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_processed(self.master, patch_json(patch))

    def test_wrong_date_or_source_line_fails_closed(self):
        for field, value in (("date", "2026-03-28"), ("source_line", 2069215)):
            with self.subTest(field=field):
                patch = deepcopy(self.patch)
                patch["replacements"]["metadata"]["source_clock_revision"]["corrected_transitions"][0][field] = value
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_processed(self.master, patch_json(patch))

    def test_protocol_revision_cannot_be_forged_or_rolled_back(self):
        for protocol, revision in ((True, DELIVERY_REVISION), (2, "wrong"), (1, None)):
            with self.subTest(protocol=protocol, revision=revision):
                patch = deepcopy(self.patch)
                patch["protocol_version"] = protocol
                if revision is None:
                    patch.pop("delivery_revision")
                    patch["replacements"]["metadata"].pop("source_clock_revision")
                else:
                    patch["delivery_revision"] = revision
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_processed(self.revised, patch_json(patch))

    def test_unrelated_or_inexact_measurement_changes_are_rejected(self):
        cases = (("hourly", 0, 4), ("global_hourly", 0, 5),
                 ("global_hourly", -1, 5), ("thermal_extended", -1, 7))
        for key, row, column in cases:
            with self.subTest(key=key, row=row, column=column):
                patch = deepcopy(self.patch)
                patch["replacements"][key][row][column] += 0.001
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_processed(self.master, patch_json(patch))

    def test_thermal_identity_keeps_existing_tolerance(self):
        component = -0.09994542923746184 * (12.5 - 15.1)
        row = [None] * 29
        row[4], row[6], row[7], row[10] = 34, 0.0, 1.23456789, 1.23456789 - component
        fixture = {"global_hourly": [], "global_daily": [], "thermal_extended": [row],
                   "metadata": {"thermal_extension": {}}}
        projected = project_dynamic_replacements(fixture)["thermal_extended"][0]
        self.assertLess(abs(projected[10] - (projected[7] - component)), 1e-11)
        self.assertGreater(abs(round(row[10] + 0.0508, 10) - (projected[7] - component)), 1e-11)

    def test_static_revision_and_review_tampering_is_rejected(self):
        _, payload, _, review = refresh._processed_document(self.revised)
        for mutate in (
            lambda p: p["offsets"][-1].__setitem__(10, p["offsets"][-1][10] + 0.001),
            lambda p: p["resumptions"][-3].__setitem__(5, "OTHER"),
        ):
            candidate = deepcopy(payload)
            mutate(candidate)
            with self.assertRaises(refresh.RefreshError):
                refresh._validate_processed_payload(candidate)
        altered = deepcopy(review)
        altered["source_clock_revision"]["trusted_utc"] = True
        with self.assertRaises(refresh.RefreshError):
            refresh._validate_processed_review(altered)

    def test_projection_cannot_be_applied_twice(self):
        _, payload, _, review = refresh._processed_document(self.revised)
        with self.assertRaisesRegex(ValueError, "ALREADY_PROJECTED"):
            project_full_payload(payload)
        with self.assertRaisesRegex(ValueError, "FULL_LEGACY_REVIEW_REQUIRED"):
            project_review_diagnostics(review)

    def test_template_change_is_not_authorized_by_revision(self):
        altered = self.master.replace(b"<body>", b'<body class="unexpected">', 1)
        self.assertNotEqual(altered, self.master)
        with self.assertRaisesRegex(refresh.RefreshError, "TEMPLATE_DIVERGED"):
            refresh.refresh_processed(altered, patch_json(self.patch))


class PatternClockRevisionTests(unittest.TestCase):
    def test_exact_method_migration_preserves_protected_skeleton_and_is_idempotent(self):
        active = patterns.active_patterns()
        result = refresh.refresh_pattern_pair(active, clock_patterns(active))
        self.assertEqual(refresh.refresh_pattern_pair(result, result), result)
        for name in active:
            self.assertEqual(refresh.pattern_data_only_skeleton(active[name]),
                             refresh.pattern_data_only_skeleton(result[name]))

    def test_clock_method_mutation_is_rejected(self):
        active = patterns.active_patterns()
        for field, value in (("trusted_utc_produced", True),
                             ("maximum_transition_elapsed_seconds", 301)):
            candidate = clock_patterns(active)
            candidate[refresh.PATTERN_MEDIAN] = patterns.rewrite_pattern(
                candidate[refresh.PATTERN_MEDIAN], metadata_change=lambda m:
                m["method"]["elapsed_clock"].__setitem__(field, value))
            with self.subTest(field=field), self.assertRaises(refresh.RefreshError):
                refresh.refresh_pattern_pair(active, candidate)

    def test_unrelated_method_count_changes_and_rollback_are_rejected(self):
        active = patterns.active_patterns()
        candidate = clock_patterns(active)
        for mutate in (
            lambda m: m["method"].__setitem__("central_time_estimator", "OTHER"),
            lambda m: m["counts"].__setitem__("unapproved", 0),
            lambda m: m["counts"].__setitem__("recognized_daylight_saving_steps", True),
        ):
            altered = dict(candidate)
            altered[refresh.PATTERN_MEDIAN] = patterns.rewrite_pattern(
                altered[refresh.PATTERN_MEDIAN], metadata_change=mutate)
            with self.assertRaises(refresh.RefreshError):
                refresh.refresh_pattern_pair(active, altered)
        revised = refresh.refresh_pattern_pair(active, candidate)
        legacy = {}
        for name, value in active.items():
            def revert(m):
                m["method"], _ = refresh._pattern_legacy_method(m["method"])
                for key in refresh._PATTERN_CLOCK_COUNT_KEYS:
                    m["counts"].pop(key, None)
            legacy[name] = patterns.rewrite_pattern(value, metadata_change=revert)
        with self.assertRaisesRegex(refresh.RefreshError, "CLOCK_REVISION_ROLLBACK"):
            refresh.refresh_pattern_pair(revised, legacy)
