from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_demo2_stage3_data as stage3  # noqa: E402
import promote_demo2_validated_release as promoter  # noqa: E402
from tests.test_validate_demo2_active_figures import build_active_site  # noqa: E402
from tests.test_promote_demo2_validated_release import TARGET, figure, set_active_payload  # noqa: E402


def fixture_simulation(issued_at="2026-09-25T12:00:00+00:00", days=(7, 14, 28)):
    """Synthetic test data only: fixed clock, never copied from live forecasts."""
    issued = datetime.fromisoformat(issued_at)
    targets = []
    for horizon in days:
        target = datetime(2026, 9, 24, tzinfo=ZoneInfo("Europe/Paris")) + timedelta(days=horizon)
        lead = (target - issued).total_seconds() / 86400
        targets.append({
            "horizon": f"{horizon}d", "horizon_label": f"{horizon} jours",
            "date": target.date().isoformat(), "predicted_mm": 30.82,
            "model": "ElasticNet_dynamic", "model_label": "ElasticNet",
            "calibration_n": 40, "selection_n": 12, "selection_mae_mm": .02,
            "selection_wis_mm": .02, "selection_score": .02,
            "selection_reference_model": "persistence", "selection_reference_mae_mm": .03,
            "selection_reference_wis_mm": .03, "lower80_mm": 30.75, "upper80_mm": 30.85,
            "lower95_mm": 30.7, "upper95_mm": 30.9, "feature_scope": "RECENT_AND_CALENDAR_ONLY",
            "additional_data_groups_in_scope": [], "scientific_acceptance": False,
            "status": "PREVISION_EXPLORATOIRE_NON_VALIDEE", "actual_lead_days": [lead, lead + 1],
        })
    return {
        "method_id": stage3.METHOD, "status": "PREVISION_EXPLORATOIRE_NON_VALIDEE",
        "generated_at": issued_at, "issued_at": issued_at, "origin_utc": issued_at,
        "data_cutoff": "2026-09-24T00:00:00", "scenario": "past_crack_calendar_only",
        "targets": targets, "scientific_acceptance": False,
        "selection_rule": {"mode": "MINIMUM_COMMON_PAST_WIS", "selection_n": 12,
                           "reference_model": "persistence", "past_only": True, "common_cases": True,
                           "tie_break": ["MAE", "fixed_model_order"]},
    }


