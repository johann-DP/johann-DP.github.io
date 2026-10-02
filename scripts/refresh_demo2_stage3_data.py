#!/usr/bin/env python3
"""Closed, data-only publication boundary for the three Stage 3 charts.

Editorial fields are never generated here. Their normalized fingerprints remain
part of the reviewed protected-site baseline. A ready release supplies data only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Mapping


ROOT = PurePosixPath("assets/analyses/demo-2/m12/data")
SLUGS = ("factors", "forecast", "pruning")
STAGE3_PATHS = frozenset(ROOT / f"{slug}.json" for slug in SLUGS)
READY = b"atomic-directory-publication-v1\n"
HASH = re.compile(r"[0-9a-f]{64}\Z")
METHOD = "stage3-m11-causal-v1"
MODEL_LABELS = {
    "persistence": {"Persistance"},
    "past_local_trend": {"Tendance locale passée", "Tendance locale (OLS)", "Tendance locale"},
    "ElasticNet_dynamic": {"ElasticNet"},
    "GAM_bounded_spline": {"GAM borné"},
    "CatBoost_compact_CPU": {"CatBoost CPU"},
}
HORIZONS = {"PROCHAIN_RELEVÉ_HEBDOMADAIRE_LEAD_6_7J": "6–7 jours",
            "RELEVÉ_J14_LEAD_13_14J": "13–14 jours", "RELEVÉ_J28_LEAD_27_28J": "27–28 jours"}
LEGACY_SIMULATION_SHA256 = "91f1a39ab4b9bcb0145adc9e94710d315423dc96b15a18fb9da5f3f270b1d519"


class Stage3DataError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Stage3DataError(code)


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_regular(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                "STAGE3_FILE_UNSAFE")
        require(metadata.st_size <= 20_000_000, "STAGE3_FILE_TOO_LARGE")
        return path.read_bytes()
    except OSError as error:
        raise Stage3DataError("STAGE3_FILE_UNAVAILABLE") from error


def parse(payload: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "STAGE3_DUPLICATE_KEY")
            result[key] = value
        return result
    try:
        value = json.loads(payload, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               Stage3DataError("STAGE3_NONFINITE")))
    except (UnicodeError, ValueError) as error:
        raise Stage3DataError("STAGE3_JSON_INVALID") from error
    require(isinstance(value, dict), "STAGE3_OBJECT_REQUIRED")
    _finite_tree(value)
    return value


def _finite_tree(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(isinstance(key, str), "STAGE3_KEY_INVALID")
            require(key not in {"source_parent_ids", "target_id", "observation_id"},
                    "STAGE3_PRIVATE_ID_FORBIDDEN")
            _finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            _finite_tree(child)
    elif isinstance(value, float):
        require(math.isfinite(value), "STAGE3_NONFINITE")
    elif isinstance(value, str):
        require(len(value) <= 5000 and not any(marker in value for marker in
                ("/media/", "/home/", "<script", "javascript:", "file://")),
                "STAGE3_PRIVATE_OR_EXECUTABLE_TEXT")


def _number(value: object, nullable: bool = False) -> None:
    require((nullable and value is None) or
            (type(value) in {float, int} and math.isfinite(value)), "STAGE3_NUMBER_INVALID")


def _count(value: object) -> None:
    require(type(value) is int and value >= 0, "STAGE3_COUNT_INVALID")


def _date(value: object) -> date:
    require(isinstance(value, str), "STAGE3_DATE_INVALID")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        raise Stage3DataError("STAGE3_DATE_INVALID") from error


def _ordered(rows: list, key: str) -> None:
    require(isinstance(rows, list) and 0 < len(rows) <= 100000, "STAGE3_ROWS_INVALID")
    previous = None
    for row in rows:
        require(isinstance(row, dict), "STAGE3_ROW_INVALID")
        stamp = row.get(key)
        _date(stamp)
        require(previous is None or stamp > previous, "STAGE3_ORDER_INVALID")
        previous = stamp


def _bounds(row: dict, lower: str, upper: str, value: str | None = None) -> None:
    low, high = row.get(lower), row.get(upper)
    _number(low, True)
    _number(high, True)
    require((low is None) == (high is None), "STAGE3_INTERVAL_PARTIAL")
    if low is not None:
        require(low <= high, "STAGE3_INTERVAL_REVERSED")
        if value is not None:
            require(low <= row[value] <= high, "STAGE3_POINT_OUTSIDE_INTERVAL")


def _mask_fields(value: dict, names: tuple[str, ...]) -> None:
    for name in names:
        if name in value:
            value[name] = "__DATA__"


def _validate_factors(value: dict) -> None:
    require(value.get("schema") == "m12-factors-public/2", "STAGE3_SCHEMA_INVALID")
    if "analysis_cutoff" in value:
        _date(value["analysis_cutoff"])
    rows = value.get("contrasts")
    require(isinstance(rows, list) and len(rows) == 19, "STAGE3_CONTRAST_SET_INVALID")
    require(len({r.get("id") for r in rows}) == 19, "STAGE3_CONTRAST_SET_INVALID")
    for row in rows:
        _count(row.get("n"))
        _number(row.get("gain_mae_mm"), True)
        bounds = row.get("simultaneous_95_mm", {})
        require(set(bounds) == {"lower", "upper", "status"}, "STAGE3_BOUND_SCHEMA_INVALID")
        _bounds(bounds, "lower", "upper")
        require(bounds.get("status") in {"ESTIMABLE", "NON_ESTIMABLE"}, "STAGE3_BOUND_STATUS_INVALID")
        require((bounds["status"] == "ESTIMABLE") == (bounds["lower"] is not None),
                "STAGE3_BOUND_STATUS_INVALID")
        require(row.get("verdict") in {"INCONCLUSIF", "GAIN", "PERTE", "GAIN_DEMONTRE",
                "PERTE_DEMONTREE", "AMELIORATION", "DEGRADATION"}, "STAGE3_VERDICT_INVALID")
    test = value.get("global_test", {})
    _number(test.get("p_value"), True)
    require(test["p_value"] is None or 0 <= test["p_value"] <= 1, "STAGE3_PVALUE_INVALID")
    expected_display = "p non calculable" if test["p_value"] is None else "p = " + f'{test["p_value"]:.3f}'.replace(".", ",")
    require(test.get("display") == expected_display, "STAGE3_PVALUE_DISPLAY_INVALID")
    for key in ("estimable_contrasts", "contrast_universe", "bootstrap_paths"):
        _count(test.get(key))
    require(test["contrast_universe"] == 19 and test["estimable_contrasts"] ==
            sum(r["simultaneous_95_mm"]["status"] == "ESTIMABLE" for r in rows),
            "STAGE3_SUPPORT_MISMATCH")
    for support in value.get("supports", []):
        _count(support.get("n"))
    diagnostic = value.get("joint_diagnostic", {})
    _count(diagnostic.get("n"))
    for key in ("pearson", "spearman", "p_value"):
        _number(diagnostic.get(key), True)


def _model(value: dict, key: str = "model") -> None:
    model = value.get(key)
    require(model in MODEL_LABELS and value.get("model_label") in MODEL_LABELS[model],
            "STAGE3_MODEL_LABEL_INVALID")


def _metric(value: dict) -> None:
    require(set(value) == {"horizon", "horizon_label", "model", "model_label", "targets",
                          "mae_mm", "wis_mm", "interval_targets", "coverage_80", "coverage_95",
                          "mean_width_80_mm", "mean_width_95_mm"}, "STAGE3_METRIC_SCHEMA_INVALID")
    _model(value)
    require(value.get("horizon") in HORIZONS and
            value.get("horizon_label") == HORIZONS[value["horizon"]], "STAGE3_HORIZON_LABEL_INVALID")
    _count(value["targets"])
    _count(value["interval_targets"])
    require(value["interval_targets"] <= value["targets"], "STAGE3_SUPPORT_MISMATCH")
    for key in ("mae_mm", "wis_mm", "coverage_80", "coverage_95", "mean_width_80_mm", "mean_width_95_mm"):
        _number(value[key], True)
        require(value[key] is None or value[key] >= 0, "STAGE3_METRIC_NEGATIVE")
    for key in ("coverage_80", "coverage_95"):
        require(value[key] is None or value[key] <= 1, "STAGE3_COVERAGE_INVALID")


def _validate_forecast(value: dict) -> None:
    require(value.get("schema") == "forecast-public/2", "STAGE3_SCHEMA_INVALID")
    observations = value.get("measurements")
    _ordered(observations, "date")
    for row in observations:
        require(set(row) == {"date", "value_mm"}, "STAGE3_MEASUREMENT_SCHEMA_INVALID")
        _number(row["value_mm"])
    _date(value.get("cutoff_date"))
    require(value["cutoff_date"][:10] <= observations[-1]["date"], "STAGE3_CUTOFF_INVALID")
    simulation = value.get("simulation", {})
    targets = simulation.get("targets")
    _ordered(targets, "date")
    require(1 <= len(targets) <= 3 and len({r.get("horizon") for r in targets}) == len(targets)
            and {r.get("horizon") for r in targets} <= {"7d", "14d", "28d"},
            "STAGE3_HORIZONS_INVALID")
    for row in targets:
        _number(row.get("predicted_mm"))
        _bounds(row, "lower80_mm", "upper80_mm", "predicted_mm")
        _bounds(row, "lower95_mm", "upper95_mm", "predicted_mm")
        for key in ("calibration_n", "selection_n"):
            _count(row.get(key))
        require(row.get("scientific_acceptance") is False, "STAGE3_ACCEPTANCE_FORBIDDEN")
    if simulation.get("issued_at") is not None:
        require(set(simulation) == {"method_id", "status", "generated_at", "issued_at", "data_cutoff",
                "origin_utc", "scenario", "targets", "scientific_acceptance", "selection_rule"},
                "STAGE3_SIMULATION_SCHEMA_INVALID")
        require(simulation.get("method_id") == METHOD, "STAGE3_METHOD_INVALID")
        require(simulation.get("status") == "PREVISION_EXPLORATOIRE_NON_VALIDEE",
                "STAGE3_ISSUANCE_STATUS_INVALID")
        require(simulation.get("issued_at") == simulation.get("generated_at"),
                "STAGE3_ISSUANCE_REWRITTEN")
        require(simulation.get("scientific_acceptance") is False and
                simulation.get("scenario") == "past_crack_calendar_only" and
                simulation.get("origin_utc") == simulation["issued_at"], "STAGE3_METHOD_INVALID")
        require(simulation.get("selection_rule") == {"mode": "MINIMUM_COMMON_PAST_WIS", "selection_n": 12,
                "reference_model": "persistence", "past_only": True, "common_cases": True,
                "tie_break": ["MAE", "fixed_model_order"]}, "STAGE3_SELECTION_RULE_CHANGED")
        issued = datetime.fromisoformat(simulation["issued_at"])
        require(issued.tzinfo is not None, "STAGE3_ISSUANCE_CLOCK_INVALID")
        require(all(_date(r["date"]) > issued.date() for r in targets),
                "STAGE3_RETRODATED_FORECAST")
        for row in targets:
            require(set(row) == {"horizon", "horizon_label", "date", "predicted_mm", "model", "model_label",
                    "calibration_n", "selection_n", "selection_mae_mm", "selection_wis_mm", "selection_score",
                    "selection_reference_model", "selection_reference_mae_mm", "selection_reference_wis_mm",
                    "feature_scope", "additional_data_groups_in_scope", "scientific_acceptance", "status",
                    "actual_lead_days", "lower80_mm", "upper80_mm", "lower95_mm", "upper95_mm"},
                    "STAGE3_TARGET_SCHEMA_INVALID")
            _model(row)
            require(row["model"] != "persistence" and row["selection_n"] == 12 and
                    row["selection_reference_model"] == "persistence" and
                    row["feature_scope"] == "RECENT_AND_CALENDAR_ONLY" and
                    row["additional_data_groups_in_scope"] == [] and
                    row["status"] == "PREVISION_EXPLORATOIRE_NON_VALIDEE", "STAGE3_TARGET_METHOD_INVALID")
            require(row["horizon_label"] == row["horizon"][:-1] + " jours", "STAGE3_HORIZON_LABEL_INVALID")
            leads = row["actual_lead_days"]
            require(isinstance(leads, list) and len(leads) == 2 and 0 < leads[0] < leads[1],
                    "STAGE3_TARGET_LEAD_INVALID")
            for key in ("selection_mae_mm", "selection_wis_mm", "selection_score",
                        "selection_reference_mae_mm", "selection_reference_wis_mm"):
                _number(row[key])
                require(row[key] >= 0, "STAGE3_METRIC_NEGATIVE")
    else:
        require(digest(canonical(simulation)) == LEGACY_SIMULATION_SHA256, "STAGE3_LEGACY_SIMULATION_REWRITTEN")
    metrics = value.get("metrics", [])
    require(len(metrics) == 15 and len({(r.get("model"), r.get("horizon")) for r in metrics}) == 15,
            "STAGE3_METRIC_SET_INVALID")
    for metric in metrics:
        _metric(metric)
    panels = value.get("historical_comparison", {}).get("panels", [])
    require(len(panels) == 3, "STAGE3_HISTORICAL_PANELS_INVALID")
    for panel in panels:
        require(set(panel) == {"horizon", "horizon_label", "selected_model", "model_label", "status",
                             "metrics", "persistence_metrics", "rows"}, "STAGE3_PANEL_SCHEMA_INVALID")
        _model(panel, "selected_model")
        require(panel.get("status") in {"COMPARAISON_HISTORIQUE_DESCRIPTIVE_PAS_DE_MODÈLE_RETENU",
                "COMPARAISON_HISTORIQUE_DESCRIPTIVE_PAS_DE_MODELE_VALIDE"}, "STAGE3_PANEL_STATUS_INVALID")
        _metric(panel["metrics"])
        _metric(panel["persistence_metrics"])
        rows = panel.get("rows")
        _ordered(rows, "target_date")
        require(panel["metrics"]["targets"] == len(rows) and panel["persistence_metrics"]["targets"] == len(rows),
                "STAGE3_SUPPORT_MISMATCH")
        require(panel["horizon"] == panel["metrics"]["horizon"] == panel["persistence_metrics"]["horizon"]
                and panel["model_label"] == panel["metrics"]["model_label"]
                and panel["selected_model"] == panel["metrics"]["model"]
                and panel["persistence_metrics"]["model"] == "persistence", "STAGE3_PANEL_METRICS_MIXED")
        for row in rows:
            require(set(row) == {"origin_utc", "target_date", "evaluation_at_utc", "observed_mm", "predicted_mm",
                    "persistence_mm", "lower80_mm", "upper80_mm", "lower95_mm", "upper95_mm",
                    "interval_available", "calibration_n", "training_n", "historical_backtest_not_actual_issuance"},
                    "STAGE3_BACKTEST_SCHEMA_INVALID")
            require(row.get("historical_backtest_not_actual_issuance") is True,
                    "STAGE3_BACKTEST_ISSUANCE_CONFUSION")
            require(_date(row.get("origin_utc")) < _date(row["target_date"]),
                    "STAGE3_BACKTEST_CAUSALITY_INVALID")
            for key in ("observed_mm", "predicted_mm", "persistence_mm"):
                _number(row.get(key))
            _bounds(row, "lower80_mm", "upper80_mm", "predicted_mm")
            _bounds(row, "lower95_mm", "upper95_mm", "predicted_mm")
            _count(row["calibration_n"])
            _count(row["training_n"])
            require(row["interval_available"] is (row["lower95_mm"] is not None), "STAGE3_INTERVAL_STATUS_INVALID")


def _validate_pruning(value: dict) -> None:
    require(value.get("schema") == "m12-pruning-public/2", "STAGE3_SCHEMA_INVALID")
    rows = value.get("comparator_series")
    _ordered(rows, "date")
    for row in rows:
        require(set(row) == {"date", "timestamp_ms", "raw_mm", "corrected_mm",
                            "temperature_c", "missing_reason"}, "STAGE3_THERMAL_SCHEMA_INVALID")
        _number(row.get("raw_mm"))
        _number(row.get("corrected_mm"), True)
        _number(row.get("temperature_c"), True)
        _number(row.get("timestamp_ms"))
        require(datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                == row["date"], "STAGE3_SOURCE_CLOCK_CHANGED")
        require((row["corrected_mm"] is None) == (row["missing_reason"] is not None),
                "STAGE3_THERMAL_MISSING_REASON_INVALID")
    comparator = value.get("comparator", {})
    counts = comparator.get("counts", {})
    require(set(counts) in ({"source_hours", "raw_hours", "corrected_hours", "temperature_present_hours",
                            "temperature_missing_hours", "temperature_outside_documented_domain_hours",
                            "correction_unavailable_hours"},
                           {"raw", "corrected", "missing_temperature", "out_of_domain", "other_missing"}),
            "STAGE3_THERMAL_COUNTS_SCHEMA_INVALID")
    for count in counts.values():
        _count(count)
    require(counts.get("raw_hours", counts.get("raw")) == len(rows) and counts.get("corrected_hours", counts.get("corrected")) ==
            sum(r["corrected_mm"] is not None for r in rows), "STAGE3_SUPPORT_MISMATCH")
    require(comparator.get("period", {}).get("start") == rows[0]["date"] and
            comparator.get("period", {}).get("end") == rows[-1]["date"], "STAGE3_PERIOD_MISMATCH")
    require(set(comparator["period"]) <= {"start", "end", "first_corrected", "last_corrected"},
            "STAGE3_PERIOD_SCHEMA_INVALID")
    _count(comparator.get("segment"))
    _number(comparator.get("center_mm"))


def data_only_skeleton(slug: str, payload: bytes | dict) -> bytes:
    """Normalize only explicitly authorized chart values, not editorial prose."""
    value = parse(canonical(payload) if isinstance(payload, dict) else payload)
    {"factors": _validate_factors, "forecast": _validate_forecast,
     "pruning": _validate_pruning}[slug](value)
    result = deepcopy(value)
    runtime = result.get("runtime_metadata")
    if runtime is not None:
        require(set(runtime) in ({"protocol_version", "protocol_sha256", "generated_at",
                                 "scientific_acceptance", "editorial_updated"},
                                {"protocol_version", "protocol_sha256", "generated_at",
                                 "scientific_acceptance", "editorial_updated", "input_sha256",
                                 "implementation_sha256"}), "STAGE3_RUNTIME_SCHEMA_INVALID")
        require(runtime["protocol_version"] == METHOD and HASH.fullmatch(runtime["protocol_sha256"]) is not None
                and runtime["scientific_acceptance"] is False and runtime["editorial_updated"] is False,
                "STAGE3_RUNTIME_METHOD_INVALID")
        require(datetime.fromisoformat(runtime["generated_at"]).tzinfo is not None,
                "STAGE3_RUNTIME_CLOCK_INVALID")
        for key in ("input_sha256", "implementation_sha256"):
            if key in runtime:
                require(isinstance(runtime[key], str) and HASH.fullmatch(runtime[key]) is not None,
                        "STAGE3_RUNTIME_ID_INVALID")
    result.pop("runtime_metadata", None)
    if slug == "factors":
        result["analysis_cutoff"] = "__DATA__"
        for row in result["contrasts"]:
            _mask_fields(row, ("n", "gain_mae_mm", "simultaneous_95_mm"))
        _mask_fields(result["global_test"], ("p_value", "display", "estimable_contrasts",
                                          "contrast_universe", "bootstrap_paths"))
        for row in result["supports"]:
            _mask_fields(row, ("n",))
        _mask_fields(result["joint_diagnostic"], ("n", "pearson", "spearman", "p_value"))
    elif slug == "forecast":
        _mask_fields(result, ("measurements", "cutoff_date", "metrics", "simulation"))
        result["historical_comparison"]["panels"] = "__DATA__"
    else:
        result["comparator_series"] = "__DATA__"
        _mask_fields(result["comparator"], ("segment", "center_mm", "counts", "period"))
    return canonical(result)


def validate_stage3_outputs(site_root: Path, outputs: Mapping[PurePosixPath, bytes]) -> None:
    require(set(outputs) == STAGE3_PATHS, "STAGE3_OUTPUT_SET_INVALID")
    require(all((site_root / parent).is_dir() and not (site_root / parent).is_symlink()
                for parent in (ROOT, *tuple(ROOT.parents)[:-1])), "STAGE3_DIRECTORY_UNSAFE")
    metadata = []
    for slug in SLUGS:
        relative = ROOT / f"{slug}.json"
        active = read_regular(site_root / relative)
        candidate = outputs[relative]
        require(data_only_skeleton(slug, active) == data_only_skeleton(slug, candidate),
                "STAGE3_EDITORIAL_CHANGED")
        old, new = parse(active), parse(candidate)
        if slug == "forecast":
            require(new["measurements"][:len(old["measurements"])] == old["measurements"],
                    "STAGE3_OBSERVATIONS_REWRITTEN")
            require(new["cutoff_date"] >= old["cutoff_date"], "STAGE3_CUTOFF_REGRESSION")
            if old["simulation"].get("issued_at") is not None:
                require(new["simulation"].get("issued_at") is not None and
                        new["simulation"]["issued_at"] >= old["simulation"]["issued_at"],
                        "STAGE3_ISSUANCE_REGRESSION")
                if new["simulation"]["issued_at"] == old["simulation"]["issued_at"]:
                    require(new["simulation"] == old["simulation"], "STAGE3_ISSUANCE_REWRITTEN")
        metadata.append(new.get("runtime_metadata"))
    if any(item is not None for item in metadata):
        require(all(item is not None for item in metadata), "STAGE3_GENERATION_MIXED")
        # A bundle may reuse an unchanged calculation: calculation dates and
        # relevant-input hashes are per chart, but its executable protocol is one.
        common = [{key: item.get(key) for key in
                   ("protocol_version", "protocol_sha256", "implementation_sha256")}
                  for item in metadata]
        require(common[0] == common[1] == common[2], "STAGE3_GENERATION_MIXED")


def validate_stage3_data(site_root: Path) -> None:
    directory = site_root / ROOT
    require(directory.is_dir() and not directory.is_symlink(), "STAGE3_DIRECTORY_UNSAFE")
    require({p.name for p in directory.iterdir()} == {f"{slug}.json" for slug in SLUGS},
            "STAGE3_FILE_SET_INVALID")
    outputs = {path: read_regular(site_root / path) for path in STAGE3_PATHS}
    validate_stage3_outputs(site_root, outputs)


def prepare_stage3_outputs(site_root: Path, release_root: Path) -> dict[PurePosixPath, bytes]:
    require(release_root.is_dir() and not release_root.is_symlink(), "STAGE3_RELEASE_UNSAFE")
    require((release_root / "data").is_dir() and not (release_root / "data").is_symlink(),
            "STAGE3_RELEASE_UNSAFE")
    require(read_regular(release_root / ".READY") == READY, "STAGE3_RELEASE_NOT_READY")
    manifest = parse(read_regular(release_root / "content-manifest.json"))
    require(manifest.get("schema") == "stage3-public-release/1", "STAGE3_RELEASE_SCHEMA_INVALID")
    require(HASH.fullmatch(release_root.name) is not None and
            manifest.get("release_id") == release_root.name, "STAGE3_RELEASE_ID_INVALID")
    records = manifest.get("files", [])
    require(isinstance(records, list) and len(records) == 3, "STAGE3_RELEASE_FILE_SET_INVALID")
    records = {item.get("path"): item for item in records}
    require(set(records) == {f"data/{slug}.json" for slug in SLUGS}, "STAGE3_RELEASE_FILE_SET_INVALID")
    result = {}
    for slug in SLUGS:
        record = records[f"data/{slug}.json"]
        payload = read_regular(release_root / record["path"])
        require(digest(payload) == record.get("sha256") and len(payload) == record.get("size_bytes"),
                "STAGE3_RELEASE_HASH_MISMATCH")
        result[ROOT / f"{slug}.json"] = payload
    validate_stage3_outputs(site_root, result)
    if manifest.get("generated_at"):
        generated = datetime.fromisoformat(manifest["generated_at"])
        require(generated.tzinfo is not None, "STAGE3_RELEASE_CLOCK_INVALID")
        for payload in result.values():
            metadata = parse(payload).get("runtime_metadata")
            if metadata:
                require(datetime.fromisoformat(metadata["generated_at"]) <= generated,
                        "STAGE3_CALCULATION_AFTER_RELEASE")
    return result


def promote_stage3_outputs(site_root: Path, outputs: Mapping[PurePosixPath, bytes],
                          source_ids: tuple[str, ...]) -> dict:
    """Called only while the existing Demo 2 promotion lock is held.

    The old data directory is retained. A killed process is recognized by the
    exact before/after digests before the next exchange; no forecast is rewritten.
    """
    import promote_demo2_validated_release as promoter

    validate_stage3_outputs(site_root, outputs)
    active = site_root / ROOT
    transactions = site_root / promoter.TRANSACTION_ROOT_RELATIVE / "stage3"
    transactions.mkdir(mode=0o700, exist_ok=True)
    for path in sorted(transactions.iterdir()):
        require(path.is_dir() and not path.is_symlink(), "STAGE3_JOURNAL_UNSAFE")
        journal = parse(read_regular(path / "transaction.json"))
        if journal.get("phase") not in {"PREPARED", "COMMITTING"}:
            continue
        current = promoter._tree_digest(active)
        other = promoter._tree_digest(path / "counterpart")
        if (current, other) == (journal["new_tree_sha256"], journal["old_tree_sha256"]):
            promoter._set_phase(path, journal, "COMMITTED")
        elif (current, other) == (journal["old_tree_sha256"], journal["new_tree_sha256"]):
            promoter._set_phase(path, journal, "ROLLED_BACK")
        else:
            raise Stage3DataError("STAGE3_RECOVERY_DIVERGED")
    changed = {path: payload for path, payload in outputs.items()
               if read_regular(site_root / path) != payload}
    if not changed:
        return {"status": "ALREADY_ACTIVE", "updated_master_count": 0}
    old_digest = promoter._tree_digest(active)
    identity = {"old": old_digest, "files": {str(p): digest(v) for p, v in sorted(outputs.items())},
                "sources": list(source_ids)}
    transaction_id = digest(canonical(identity))
    transaction = transactions / transaction_id
    attempt = 1
    while transaction.exists():
        attempt += 1
        transaction = transactions / f"{transaction_id}-{attempt}"
    preparations = transactions.parent / "stage3-preparations"
    preparations.mkdir(mode=0o700, exist_ok=True)
    prepared = Path(tempfile.mkdtemp(prefix="prepared-", dir=preparations))
    counterpart = prepared / "counterpart"
    shutil.copytree(active, counterpart)
    for relative, payload in outputs.items():
        destination = counterpart / relative.name
        with destination.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        destination.chmod(0o644)
    new_digest = promoter._tree_digest(counterpart)
    journal = {"version": 1, "phase": "PREPARED", "old_tree_sha256": old_digest,
               "new_tree_sha256": new_digest, "transaction_id": transaction_id,
               "targets": sorted(str(p) for p in changed)}
    promoter._write_journal(prepared, journal)
    promoter._fsync_directory(counterpart)
    os.rename(prepared, transaction)
    promoter._fsync_directory(transactions)
    counterpart = transaction / "counterpart"
    promoter._set_phase(transaction, journal, "COMMITTING")
    exchanged = False
    try:
        promoter._rename_exchange(active, counterpart)
        exchanged = True
        promoter._fsync_directory(active.parent)
        promoter._fsync_directory(transaction)
        _after_stage3_exchange()
        validate_stage3_data(site_root)
        require(promoter._tree_digest(active) == new_digest, "STAGE3_POST_COMMIT_DIVERGED")
        promoter._set_phase(transaction, journal, "COMMITTED")
    except Exception:
        if exchanged:
            promoter._rename_exchange(active, counterpart)
            promoter._fsync_directory(active.parent)
            promoter._fsync_directory(transaction)
        require(promoter._tree_digest(active) == old_digest, "STAGE3_ROLLBACK_DIVERGED")
        promoter._set_phase(transaction, journal, "ROLLED_BACK")
        raise
    return {"status": "PROMOTED", "updated_master_count": len(changed),
            "transaction_id": transaction_id}


def _after_stage3_exchange() -> None:
    """Causal crash/rollback test boundary."""