def fixture_payloads(public):
    """Reuse the reviewed editorial schema, replace every changing chart value.

    The public snapshot is independently validated below. It is not the clock or
    observation fixture for transaction tests, which must survive later updates.
    """
    values = {slug: deepcopy(public[slug]) for slug in stage3.SLUGS}
    for value in values.values():
        value.pop("runtime_metadata", None)
    factors = values["factors"]
    factors["analysis_cutoff"] = "2026-09-24"
    for row in factors["contrasts"]:
        row.update(n=28, gain_mae_mm=.002, simultaneous_95_mm={
            "lower": -.004, "upper": .01, "status": "ESTIMABLE"})
    factors["global_test"].update(p_value=.4, display="p = 0,400", estimable_contrasts=19,
                                  contrast_universe=19, bootstrap_paths=1000)
    for support in factors["supports"]:
        support["n"] = 100
    factors["joint_diagnostic"].update(n=100, pearson=.1, spearman=.1, p_value=None)
    forecast = values["forecast"]
    forecast["measurements"] = [{"date": "2026-09-17", "value_mm": 30.79},
                                {"date": "2026-09-24", "value_mm": 30.8}]
    forecast["cutoff_date"] = "2026-09-24"
    forecast["simulation"] = fixture_simulation()
    for metric in forecast["metrics"]:
        metric.update(targets=1, interval_targets=1, mae_mm=.02, wis_mm=.02,
                      coverage_80=1., coverage_95=1., mean_width_80_mm=.1, mean_width_95_mm=.2)
    for panel, horizon in zip(forecast["historical_comparison"]["panels"], (7, 14, 28), strict=True):
        panel.update(selected_model="ElasticNet_dynamic", model_label="ElasticNet")
        panel["metrics"] = deepcopy(next(m for m in forecast["metrics"]
                                            if m["horizon"] == panel["horizon"] and m["model"] == "ElasticNet_dynamic"))
        panel["persistence_metrics"] = deepcopy(next(m for m in forecast["metrics"]
                                                        if m["horizon"] == panel["horizon"] and m["model"] == "persistence"))
        target = datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=horizon)
        panel["rows"] = [{"origin_utc": "2026-08-01T00:00:00+00:00",
                          "target_date": target.date().isoformat(),
                          "evaluation_at_utc": (target + timedelta(days=1)).isoformat(),
                          "observed_mm": 30.8, "predicted_mm": 30.82, "persistence_mm": 30.79,
                          "lower80_mm": 30.75, "upper80_mm": 30.85,
                          "lower95_mm": 30.7, "upper95_mm": 30.9,
                          "interval_available": True, "calibration_n": 40, "training_n": 50,
                          "historical_backtest_not_actual_issuance": True}]
    pruning = values["pruning"]
    start = datetime(2026, 9, 24, 8, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    pruning["comparator_series"] = [
        {"date": start.strftime("%Y-%m-%dT%H:%M:%S"), "timestamp_ms": int(start.timestamp()*1000),
         "raw_mm": .02, "corrected_mm": .01, "temperature_c": 16., "missing_reason": None},
        {"date": end.strftime("%Y-%m-%dT%H:%M:%S"), "timestamp_ms": int(end.timestamp()*1000),
         "raw_mm": .03, "corrected_mm": None, "temperature_c": None,
         "missing_reason": "Température exacte indisponible"},
    ]
    pruning["comparator"].update(segment=36, center_mm=-.4318,
        counts={"raw": 2, "corrected": 1, "missing_temperature": 1, "out_of_domain": 0, "other_missing": 0},
        period={"start": start.strftime("%Y-%m-%dT%H:%M:%S"), "end": end.strftime("%Y-%m-%dT%H:%M:%S")})
    return values


class Stage3DataPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.site = Path(self.temporary.name) / "site"
        self.site.mkdir()
        build_active_site(self.site)
        public = {slug: json.loads((ROOT / stage3.ROOT / f"{slug}.json").read_bytes()) for slug in stage3.SLUGS}
        (self.site / stage3.ROOT).mkdir(parents=True)
        for slug, value in fixture_payloads(public).items():
            (self.site / stage3.ROOT / f"{slug}.json").write_bytes(stage3.canonical(value))
        self.original = {p: (self.site / p).read_bytes() for p in stage3.STAGE3_PATHS}

    def tearDown(self):
        self.temporary.cleanup()

    def candidate(self):
        result = dict(self.original)
        path = stage3.ROOT / "forecast.json"
        value = json.loads(result[path])
        value["measurements"].append({"date": "2026-10-01", "value_mm": 30.81})
        result[path] = stage3.canonical(value)
        return result

    def issued_candidate(self):
        candidate = dict(self.original)
        path = stage3.ROOT / "forecast.json"
        value = json.loads(candidate[path])
        value["simulation"] = fixture_simulation("2026-10-02T12:00:00+00:00", (14, 28))
        candidate[path] = stage3.canonical(value)
        return candidate

    def test_existing_public_payloads_validate(self):
        stage3.validate_stage3_data(ROOT)
        stage3.validate_stage3_data(self.site)

    def test_fixture_clock_and_measurements_do_not_depend_on_later_publications(self):
        public = {slug: json.loads((ROOT / stage3.ROOT / f"{slug}.json").read_bytes()) for slug in stage3.SLUGS}
        original_fixture = fixture_payloads(public)
        later = deepcopy(public)
        for day in ("2026-10-04", "2026-10-11", "2027-01-03"):
            later["forecast"]["measurements"].append({"date": day, "value_mm": 31.})
        later["forecast"]["cutoff_date"] = "2027-01-03"
        later["forecast"]["simulation"].update(issued_at="2027-01-03T12:00:00+00:00", targets=[])
        later["forecast"]["metrics"][0]["mae_mm"] = 99.
        later["forecast"]["historical_comparison"]["panels"][0]["rows"] = []
        later["factors"]["analysis_cutoff"] = "2027-01-03"
        later["factors"]["contrasts"][0]["gain_mae_mm"] = 99.
        later["pruning"]["comparator_series"] = []
        later["pruning"]["comparator"].update(segment=99, center_mm=123., counts={}, period={})
        self.assertEqual(fixture_payloads(later), original_fixture)

    def test_new_observation_keeps_editorial_fingerprints(self):
        candidate = self.candidate()
        stage3.validate_stage3_outputs(self.site, candidate)
        for path in candidate:
            self.assertEqual(stage3.data_only_skeleton(path.stem, candidate[path]),
                             stage3.data_only_skeleton(path.stem, self.original[path]))

    def test_editorial_change_is_rejected_even_inside_json(self):
        for slug, key in (("forecast", "interpretation"), ("pruning", "conclusion"),
                          ("factors", "provenance")):
            candidate = self.candidate()
            path = stage3.ROOT / f"{slug}.json"
            value = json.loads(candidate[path])
            value[key] = "Une conclusion automatiquement réécrite"
            candidate[path] = stage3.canonical(value)
            with self.subTest(slug=slug), self.assertRaisesRegex(stage3.Stage3DataError, "EDITORIAL_CHANGED"):
                stage3.validate_stage3_outputs(self.site, candidate)

    def test_revised_observation_is_not_an_append(self):
        candidate = self.candidate()
        path = stage3.ROOT / "forecast.json"
        value = json.loads(candidate[path])
        value["measurements"][0]["value_mm"] += .01
        candidate[path] = stage3.canonical(value)
        with self.assertRaisesRegex(stage3.Stage3DataError, "OBSERVATIONS_REWRITTEN"):
            stage3.validate_stage3_outputs(self.site, candidate)

    def test_partial_bundle_and_mixed_generation_rejected(self):
        candidate = self.candidate()
        with self.assertRaisesRegex(stage3.Stage3DataError, "OUTPUT_SET_INVALID"):
            stage3.validate_stage3_outputs(self.site, {next(iter(candidate)): next(iter(candidate.values()))})
        path = stage3.ROOT / "forecast.json"
        value = json.loads(candidate[path])
        value["runtime_metadata"] = {"protocol_version": stage3.METHOD, "protocol_sha256": "a" * 64,
                                     "generated_at": "2026-10-02T13:00:00+00:00",
                                     "scientific_acceptance": False, "editorial_updated": False}
        candidate[path] = stage3.canonical(value)
        with self.assertRaisesRegex(stage3.Stage3DataError, "GENERATION_MIXED"):
            stage3.validate_stage3_outputs(self.site, candidate)

    def test_duplicate_keys_and_nonfinite_rejected(self):
        for invalid in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'):
            with self.subTest(invalid=invalid), self.assertRaises(stage3.Stage3DataError):
                stage3.parse(invalid)

    def test_new_emission_may_have_only_unexpired_horizons(self):
        stage3.validate_stage3_outputs(self.site, self.issued_candidate())

    def test_unchanged_chart_may_retain_its_own_calculation_date(self):
        candidate = self.candidate()
        for index, path in enumerate(sorted(candidate)):
            value = json.loads(candidate[path])
            value["runtime_metadata"] = {"protocol_version": stage3.METHOD, "protocol_sha256": "a" * 64,
                    "generated_at": f"2026-10-02T1{index}:00:00+00:00", "input_sha256": str(index) * 64,
                    "implementation_sha256": "b" * 64, "scientific_acceptance": False, "editorial_updated": False}
            candidate[path] = stage3.canonical(value)
        stage3.validate_stage3_outputs(self.site, candidate)
        path = stage3.ROOT / "forecast.json"
        value = json.loads(candidate[path])
        value["runtime_metadata"]["implementation_sha256"] = "c" * 64
        candidate[path] = stage3.canonical(value)
        with self.assertRaisesRegex(stage3.Stage3DataError, "GENERATION_MIXED"):
            stage3.validate_stage3_outputs(self.site, candidate)

    def test_new_emission_cannot_contain_extra_prose_or_past_targets(self):
        path = stage3.ROOT / "forecast.json"
        for mutation, code in ((lambda s: s.update(conclusion="Tout va bien"), "SIMULATION_SCHEMA"),
                               (lambda s: s["targets"][0].update(date="2026-10-01"), "RETRODATED")):
            candidate = self.issued_candidate()
            value = json.loads(candidate[path])
            mutation(value["simulation"])
            candidate[path] = stage3.canonical(value)
            with self.subTest(code=code), self.assertRaisesRegex(stage3.Stage3DataError, code):
                stage3.validate_stage3_outputs(self.site, candidate)

    def test_previous_emission_is_not_rewritten(self):
        candidate = self.issued_candidate()
        promoter.promote_prepared_outputs(candidate, ("stage3:" + "c" * 64,), site_root=self.site)
        path = stage3.ROOT / "forecast.json"
        value = json.loads(candidate[path])
        value["simulation"]["targets"][0]["predicted_mm"] += .001
        candidate[path] = stage3.canonical(value)
        with self.assertRaisesRegex(stage3.Stage3DataError, "ISSUANCE_REWRITTEN"):
            stage3.validate_stage3_outputs(self.site, candidate)

    def test_promotes_only_three_data_files_and_is_idempotent(self):
        before = {p.relative_to(self.site): p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        candidate = self.candidate()
        result = promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(result["updated_master_count"], 1)
        for path, payload in before.items():
            self.assertEqual((self.site / path).read_bytes(), candidate.get(path, payload))
        second = promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        self.assertEqual(second["status"], "ALREADY_ACTIVE")
        self.assertEqual(second["updated_master_count"], 0)
        transactions = self.site / promoter.TRANSACTION_ROOT_RELATIVE / "stage3"
        retained = next(transactions.iterdir()) / "counterpart"
        for path, payload in self.original.items():
            self.assertEqual((retained / path.name).read_bytes(), payload)

    def test_failure_rolls_back_and_retry_preserves_previous_tree(self):
        candidate = self.candidate()
        with patch.object(stage3, "_after_stage3_exchange", side_effect=RuntimeError("interruption")):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        for path, payload in self.original.items():
            self.assertEqual((self.site / path).read_bytes(), payload)
        result = promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        self.assertEqual(result["status"], "PROMOTED")

    def test_hard_interruption_after_exchange_is_recognised_on_retry(self):
        candidate = self.candidate()
        with patch.object(stage3, "_after_stage3_exchange", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        result = promoter.promote_prepared_outputs(candidate, ("stage3:" + "a" * 64,), site_root=self.site)
        self.assertEqual(result["status"], "ALREADY_ACTIVE")
        transactions = self.site / promoter.TRANSACTION_ROOT_RELATIVE / "stage3"
        journal = json.loads((next(transactions.iterdir()) / "transaction.json").read_bytes())
        self.assertEqual(journal["phase"], "COMMITTED")

    def test_mixed_promotion_resumes_after_stage_two_changed_and_stage_three_failed(self):
        set_active_payload(self.site, TARGET, figure('[{"x":[1]}]'))
        path = Path("assets/figures/demo-2") / TARGET
        candidate = self.candidate()
        candidate[stage3.PurePosixPath(path)] = figure('[{"x":[2]}]')
        with patch.object(stage3, "_after_stage3_exchange", side_effect=RuntimeError("interruption")):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                promoter.promote_prepared_outputs(candidate, ("stage3:" + "d" * 64,), site_root=self.site)
        self.assertEqual((self.site / path).read_bytes(), candidate[stage3.PurePosixPath(path)])
        for json_path, payload in self.original.items():
            self.assertEqual((self.site / json_path).read_bytes(), payload)
        result = promoter.promote_prepared_outputs(candidate, ("stage3:" + "d" * 64,), site_root=self.site)
        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(result["updated_master_count"], 1)
        repeat = promoter.promote_prepared_outputs(candidate, ("stage3:" + "d" * 64,), site_root=self.site)
        self.assertEqual(repeat["status"], "ALREADY_ACTIVE")

    def test_invalid_stage_three_never_mutates_stage_two(self):
        current = figure('[{"x":[1]}]')
        set_active_payload(self.site, TARGET, current)
        path = stage3.PurePosixPath("assets/figures/demo-2") / TARGET
        candidate = self.candidate()
        candidate[path] = figure('[{"x":[2]}]')
        candidate[stage3.ROOT / "pruning.json"] = b'{}'
        with self.assertRaises(stage3.Stage3DataError):
            promoter.promote_prepared_outputs(candidate, ("stage3:" + "e" * 64,), site_root=self.site)
        self.assertEqual((self.site / path).read_bytes(), current)

    def test_ready_release_hashes_are_verified_before_any_mutation(self):
        candidate = self.candidate()
        release = Path(self.temporary.name) / ("b" * 64)
        (release / "data").mkdir(parents=True)
        records = []
        for path, payload in candidate.items():
            (release / "data" / path.name).write_bytes(payload)
            records.append({"path": "data/" + path.name, "sha256": stage3.digest(payload),
                            "size_bytes": len(payload)})
        manifest = {"schema": "stage3-public-release/1", "release_id": release.name, "files": records}
        (release / "content-manifest.json").write_bytes(stage3.canonical(manifest))
        (release / ".READY").write_bytes(stage3.READY)
        self.assertEqual(stage3.prepare_stage3_outputs(self.site, release), candidate)
        (release / "data/forecast.json").write_bytes(b"{}")
        with self.assertRaisesRegex(stage3.Stage3DataError, "HASH_MISMATCH"):
            stage3.prepare_stage3_outputs(self.site, release)
        for path, payload in self.original.items():
            self.assertEqual((self.site / path).read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
