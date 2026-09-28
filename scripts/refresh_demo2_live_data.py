#!/usr/bin/env python3
"""Fail-closed, data-only refresh for the validated Demo 2 masters.

This module deliberately does not know how measurements are calculated.  It
accepts approved ``.READY`` HTML payloads (or already-refreshed manual bytes),
proves that their presentation is unchanged, and returns a complete staging
mapping.  Callers may write that mapping only after this function succeeds.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from statistics import median
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


SITE_ROOT = Path(__file__).resolve().parents[1]
FIGURES = PurePosixPath("assets/figures/demo-2")
READY = ".READY"
READY_CONTENT = b"atomic-directory-publication-v1\n"
CONTENT_MANIFEST = "content-manifest.json"
HASH = re.compile(r"[0-9a-f]{64}", re.ASCII)
LEGACY = (
    "meteo_temperature.html", "meteo_temp_minmax.html", "meteo_humidity.html",
    "meteo_light_uv.html", "meteo_precipitation.html", "meteo_wind_speed.html",
    "meteo_pairplots.html",
)
PATTERN_MEDIAN = "retaining-wall-median-day.html"
PATTERN_EXTREMA = "retaining-wall-extrema-hours.html"
PATTERN_TARGETS = frozenset((PATTERN_MEDIAN, PATTERN_EXTREMA))
PATTERN_ROLES = {
    PATTERN_MEDIAN: "legacy_half_hour_median_profile_candidate",
    PATTERN_EXTREMA: "legacy_daily_extrema_distributions_candidate",
}
FROZEN = frozenset(("weather/legacy/meteo_wind_dir.html",))
_SCRIPT_PAYLOAD = re.compile(br'(<script id="payload" type="application/json">)(.*?)(</script>)', re.S)
_RAW_PAYLOAD = re.compile(br'(<script id="d2-cap-payload"[^>]*>)(.*?)(</script>)', re.S)
_FIGURE_METADATA = re.compile(br'const\s+FIGURE_METADATA\s*=\s*\{.*?\};', re.S)
_PATTERN_PAYLOAD = re.compile(
    br'(<script id="pattern-payload" type="application/json">)(.*?)(</script>)',
    re.S,
)
_PATTERN_METADATA_PREFIX = re.compile(br"const\s+PATTERN_METADATA\s*=\s*")
_PATTERN_CARDS = re.compile(
    br'<section class="cards" aria-label="Rep\xc3\xa8res statistiques">.*?</section>',
    re.S,
)
_PARAGRAPH = re.compile(br"<p\b[^>]*>.*?</p>", re.I | re.S)
_STRONG = re.compile(br'(<strong(?:\s+[^>]*)?>)(.*?)(</strong>)', re.S)
_MEASURE_COUNT = re.compile(br"\b[0-9]+(?=\s+mesures\b)")
_PATTERN_METADATA_KEYS = frozenset(
    {
        "analysis_id",
        "axes",
        "bootstrap",
        "counts",
        "figure_id",
        "limits",
        "method",
        "review_status",
        "semantics",
    }
)
_PATTERN_STATIC_METADATA_KEYS = frozenset(
    {"analysis_id", "axes", "figure_id", "limits", "method", "semantics"}
)
PROCESSED_PATCH = "processed-signal-payload-patch.json"
PROCESSED_PATCH_ROLE = "processed_signal_payload_patch"
PROCESSED_TARGET = "retaining-wall-sensor-processed-v2.html"
PROCESSED_LOGICAL_ASSET_ID = "retaining-wall-sensor-processed-v2"
PROCESSED_PROTOCOL_VERSION = 1
PROCESSED_BASE_PAYLOAD_SHA256 = (
    "96a53097b26e3454f29a6290a915adb0e9cbee22cb89ba8eacc73bf5b1333696"
)
PROCESSED_BASE_TEMPLATE_SHA256 = (
    "9d8d4aef184b36804ba8a59f9f8e06cb0e583d28c67f0449af858b00efba848d"
)
MAX_PROCESSED_PATCH_BYTES = 32 * 1024 * 1024
MAX_PROCESSED_MASTER_BYTES = 40 * 1024 * 1024
_PROCESSED_PAYLOAD = re.compile(
    br'(<script id="processed-signal-payload" type="application/json">)(.*?)(</script>)',
    re.S,
)
_REVIEW_DIAGNOSTICS = re.compile(
    br'(<script id="review-diagnostics" type="application/json">)(.*?)(</script>)',
    re.S,
)
_SOURCE_HOUR = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:00:00\Z", re.ASCII)
_SOURCE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
_MONTH = re.compile(r"\d{4}-\d{2}\Z", re.ASCII)
_PARIS = ZoneInfo("Europe/Paris")
_UTC = ZoneInfo("UTC")
_HOUR_MILLISECONDS = 3_600_000
_SG5_WEIGHTS = (
    -0.08571428571428572,
    0.34285714285714286,
    0.4857142857142857,
    0.34285714285714286,
    -0.08571428571428572,
)
_PROCESSED_DELIVERY_REVISION = "AUTOMATIC_DATA_ONLY_REFRESH_1"
_PROCESSED_BASELINE_PROOF = {
    "stable_source_hour_inclusive": "2026-09-24 10:00:00",
    "hourly_prefix_count": 12660,
    "hourly_prefix_sha256": "bc80eddad6967ceb1d39a656643e11f669615534316cff78bf4f7a0e5d8111c5",
    "global_hourly_prefix_count": 12660,
    "global_hourly_prefix_without_sg5_sha256": "8bceb0af310be53c210f9f6c515128692b8c07d2fbca317648d862de627e13c8",
    "global_hourly_stable_sg5_source_hour_inclusive": "2026-09-24 08:00:00",
    "global_hourly_stable_sg5_prefix_count": 12658,
    "global_hourly_stable_sg5_prefix_sha256": "5902fba951d7628a3584312bb07edfeff0f7e0c307d9806321c610aefdcc843f",
    "daily_prefix_count": 563,
    "daily_prefix_sha256": "4d8d82023f083be18cbd33290e4f37a1f78cfc0a48c77efaab433e51888323ee",
    "global_daily_prefix_count": 563,
    "global_daily_prefix_sha256": "58d8c9a32a94765377236da2abe35ba6688ed931f6c3a8dc0ca7ca3d260f3b9a",
}
_PROCESSED_STATIC_PAYLOAD_HASHES = {
    "events": "596e0a450dd904dc3861d91e434ef29e2effa53d6655584ed454a41401d35f78",
    "offsets": "78084947927984cffa37b1a078e473b48e9657ef16326e0d18c080235b0cfcae",
    "origin_starts": "4fd1c462fff370ac9b77a353bc5c814c040d9d42ad4bbc567e520527ca91e2a6",
    "resumptions": "411af934ca59a02a22b44295d61538403e7c81143058f1ac02a73ad453047b74",
    "thermal": "131dcae5418c151be091295f9db0a6b5ff7f83158ad41f724ed9dcb88b80ef6b",
}
_PROCESSED_FROZEN_ORIGIN_STRUCTURE_SHA256 = (
    "d41da01c6de787062652fe627328e338e6be747a1f5f956f99b270fb5dc1a7f4"
)
_PROCESSED_APPEND_ORIGIN_STATIC_SHA256 = (
    "b7e18748b529ae935a5a129c370dce914daf0031be0837483451cdbe0557dde8"
)
_PROCESSED_STATIC_METADATA_SHA256 = (
    "dd1a386a5f0436c4f9966e1a2709e884642069a483d3321dfea89ebf0ec565fd"
)
_PROCESSED_STATIC_THERMAL_EXTENSION_SHA256 = (
    "c28a00e0700fa979390e49d783027aafc8376ee05408483240d6fba9b4bca771"
)
_PROCESSED_STATIC_REVIEW_SHA256 = (
    "9f37256a08a0ea3c8b7c45898fa523db6c37625b2e2267e07efd9a6e4269051f"
)
_PROCESSED_REPLACEMENT_KEYS = frozenset(
    {
        "daily",
        "global_daily",
        "global_hourly",
        "hourly",
        "metadata",
        "origins",
        "thermal_coverage",
        "thermal_extended",
    }
)
_PROCESSED_PAYLOAD_KEYS = frozenset(
    {
        "daily",
        "events",
        "global_daily",
        "global_hourly",
        "hourly",
        "metadata",
        "offsets",
        "origin_starts",
        "origins",
        "resumptions",
        "thermal",
        "thermal_coverage",
        "thermal_extended",
    }
)
_PROCESSED_ROW_WIDTHS = {
    "daily": 9,
    "events": 13,
    "global_daily": 11,
    "global_hourly": 12,
    "hourly": 12,
    "offsets": 22,
    "origin_starts": 5,
    "resumptions": 9,
    "thermal": 21,
    "thermal_extended": 29,
}
_PROCESSED_METADATA_KEYS = frozenset(
    {
        "conditional_uncertainty_scope",
        "conversion_factor_mm_per_inch",
        "counts",
        "coverage_end",
        "coverage_start",
        "default_origin_id",
        "default_origin_policy",
        "delivery_revision",
        "delivery_version",
        "full_y_range_mm",
        "global_reference_temperature_c",
        "graphical_alignment_repair",
        "minimum_cycle_count_for_thermal_application",
        "offsets",
        "robust_outside_hourly_point_count",
        "robust_y_range_mm",
        "status",
        "thermal_coefficient_mm_per_c",
        "thermal_extension",
        "thermal_windows",
        "title",
    }
)
_PROCESSED_DYNAMIC_METADATA_KEYS = frozenset(
    {
        "counts",
        "coverage_end",
        "delivery_revision",
        "full_y_range_mm",
        "robust_outside_hourly_point_count",
        "robust_y_range_mm",
        "thermal_extension",
    }
)
_PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS = frozenset(
    {
        "coverage_totals",
        "historical_global_component_equivalence_max_abs_error_mm",
        "row_count",
        "sg5_identity_max_abs_error_mm",
    }
)
_PROCESSED_REVIEW_UPDATE_KEYS = frozenset(
    {
        "lastPairedTemperatureC",
        "lastPairedTemperatureSourceHour",
        "monthlyThermalAdjustments",
        "sensor_snapshot_sha256",
        "trailingReasons",
        "trailingUnpairedHourCount",
    }
)
_PROCESSED_REVIEW_KEYS = frozenset(
    {
        "episodes",
        "lastPairedTemperatureC",
        "lastPairedTemperatureSourceHour",
        "missingRuns",
        "monthlyThermalAdjustments",
        "no_model_refit",
        "raw_quality_inventory_reused",
        "raw_reanalysed_in_this_edit",
        "segmentation",
        "sensor_snapshot_sha256",
        "smoothingRemovedFromControls",
        "source_audit_sha256",
        "source_html_sha256",
        "trailingReasons",
        "trailingUnpairedHourCount",
        "unchanged_payload_keys",
    }
)
_PROCESSED_ORIGIN_KEYS = frozenset(
    {"center_mm", "end", "id", "n", "start", "thermal", "thermal_available"}
)
_PROCESSED_THERMAL_COVERAGE_KEYS = frozenset(
    {
        "analysis_origin_regime_id",
        "clock_ambiguous_hour_count",
        "exploitable_hour_count",
        "extended_hour_count",
        "historical_hour_count",
        "low_cycle_hour_count",
        "measured_hour_count",
        "no_temperature_hour_count",
        "normalized_hour_count",
        "out_of_domain_hour_count",
        "temperature_max_c",
        "temperature_min_c",
    }
)
_DOCUMENTED_THERMAL_ORIGINS = {
    5: (1.5, 29.5, 12.6, "2025-05-25 13:00:00"),
    9: (8.0, 31.6, 18.0, "2025-09-15 10:00:00"),
    30: (-4.5, 15.0, 8.5, "2026-01-09 12:00:00"),
    32: (-1.4, 16.2, 8.3, "2026-03-08 12:00:00"),
    34: (0.1, 40.1, 15.1, "2026-07-21 08:00:00"),
}


@dataclass(frozen=True)
class ReadyFile:
    role: str
    payload: bytes


@dataclass(frozen=True)
class ReadyInventory:
    release_id: str
    files: Mapping[str, ReadyFile]


class RefreshError(RuntimeError):
    """A stable, fail-closed refresh rejection."""


def _one(match: re.Pattern[bytes], payload: bytes, code: str) -> re.Match[bytes]:
    matches = list(match.finditer(payload))
    if len(matches) != 1:
        raise RefreshError(code)
    return matches[0]


def _replace_span(payload: bytes, match: re.Match[bytes], replacement: bytes) -> bytes:
    return payload[:match.start(2)] + replacement + payload[match.end(2):]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _html_safe_json(value: object) -> bytes:
    """Serialize JSON embedded in HTML without emitting HTML parser sentinels."""
    return (
        _canonical_json(value)
        .replace(b"&", b"\\u0026")
        .replace(b"<", b"\\u003c")
        .replace(b">", b"\\u003e")
        .replace("\u2028".encode(), b"\\u2028")
        .replace("\u2029".encode(), b"\\u2029")
    )


def _value_sha256(value: object) -> str:
    """Hash one canonical JSON value using the producer's newline convention."""
    return hashlib.sha256(_canonical_json(value) + b"\n").hexdigest()


def _same_number(left: object, right: object, *, tolerance: float = 1e-9) -> bool:
    return _number(left) and _number(right) and math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=tolerance
    )


def _literal_hour_milliseconds(value: object, code: str) -> int:
    parsed = _source_hour(value, code)
    return int((parsed - datetime(1970, 1, 1)).total_seconds() * 1000)


def _paris_aligned_hour(value: object, code: str) -> tuple[int, str] | None:
    """Reproduce pandas ambiguous/nonexistent rejection without a fixed UTC shift."""
    local = _source_hour(value, code)
    candidates: dict[int, datetime] = {}
    for fold in (0, 1):
        aware = local.replace(tzinfo=_PARIS, fold=fold)
        utc = aware.astimezone(_UTC)
        if utc.astimezone(_PARIS).replace(tzinfo=None) == local:
            milliseconds = int(
                (utc.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds()
                * 1000
            )
            candidates[milliseconds] = utc
    if len(candidates) != 1:
        return None
    milliseconds, utc = next(iter(candidates.items()))
    return milliseconds, utc.strftime("%Y-%m-%d %H:%M:%S")


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise RefreshError("REFRESH_PROCESSED_SCHEMA_DIVERGED")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict_json(payload: bytes, code: str) -> object:
    try:
        return json.loads(payload, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RefreshError(code) from error


def _verified_ready_files(root: Path) -> ReadyInventory:
    """Read one immutable candidate only after its closed manifest is verified."""
    if root.is_symlink():
        raise RefreshError("REFRESH_READY_ROOT_INVALID")
    root = root.resolve(strict=True)
    if HASH.fullmatch(root.name) is None or not root.is_dir():
        raise RefreshError("REFRESH_READY_ROOT_INVALID")
    ready = root / READY
    manifest_path = root / CONTENT_MANIFEST
    if (
        ready.is_symlink()
        or not ready.is_file()
        or ready.read_bytes() != READY_CONTENT
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        raise RefreshError("REFRESH_READY_MARKER_MISSING")
    manifest = _strict_json(
        manifest_path.read_bytes(), "REFRESH_READY_MANIFEST_INVALID"
    )
    records = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(records, list):
        raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
    release_id = manifest.get("release_id")
    if release_id is not None and release_id != root.name:
        raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
    files: dict[str, ReadyFile] = {}
    expected = {READY, CONTENT_MANIFEST}
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "path", "role", "sha256", "size_bytes"
        }:
            raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
        relative = record["path"]
        if not isinstance(relative, str):
            raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative
            or any(part in {"", ".", ".."} for part in pure.parts)
            or relative in expected
        ):
            raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
        path = root.joinpath(*pure.parts)
        if path.is_symlink() or not path.is_file():
            raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
        content = path.read_bytes()
        role = record["role"]
        if (
            type(record["size_bytes"]) is not int
            or record["size_bytes"] != len(content)
            or not isinstance(role, str)
            or not role
            or not isinstance(record["sha256"], str)
            or HASH.fullmatch(record["sha256"]) is None
            or hashlib.sha256(content).hexdigest() != record["sha256"]
        ):
            raise RefreshError("REFRESH_READY_MANIFEST_DIVERGED")
        expected.add(relative)
        files[relative] = ReadyFile(role=role, payload=content)
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed != expected:
        raise RefreshError("REFRESH_READY_INVENTORY_DIVERGED")
    if PROCESSED_PATCH in files:
        patch = files[PROCESSED_PATCH]
        if (
            set(files) != {PROCESSED_PATCH}
            or patch.role != PROCESSED_PATCH_ROLE
            or release_id != root.name
            or hashlib.sha256(patch.payload).hexdigest() != root.name
        ):
            raise RefreshError("REFRESH_PROCESSED_READY_INVALID")
    return ReadyInventory(release_id=root.name, files=files)


def _verified_ready_inventory(root: Path) -> dict[str, bytes]:
    """Compatibility view exposing only HTML candidates from one ready release."""
    inventory = _verified_ready_files(root)
    return {
        relative: entry.payload
        for relative, entry in inventory.files.items()
        if PurePosixPath(relative).suffix.lower() in {".html", ".htm"}
    }


def _expect_object(value: object, keys: frozenset[str] | set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RefreshError(code)
    return value


def _hash_value(value: object, code: str) -> str:
    if not isinstance(value, str) or HASH.fullmatch(value) is None:
        raise RefreshError(code)
    return value


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _validate_json_tree(value: object, code: str) -> None:
    if value is None or isinstance(value, bool):
        return
    if _number(value):
        return
    if isinstance(value, str):
        if "</script" in value.lower():
            raise RefreshError(code)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_tree(item, code)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) or "</script" in key.lower() for key in value):
            raise RefreshError(code)
        for item in value.values():
            _validate_json_tree(item, code)
        return
    raise RefreshError(code)


def _source_hour(value: object, code: str) -> datetime:
    if not isinstance(value, str) or _SOURCE_HOUR.fullmatch(value) is None:
        raise RefreshError(code)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise RefreshError(code) from None


def _rows(value: object, width: int, code: str) -> list[list[object]]:
    if not isinstance(value, list) or any(
        not isinstance(row, list) or len(row) != width for row in value
    ):
        raise RefreshError(code)
    return value


def _validate_hourly_tables(payload: Mapping[str, object]) -> None:
    code = "REFRESH_PROCESSED_SERIES_DIVERGED"
    hourly = payload["hourly"]
    global_hourly = payload["global_hourly"]
    if not isinstance(hourly, list) or not isinstance(global_hourly, list) or len(hourly) != len(global_hourly):
        raise RefreshError(code)
    origin_centers = [origin["center_mm"] for origin in payload["origins"]]
    origin_offsets = [0.0] + [row[10] for row in payload["offsets"]]
    previous_time: int | None = None
    for row, global_row in zip(hourly, global_hourly, strict=True):
        if (
            type(row[0]) is not int
            or row[0] != _literal_hour_milliseconds(row[1], code)
            or type(row[2]) is not int
            or not 0 <= row[2] < 37
            or not all(_number(row[position]) for position in (3, 4, 5, 6))
            or not _same_number(row[3], origin_centers[row[2]])
            or type(row[7]) is not int
            or row[7] < 1
            or type(row[8]) is not int
            or row[8] < 1
            or type(row[9]) is not int
            or type(row[10]) is not int
            or row[9] < 1
            or row[10] < row[9]
            or row[11]
            != ("EFFECTIF_HORAIRE_INFÉRIEUR_À_20_CYCLES" if row[7] < 20 else "")
            or not _same_number(row[5], row[4] * 25.4)
            or not _same_number(row[6], row[5] - row[3])
        ):
            raise RefreshError(code)
        if previous_time is not None and row[0] < previous_time:
            raise RefreshError(code)
        previous_time = row[0]
        if (
            global_row[:3] != row[:3]
            or not _same_number(global_row[3], row[5])
            or not _same_number(global_row[4], origin_offsets[row[2]])
            or not _same_number(global_row[5], global_row[3] + global_row[4])
            or global_row[8] != row[7]
            or global_row[9] != row[11]
            or global_row[10:] != row[9:11]
            or global_row[7]
            not in {"AVAILABLE", "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"}
            or (global_row[7] == "AVAILABLE") != _number(global_row[6])
            or (
                global_row[7] == "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"
                and global_row[6] is not None
            )
        ):
            raise RefreshError(code)
    for index in range(2, len(global_hourly) - 2):
        window = global_hourly[index - 2 : index + 3]
        available = (
            len({row[2] for row in window}) == 1
            and all(
                right[0] - left[0] == _HOUR_MILLISECONDS
                for left, right in zip(window, window[1:])
            )
        )
        row = global_hourly[index]
        if available:
            expected = sum(weight * item[5] for weight, item in zip(_SG5_WEIGHTS, window, strict=True))
            if row[7] != "AVAILABLE" or not _same_number(row[6], expected, tolerance=1e-8):
                raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")
        elif row[6] is not None or row[7] != "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT":
            raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")


def _daily_groups(payload: Mapping[str, object]) -> list[tuple[tuple[int, str], list[int]]]:
    groups: dict[tuple[int, str], list[int]] = {}
    for index, row in enumerate(payload["hourly"]):
        key = (row[2], row[1][:10])
        groups.setdefault(key, []).append(index)
    return list(groups.items())


def _validate_daily_tables(payload: Mapping[str, object]) -> None:
    code = "REFRESH_PROCESSED_DAILY_DIVERGED"
    daily = payload["daily"]
    global_daily = payload["global_daily"]
    groups = _daily_groups(payload)
    if len(daily) != len(groups) or len(global_daily) != len(groups):
        raise RefreshError(code)
    hourly = payload["hourly"]
    global_hourly = payload["global_hourly"]
    for daily_row, global_row, ((origin, date), indexes) in zip(
        daily, global_daily, groups, strict=True
    ):
        rows = [hourly[index] for index in indexes]
        global_rows = [global_hourly[index] for index in indexes]
        centered = [float(row[6]) for row in rows]
        time_coordinate = round(median([row[0] for row in rows]))
        count = len(rows)
        expected = (
            time_coordinate,
            date,
            origin,
            count,
            median(centered),
            _quantile(centered, 0.25),
            _quantile(centered, 0.75),
            count < 20,
            rows[0][3],
        )
        if (
            not isinstance(date, str)
            or _SOURCE_DATE.fullmatch(date) is None
            or daily_row[:4] != list(expected[:4])
            or daily_row[7:] != list(expected[7:])
            or any(
                not _same_number(daily_row[position], expected[position])
                for position in (4, 5, 6)
            )
        ):
            raise RefreshError(code)
        offset = global_rows[0][4]
        global_expected = (
            time_coordinate,
            date,
            origin,
            count,
            expected[4] + expected[8],
            expected[5] + expected[8],
            expected[6] + expected[8],
            expected[4] + expected[8] + offset,
            expected[5] + expected[8] + offset,
            expected[6] + expected[8] + offset,
            count < 20,
        )
        if (
            global_row[:4] != list(global_expected[:4])
            or global_row[10] != global_expected[10]
            or any(
                not _same_number(global_row[position], global_expected[position])
                for position in range(4, 10)
            )
        ):
            raise RefreshError(code)


def _thermal_expected_classification(
    row: list[object], historical_row: list[object] | None
) -> tuple[object, ...]:
    code = "REFRESH_PROCESSED_THERMAL_TRANSITION_INVALID"
    origin = row[4]
    aligned = _paris_aligned_hour(row[1], code)
    documented = _DOCUMENTED_THERMAL_ORIGINS.get(origin)
    if documented is None:
        domain_min, domain_max = -4.5, 40.1
        domain_source = "GLOBAL_HISTORICAL_ENVELOPE_UNION"
    else:
        domain_min, domain_max, _, _ = documented
        domain_source = "ORIGIN_FINAL_FIT_RANGE_PRESERVED"
    if aligned is None:
        exploitable = False
        within = False
        reason = "CLOCK_AMBIGUOUS_OR_NONEXISTENT"
    elif row[26] < 20:
        exploitable = False
        within = False
        reason = "LOW_CYCLE_SUPPORT"
    elif row[8] is None:
        exploitable = False
        within = False
        reason = "NO_EXACT_OUTDOOR_TEMPERATURE"
    else:
        if not _number(row[8]):
            raise RefreshError(code)
        exploitable = True
        within = domain_min <= row[8] <= domain_max
        reason = "" if within else "OUTSIDE_DOCUMENTED_TEMPERATURE_DOMAIN"
    historical = bool(exploitable and historical_row is not None)
    historical_reference = historical_row[16] if historical_row is not None else None
    application = (
        "NOT_APPLIED"
        if not exploitable
        else (
            "HISTORICAL_REVISION_PRESERVED"
            if historical
            else "EXTENDED_FROZEN_MODEL_EXPLORATORY"
        )
    )
    return (
        aligned,
        domain_source,
        domain_min,
        domain_max,
        exploitable,
        within,
        application,
        reason,
        historical,
        historical_reference,
    )


def _validate_thermal_rows(payload: Mapping[str, object]) -> None:
    code = "REFRESH_PROCESSED_THERMAL_TRANSITION_INVALID"
    thermal = payload["thermal_extended"]
    hourly = payload["hourly"]
    global_hourly = payload["global_hourly"]
    historical_rows = {
        (row[1], row[4], row[18], row[19]): row for row in payload["thermal"]
    }
    if len(historical_rows) != len(payload["thermal"]):
        raise RefreshError("REFRESH_PROCESSED_STATIC_PAYLOAD_DIVERGED")
    observed_historical: set[tuple[object, ...]] = set()
    if len(thermal) != len(hourly):
        raise RefreshError(code)
    for row, hourly_row, global_row in zip(thermal, hourly, global_hourly, strict=True):
        if (
            row[0:2] != hourly_row[0:2]
            or row[4] != hourly_row[2]
            or not _same_number(row[5], hourly_row[5])
            or not _same_number(row[6], global_row[4])
            or not _same_number(row[7], global_row[5])
            or row[26] != hourly_row[7]
            or row[27:29] != hourly_row[9:11]
        ):
            raise RefreshError("REFRESH_PROCESSED_SERIES_DIVERGED")
        historical_key = (row[1], row[4], row[27], row[28])
        (
            aligned,
            domain_source,
            domain_min,
            domain_max,
            exploitable,
            within,
            application,
            reason,
            historical,
            historical_reference,
        ) = _thermal_expected_classification(row, historical_rows.get(historical_key))
        if (
            (aligned is None and (row[2] is not None or row[3] is not None))
            or (aligned is not None and [row[2], row[3]] != list(aligned))
            or row[11] is not within
            or row[12] is not within
            or row[13] != application
            or row[14] != reason
            or row[15] != domain_source
            or not _same_number(row[16], domain_min)
            or not _same_number(row[17], domain_max)
            or row[18] is not historical
        ):
            raise RefreshError(code)
        if exploitable:
            component = -0.09994542923746184 * (row[8] - 15.1)
            if (
                not _same_number(row[9], component, tolerance=1e-11)
                or not _same_number(row[10], row[7] - component, tolerance=1e-11)
            ):
                raise RefreshError(code)
        elif row[9] is not None or row[10] is not None:
            raise RefreshError(code)
        if historical:
            observed_historical.add(historical_key)
            historical_component = -0.09994542923746184 * (
                row[8] - historical_reference
            )
            frozen = historical_rows[historical_key]
            if (
                not _same_number(row[8], frozen[15])
                or not _same_number(row[19], historical_reference)
                or not _same_number(row[20], historical_component, tolerance=1e-11)
                or not _same_number(row[21], row[5] - historical_component, tolerance=1e-11)
                or not _same_number(row[20], frozen[12], tolerance=1e-11)
                or not _same_number(row[21], frozen[8], tolerance=1e-11)
            ):
                raise RefreshError(code)
        elif any(row[position] is not None for position in (19, 20, 21)):
            raise RefreshError(code)
        if row[25] == "AVAILABLE":
            if (
                not all(_number(row[position]) for position in (22, 23, 24))
                or global_row[7] != "AVAILABLE"
                or not _same_number(row[22], global_row[6], tolerance=1e-8)
                or not _same_number(row[24], row[22] - row[23], tolerance=1e-8)
            ):
                raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")
        elif (
            row[25] != "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT"
            or any(row[position] is not None for position in (22, 23, 24))
        ):
            raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")
    for index in range(2, len(thermal) - 2):
        window = thermal[index - 2 : index + 3]
        available = (
            all(item[12] is True for item in window)
            and len({item[4] for item in window}) == 1
            and all(
                right[0] - left[0] == _HOUR_MILLISECONDS
                for left, right in zip(window, window[1:])
            )
        )
        row = thermal[index]
        if available:
            expected = [
                sum(weight * item[position] for weight, item in zip(_SG5_WEIGHTS, window, strict=True))
                for position in (7, 9, 10)
            ]
            if row[25] != "AVAILABLE" or any(
                not _same_number(row[position], value, tolerance=1e-8)
                for position, value in zip((22, 23, 24), expected, strict=True)
            ):
                raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")
        elif row[25] != "UNAVAILABLE_INCOMPLETE_5_POINT_SUPPORT":
            raise RefreshError("REFRESH_PROCESSED_SG5_DIVERGED")
    if observed_historical != set(historical_rows):
        raise RefreshError("REFRESH_PROCESSED_STATIC_PAYLOAD_DIVERGED")


def _derived_thermal_coverage(payload: Mapping[str, object]) -> list[dict[str, object]]:
    rows_by_origin: list[list[list[object]]] = [[] for _ in range(37)]
    for row in payload["thermal_extended"]:
        rows_by_origin[row[4]].append(row)
    derived: list[dict[str, object]] = []
    for origin, rows in enumerate(rows_by_origin):
        exploitable = [row for row in rows if row[13] != "NOT_APPLIED"]
        temperatures = [row[8] for row in exploitable]
        derived.append(
            {
                "analysis_origin_regime_id": origin,
                "clock_ambiguous_hour_count": sum(
                    row[14] == "CLOCK_AMBIGUOUS_OR_NONEXISTENT" for row in rows
                ),
                "exploitable_hour_count": len(exploitable),
                "extended_hour_count": sum(
                    row[13] == "EXTENDED_FROZEN_MODEL_EXPLORATORY" for row in rows
                ),
                "historical_hour_count": sum(row[18] is True for row in rows),
                "low_cycle_hour_count": sum(row[14] == "LOW_CYCLE_SUPPORT" for row in rows),
                "measured_hour_count": len(rows),
                "no_temperature_hour_count": sum(
                    row[14] == "NO_EXACT_OUTDOOR_TEMPERATURE" for row in rows
                ),
                "normalized_hour_count": sum(row[12] is True for row in rows),
                "out_of_domain_hour_count": sum(
                    row[14] == "OUTSIDE_DOCUMENTED_TEMPERATURE_DOMAIN" for row in rows
                ),
                "temperature_max_c": max(temperatures) if temperatures else None,
                "temperature_min_c": min(temperatures) if temperatures else None,
            }
        )
    return derived


def _validate_processed_payload(value: object) -> dict[str, object]:
    code = "REFRESH_PROCESSED_SCHEMA_DIVERGED"
    payload = _expect_object(value, _PROCESSED_PAYLOAD_KEYS, code)
    _validate_json_tree(payload, code)
    for name, width in _PROCESSED_ROW_WIDTHS.items():
        _rows(payload[name], width, code)
    for name, expected_hash in _PROCESSED_STATIC_PAYLOAD_HASHES.items():
        if _value_sha256(payload[name]) != expected_hash:
            raise RefreshError("REFRESH_PROCESSED_STATIC_PAYLOAD_DIVERGED")
    origins = payload["origins"]
    if (
        not isinstance(origins, list)
        or len(origins) != 37
        or any(
            not isinstance(origin, dict)
            or set(origin) != _PROCESSED_ORIGIN_KEYS
            or origin.get("id") != index
            or not isinstance(origin.get("thermal"), dict)
            for index, origin in enumerate(origins)
        )
    ):
        raise RefreshError(code)
    if (
        _value_sha256(
            [
                {
                    name: origin[name]
                    for name in ("id", "n", "start", "end", "center_mm")
                }
                for origin in origins[:36]
            ]
        )
        != _PROCESSED_FROZEN_ORIGIN_STRUCTURE_SHA256
        or _value_sha256(
            [origins[36][name] for name in ("id", "start", "center_mm")]
        )
        != _PROCESSED_APPEND_ORIGIN_STATIC_SHA256
    ):
        raise RefreshError("REFRESH_PROCESSED_ORIGIN_DIVERGED")
    coverage = payload["thermal_coverage"]
    if (
        not isinstance(coverage, list)
        or len(coverage) != 37
        or any(
            not isinstance(row, dict)
            or set(row) != _PROCESSED_THERMAL_COVERAGE_KEYS
            or row.get("analysis_origin_regime_id") != index
            for index, row in enumerate(coverage)
        )
    ):
        raise RefreshError(code)
    metadata = _expect_object(payload["metadata"], _PROCESSED_METADATA_KEYS, code)
    static_metadata = {
        name: metadata[name]
        for name in _PROCESSED_METADATA_KEYS - _PROCESSED_DYNAMIC_METADATA_KEYS
    }
    if _value_sha256(static_metadata) != _PROCESSED_STATIC_METADATA_SHA256:
        raise RefreshError("REFRESH_PROCESSED_MODEL_DIVERGED")
    counts_keys = {
        "daily", "events", "hourly", "low_cycle_hours", "origin_starts",
        "origins", "partial_days", "resumptions", "thermal",
        "thermal_in_domain", "thermal_origins", "thermal_out_of_domain",
    }
    counts = _expect_object(metadata["counts"], counts_keys, code)
    if any(type(item) is not int or item < 0 for item in counts.values()):
        raise RefreshError(code)
    expected_counts = {
        "daily": len(payload["daily"]),
        "events": len(payload["events"]),
        "hourly": len(payload["hourly"]),
        "origin_starts": len(payload["origin_starts"]),
        "origins": len(origins),
        "resumptions": len(payload["resumptions"]),
        "thermal": len(payload["thermal"]),
        "partial_days": sum(row[7] is True for row in payload["daily"]),
        "low_cycle_hours": sum(row[7] < 20 for row in payload["hourly"]),
        "thermal_in_domain": sum(row[17] is True for row in payload["thermal"]),
        "thermal_out_of_domain": sum(row[17] is False for row in payload["thermal"]),
        "thermal_origins": len({row[4] for row in payload["thermal"]}),
    }
    if any(counts[name] != expected for name, expected in expected_counts.items()):
        raise RefreshError(code)
    if len(payload["offsets"]) != 36 or len(payload["origin_starts"]) != 36:
        raise RefreshError(code)
    if (
        metadata["thermal_coefficient_mm_per_c"] != -0.09994542923746184
        or metadata["global_reference_temperature_c"] != 15.1
        or metadata["conversion_factor_mm_per_inch"] != 25.4
        or metadata["delivery_version"] != 2
        or metadata["default_origin_id"] != "all"
    ):
        raise RefreshError("REFRESH_PROCESSED_MODEL_DIVERGED")
    coverage_start = _source_hour(metadata["coverage_start"], code)
    coverage_end = _source_hour(metadata["coverage_end"], code)
    if coverage_end < coverage_start:
        raise RefreshError(code)
    for name in ("full_y_range_mm", "robust_y_range_mm"):
        item = metadata[name]
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(_number(number) for number in item)
            or item[0] > item[1]
        ):
            raise RefreshError(code)
    extension_keys = {
        "coverage_totals", "diagnostics", "global_historical_envelope_c",
        "global_reference_temperature_c",
        "historical_global_component_equivalence_max_abs_error_mm", "row_count",
        "sequence_7_exclusion", "sg5_identity_max_abs_error_mm",
    }
    extension = _expect_object(metadata["thermal_extension"], extension_keys, code)
    static_extension = {
        name: extension[name]
        for name in extension_keys - _PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS
    }
    if (
        _value_sha256(static_extension) != _PROCESSED_STATIC_THERMAL_EXTENSION_SHA256
        or extension["global_reference_temperature_c"] != 15.1
        or type(extension["row_count"]) is not int
        or extension["row_count"] != len(payload["thermal_extended"])
        or len(payload["hourly"]) != len(payload["global_hourly"])
        or len(payload["hourly"]) != len(payload["thermal_extended"])
    ):
        raise RefreshError(code)
    if (
        not isinstance(metadata["robust_outside_hourly_point_count"], int)
        or metadata["robust_outside_hourly_point_count"] < 0
        or metadata["full_y_range_mm"][0] > metadata["robust_y_range_mm"][0]
        or metadata["robust_y_range_mm"][1] > metadata["full_y_range_mm"][1]
        or not all(
            _number(extension[name]) and extension[name] >= 0
            for name in (
                "historical_global_component_equivalence_max_abs_error_mm",
                "sg5_identity_max_abs_error_mm",
            )
        )
    ):
        raise RefreshError(code)
    _validate_hourly_tables(payload)
    _validate_daily_tables(payload)
    _validate_thermal_rows(payload)
    derived_coverage = _derived_thermal_coverage(payload)
    if coverage != derived_coverage:
        raise RefreshError("REFRESH_PROCESSED_THERMAL_COVERAGE_DIVERGED")
    coverage_totals = {
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
    if extension["coverage_totals"] != coverage_totals:
        raise RefreshError("REFRESH_PROCESSED_THERMAL_COVERAGE_DIVERGED")
    rows_by_origin: list[list[list[object]]] = [[] for _ in range(37)]
    for row in payload["hourly"]:
        rows_by_origin[row[2]].append(row)
    for index, (origin, origin_rows, coverage_row) in enumerate(
        zip(origins, rows_by_origin, coverage, strict=True)
    ):
        thermal_projection = {
            name: coverage_row[name]
            for name in _PROCESSED_THERMAL_COVERAGE_KEYS
            if name != "analysis_origin_regime_id"
        }
        if (
            not origin_rows
            or origin["id"] != index
            or origin["n"] != len(origin_rows)
            or origin["start"] != origin_rows[0][1]
            or origin["end"] != origin_rows[-1][1]
            or not _same_number(origin["center_mm"], origin_rows[0][3])
            or origin["thermal"] != thermal_projection
            or origin["thermal_available"]
            is not (coverage_row["normalized_hour_count"] > 0)
        ):
            raise RefreshError("REFRESH_PROCESSED_ORIGIN_DIVERGED")
    centered = [row[6] for row in payload["hourly"]]
    full_range = metadata["full_y_range_mm"]
    robust_range = metadata["robust_y_range_mm"]
    if (
        not _same_number(full_range[0], min(centered))
        or not _same_number(full_range[1], max(centered))
        or metadata["robust_outside_hourly_point_count"]
        != sum(value < robust_range[0] or value > robust_range[1] for value in centered)
        or metadata["coverage_start"] != payload["hourly"][0][1]
        or metadata["coverage_end"] != payload["hourly"][-1][1]
    ):
        raise RefreshError("REFRESH_PROCESSED_METADATA_DIVERGED")
    return payload


def _validate_processed_review(value: object) -> dict[str, object]:
    code = "REFRESH_PROCESSED_REVIEW_SCHEMA_DIVERGED"
    review = _expect_object(value, _PROCESSED_REVIEW_KEYS, code)
    _validate_json_tree(review, code)
    static_review = {
        name: review[name]
        for name in _PROCESSED_REVIEW_KEYS - _PROCESSED_REVIEW_UPDATE_KEYS
    }
    if _value_sha256(static_review) != _PROCESSED_STATIC_REVIEW_SHA256:
        raise RefreshError("REFRESH_PROCESSED_REVIEW_STATIC_DIVERGED")
    for name in ("source_html_sha256", "source_audit_sha256", "sensor_snapshot_sha256"):
        _hash_value(review[name], code)
    if (
        review["no_model_refit"] is not True
        or review["smoothingRemovedFromControls"] is not True
        or set(review["unchanged_payload_keys"])
        != _PROCESSED_PAYLOAD_KEYS
        or not isinstance(review["episodes"], list)
        or not isinstance(review["missingRuns"], list)
        or not isinstance(review["segmentation"], dict)
    ):
        raise RefreshError(code)
    _validate_review_update(
        {name: review[name] for name in _PROCESSED_REVIEW_UPDATE_KEYS},
        expected_snapshot=review["sensor_snapshot_sha256"],
    )
    return review


def _processed_document(
    document: bytes,
) -> tuple[re.Match[bytes], dict[str, object], re.Match[bytes], dict[str, object]]:
    if (
        not isinstance(document, bytes)
        or not document.lower().startswith(b"<!doctype html>")
        or len(document) > MAX_PROCESSED_MASTER_BYTES
    ):
        raise RefreshError("REFRESH_PROCESSED_HTML_INVALID")
    payload_match = _one(
        _PROCESSED_PAYLOAD, document, "REFRESH_PROCESSED_PAYLOAD_BLOCK_UNEXPECTED"
    )
    review_match = _one(
        _REVIEW_DIAGNOSTICS, document, "REFRESH_PROCESSED_REVIEW_BLOCK_UNEXPECTED"
    )
    if payload_match.start() >= review_match.start():
        raise RefreshError("REFRESH_PROCESSED_HTML_INVALID")
    payload = _validate_processed_payload(
        _strict_json(payload_match.group(2), "REFRESH_PROCESSED_PAYLOAD_INVALID")
    )
    review = _validate_processed_review(
        _strict_json(review_match.group(2), "REFRESH_PROCESSED_REVIEW_INVALID")
    )
    return payload_match, payload, review_match, review


def processed_data_only_skeleton(document: bytes) -> bytes:
    payload_match, _, review_match, _ = _processed_document(document)
    result = _replace_span(document, review_match, b"__REVIEW_DIAGNOSTICS__")
    return _replace_span(result, payload_match, b"__PROCESSED_SIGNAL_PAYLOAD__")


def processed_template_sha256(document: bytes) -> str:
    return hashlib.sha256(processed_data_only_skeleton(document)).hexdigest()


def _validate_review_update(
    value: object, *, expected_snapshot: str
) -> dict[str, object]:
    code = "REFRESH_PROCESSED_REVIEW_UPDATE_INVALID"
    update = _expect_object(value, _PROCESSED_REVIEW_UPDATE_KEYS, code)
    _validate_json_tree(update, code)
    if update["sensor_snapshot_sha256"] != expected_snapshot:
        raise RefreshError(code)
    paired = update["lastPairedTemperatureSourceHour"]
    if paired is not None:
        _source_hour(paired, code)
    temperature = update["lastPairedTemperatureC"]
    if temperature is not None and not _number(temperature):
        raise RefreshError(code)
    trailing = update["trailingUnpairedHourCount"]
    reasons = update["trailingReasons"]
    if (
        type(trailing) is not int
        or trailing < 0
        or not isinstance(reasons, dict)
        or any(
            not isinstance(reason, str)
            or not reason
            or type(count) is not int
            or count < 0
            for reason, count in reasons.items()
        )
        or sum(reasons.values()) != trailing
    ):
        raise RefreshError(code)
    monthly = update["monthlyThermalAdjustments"]
    if not isinstance(monthly, list):
        raise RefreshError(code)
    observed_months: list[str] = []
    for record in monthly:
        item = _expect_object(
            record,
            {"medianAdjustment", "medianTemperature", "month", "n"},
            code,
        )
        month = item["month"]
        if (
            not isinstance(month, str)
            or _MONTH.fullmatch(month) is None
            or type(item["n"]) is not int
            or item["n"] < 1
            or not _number(item["medianAdjustment"])
            or not _number(item["medianTemperature"])
        ):
            raise RefreshError(code)
        observed_months.append(month)
    if observed_months != sorted(set(observed_months)):
        raise RefreshError(code)
    return update


def _validate_review_against_payload(
    review: Mapping[str, object], payload: Mapping[str, object]
) -> None:
    code = "REFRESH_PROCESSED_REVIEW_DIVERGED"
    thermal = payload["thermal_extended"]
    paired_indexes = [
        index for index, row in enumerate(thermal) if row[13] != "NOT_APPLIED"
    ]
    if paired_indexes:
        last_index = paired_indexes[-1]
        last = thermal[last_index]
        trailing = thermal[last_index + 1 :]
        expected_hour = last[1]
        expected_temperature = last[8]
    else:
        trailing = thermal
        expected_hour = None
        expected_temperature = None
    reasons: dict[str, int] = {}
    for row in trailing:
        if row[14]:
            reasons[row[14]] = reasons.get(row[14], 0) + 1
    if (
        review["lastPairedTemperatureSourceHour"] != expected_hour
        or not (
            review["lastPairedTemperatureC"] is None
            if expected_temperature is None
            else _same_number(review["lastPairedTemperatureC"], expected_temperature)
        )
        or review["trailingUnpairedHourCount"] != len(trailing)
        or review["trailingReasons"] != reasons
    ):
        raise RefreshError(code)
    monthly: dict[str, list[list[object]]] = {}
    for row in thermal:
        if row[12] is True:
            monthly.setdefault(row[1][:7], []).append(row)
    expected_monthly = []
    for month, rows in monthly.items():
        expected_monthly.append(
            {
                "month": month,
                "n": len(rows),
                "medianTemperature": median([row[8] for row in rows]),
                "medianAdjustment": median([-row[9] for row in rows]),
            }
        )
    observed = review["monthlyThermalAdjustments"]
    if not isinstance(observed, list) or len(observed) != len(expected_monthly):
        raise RefreshError(code)
    for item, expected in zip(observed, expected_monthly, strict=True):
        if (
            item["month"] != expected["month"]
            or item["n"] != expected["n"]
            or not _same_number(
                item["medianTemperature"], expected["medianTemperature"], tolerance=1e-11
            )
            or not _same_number(
                item["medianAdjustment"], expected["medianAdjustment"], tolerance=1e-11
            )
        ):
            raise RefreshError(code)


def _parse_processed_patch(payload: bytes) -> dict[str, object]:
    code = "REFRESH_PROCESSED_PATCH_INVALID"
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_PROCESSED_PATCH_BYTES:
        raise RefreshError(code)
    value = _strict_json(payload, code)
    if _canonical_json(value) + b"\n" != payload:
        raise RefreshError(code)
    patch = _expect_object(
        value,
        {
            "baseline_proof",
            "base_payload_sha256",
            "base_template_sha256",
            "logical_asset_id",
            "protocol_version",
            "replacements",
            "review_diagnostics_update",
            "sensor_source",
            "weather_source",
        },
        code,
    )
    if (
        patch["protocol_version"] != PROCESSED_PROTOCOL_VERSION
        or patch["logical_asset_id"] != PROCESSED_LOGICAL_ASSET_ID
        or patch["base_payload_sha256"] != PROCESSED_BASE_PAYLOAD_SHA256
        or patch["base_template_sha256"] != PROCESSED_BASE_TEMPLATE_SHA256
    ):
        raise RefreshError("REFRESH_PROCESSED_BASE_DIVERGED")
    baseline_proof = _expect_object(
        patch["baseline_proof"], set(_PROCESSED_BASELINE_PROOF), code
    )
    if baseline_proof != _PROCESSED_BASELINE_PROOF:
        raise RefreshError("REFRESH_PROCESSED_BASE_DIVERGED")
    _hash_value(patch["base_payload_sha256"], code)
    _hash_value(patch["base_template_sha256"], code)
    sensor = _expect_object(
        patch["sensor_source"],
        {
            "accepted_size_bytes",
            "classification",
            "closed_source_hour",
            "first_excluded_source_hour",
            "generation_sha256",
            "observed_open_source_hour",
            "parent_generation_sha256",
            "snapshot_line_count",
            "snapshot_sha256",
        },
        code,
    )
    for name in ("generation_sha256", "snapshot_sha256"):
        _hash_value(sensor[name], code)
    classification = sensor["classification"]
    parent = sensor["parent_generation_sha256"]
    if classification not in {"BOOTSTRAP_ACCEPTED", "APPEND_ACCEPTED", "UNCHANGED"}:
        raise RefreshError(code)
    if classification == "BOOTSTRAP_ACCEPTED":
        if parent is not None:
            raise RefreshError(code)
    else:
        _hash_value(parent, code)
    if (
        type(sensor["accepted_size_bytes"]) is not int
        or sensor["accepted_size_bytes"] <= 0
        or type(sensor["snapshot_line_count"]) is not int
        or sensor["snapshot_line_count"] <= 0
    ):
        raise RefreshError(code)
    closed = _source_hour(sensor["closed_source_hour"], code)
    first_excluded = _source_hour(sensor["first_excluded_source_hour"], code)
    observed_open = _source_hour(sensor["observed_open_source_hour"], code)
    if (
        first_excluded != closed + timedelta(hours=1)
        or observed_open != closed + timedelta(hours=3)
    ):
        raise RefreshError(code)
    weather = _expect_object(
        patch["weather_source"],
        {
            "cumulative_analytical_groups",
            "current_manifest_sha256",
            "generation_names",
            "latest_literal_hour",
        },
        code,
    )
    _hash_value(weather["current_manifest_sha256"], code)
    names = weather["generation_names"]
    if (
        not isinstance(names, list)
        or not names
        or any(HASH.fullmatch(name) is None for name in names if isinstance(name, str))
        or any(not isinstance(name, str) for name in names)
        or len(names) != len(set(names))
        or type(weather["cumulative_analytical_groups"]) is not int
        or weather["cumulative_analytical_groups"] <= 0
    ):
        raise RefreshError(code)
    if weather["latest_literal_hour"] is not None:
        _source_hour(weather["latest_literal_hour"], code)
    replacements = _expect_object(
        patch["replacements"], _PROCESSED_REPLACEMENT_KEYS, code
    )
    _validate_json_tree(replacements, code)
    metadata_update = _expect_object(
        replacements["metadata"], _PROCESSED_DYNAMIC_METADATA_KEYS, code
    )
    thermal_extension_update = _expect_object(
        metadata_update["thermal_extension"],
        _PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS,
        code,
    )
    _validate_json_tree(thermal_extension_update, code)
    if metadata_update["delivery_revision"] != _PROCESSED_DELIVERY_REVISION:
        raise RefreshError("REFRESH_PROCESSED_MODEL_DIVERGED")
    _validate_review_update(
        patch["review_diagnostics_update"],
        expected_snapshot=sensor["snapshot_sha256"],
    )
    return patch


def _coverage_progressed(active: Mapping[str, object], candidate: Mapping[str, object]) -> bool:
    if set(active) != set(candidate):
        return False
    count_names = {
        "clock_ambiguous_hour_count",
        "exploitable_hour_count",
        "extended_hour_count",
        "historical_hour_count",
        "low_cycle_hour_count",
        "measured_hour_count",
        "no_temperature_hour_count",
        "normalized_hour_count",
        "out_of_domain_hour_count",
    }
    if any(
        type(candidate.get(name)) is not int or candidate[name] < 0
        for name in count_names
    ):
        return False
    if (
        candidate["normalized_hour_count"]
        + candidate["out_of_domain_hour_count"]
        + candidate["no_temperature_hour_count"]
        + candidate["clock_ambiguous_hour_count"]
        + candidate["low_cycle_hour_count"]
        != candidate["measured_hour_count"]
        or candidate["exploitable_hour_count"]
        != candidate["normalized_hour_count"]
        + candidate["out_of_domain_hour_count"]
        or candidate["exploitable_hour_count"]
        != candidate["historical_hour_count"] + candidate["extended_hour_count"]
    ):
        return False
    for name in count_names - {"no_temperature_hour_count"}:
        if candidate[name] < active[name]:
            return False
    if candidate["no_temperature_hour_count"] > candidate["measured_hour_count"]:
        return False
    for name, direction in (("temperature_min_c", -1), ("temperature_max_c", 1)):
        old, new = active.get(name), candidate.get(name)
        if old is not None and new is None:
            return False
        if old is not None and new is not None and (
            not _number(new) or (direction < 0 and new > old) or (direction > 0 and new < old)
        ):
            return False
    return True


def _merge_processed_metadata(
    active: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    candidate = _expect_object(
        candidate,
        _PROCESSED_DYNAMIC_METADATA_KEYS,
        "REFRESH_PROCESSED_SCHEMA_DIVERGED",
    )
    active_end = _source_hour(active["coverage_end"], "REFRESH_PROCESSED_HISTORY_DIVERGED")
    candidate_end = _source_hour(
        candidate["coverage_end"], "REFRESH_PROCESSED_HISTORY_DIVERGED"
    )
    if candidate_end < active_end:
        raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
    active_extension = active["thermal_extension"]
    candidate_extension = candidate["thermal_extension"]
    if not isinstance(active_extension, dict):
        raise RefreshError("REFRESH_PROCESSED_SCHEMA_DIVERGED")
    candidate_extension = _expect_object(
        candidate_extension,
        _PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS,
        "REFRESH_PROCESSED_SCHEMA_DIVERGED",
    )
    old_full = active["full_y_range_mm"]
    new_full = candidate["full_y_range_mm"]
    new_robust = candidate["robust_y_range_mm"]
    if (
        candidate["delivery_revision"] != _PROCESSED_DELIVERY_REVISION
        or not isinstance(old_full, list)
        or not isinstance(new_full, list)
        or len(new_full) != 2
        or not all(_number(value) for value in new_full)
        or new_full[0] > old_full[0]
        or new_full[1] < old_full[1]
        or not isinstance(new_robust, list)
        or len(new_robust) != 2
        or not all(_number(value) for value in new_robust)
        or new_full[0] > new_robust[0]
        or new_robust[1] > new_full[1]
        or type(candidate["robust_outside_hourly_point_count"]) is not int
        or candidate["robust_outside_hourly_point_count"] < 0
    ):
        raise RefreshError("REFRESH_PROCESSED_METADATA_DIVERGED")
    merged_extension = dict(active_extension)
    for name in _PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS:
        merged_extension[name] = candidate_extension[name]
    merged = dict(active)
    for name in _PROCESSED_DYNAMIC_METADATA_KEYS - {"thermal_extension"}:
        merged[name] = candidate[name]
    merged["thermal_extension"] = merged_extension
    return merged


def _merge_processed_origins(
    active: object, candidate: object
) -> list[dict[str, object]]:
    code = "REFRESH_PROCESSED_ORIGIN_DIVERGED"
    if not isinstance(active, list) or not isinstance(candidate, list) or len(candidate) != 37:
        raise RefreshError(code)
    for index, (old, new) in enumerate(zip(active, candidate, strict=True)):
        if (
            not isinstance(old, dict)
            or not isinstance(new, dict)
            or set(new) != _PROCESSED_ORIGIN_KEYS
            or not isinstance(old["thermal"], dict)
            or not isinstance(new["thermal"], dict)
        ):
            raise RefreshError(code)
        structural_names = (
            ("center_mm", "end", "id", "n", "start")
            if index < 36
            else ("center_mm", "id", "start")
        )
        if any(old[name] != new[name] for name in structural_names):
            raise RefreshError(code)
        if (
            type(new["n"]) is not int
            or new["n"] < old["n"]
            or _source_hour(new["end"], code) < _source_hour(old["end"], code)
            or (old["thermal_available"] is True and new["thermal_available"] is not True)
            or not _coverage_progressed(old["thermal"], new["thermal"])
            or new["thermal"]["historical_hour_count"]
            != old["thermal"]["historical_hour_count"]
            or new["n"] != new["thermal"]["measured_hour_count"]
        ):
            raise RefreshError(code)
    return candidate


def _validate_closed_daily_history(
    active: list[list[object]], candidate: list[list[object]], watermark: str
) -> None:
    closed_date = watermark[:10]
    old_closed = [row for row in active if row[1] < closed_date]
    new_closed = [row for row in candidate if row[1] < closed_date]
    if old_closed != new_closed:
        raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")


def _validate_baseline_proof(payload: Mapping[str, object]) -> None:
    proof = _PROCESSED_BASELINE_PROOF
    hourly_count = proof["hourly_prefix_count"]
    global_count = proof["global_hourly_prefix_count"]
    sg5_count = proof["global_hourly_stable_sg5_prefix_count"]
    daily_count = proof["daily_prefix_count"]
    global_daily_count = proof["global_daily_prefix_count"]
    global_projection = [
        row[:6] + row[8:] for row in payload["global_hourly"][:global_count]
    ]
    if (
        len(payload["hourly"]) < hourly_count
        or len(payload["global_hourly"]) < global_count
        or len(payload["daily"]) < daily_count
        or len(payload["global_daily"]) < global_daily_count
        or _value_sha256(payload["hourly"][:hourly_count])
        != proof["hourly_prefix_sha256"]
        or _value_sha256(global_projection)
        != proof["global_hourly_prefix_without_sg5_sha256"]
        or _value_sha256(payload["global_hourly"][:sg5_count])
        != proof["global_hourly_stable_sg5_prefix_sha256"]
        or _value_sha256(payload["daily"][:daily_count])
        != proof["daily_prefix_sha256"]
        or _value_sha256(payload["global_daily"][:global_daily_count])
        != proof["global_daily_prefix_sha256"]
        or payload["hourly"][hourly_count - 1][1]
        != proof["stable_source_hour_inclusive"]
        or payload["global_hourly"][sg5_count - 1][1]
        != proof["global_hourly_stable_sg5_source_hour_inclusive"]
    ):
        raise RefreshError("REFRESH_PROCESSED_BASELINE_PROOF_DIVERGED")


def _validate_thermal_transition(
    active: list[list[object]],
    candidate: list[list[object]],
    *,
    initial_anchor: bool,
) -> set[str]:
    if len(candidate) < len(active):
        raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
    transitions: set[int] = set()
    affected_months = {row[1][:7] for row in candidate[len(active) :]}
    provisional_index = len(active) - 1 if initial_anchor else None
    for index, old in enumerate(active):
        new = candidate[index]
        if index == provisional_index:
            immutable = (0, 1, 2, 3, 4, 6, 15, 16, 17, 18, 19, 20, 21, 27)
            if (
                any(old[position] != new[position] for position in immutable)
                or new[28] < old[28]
            ):
                raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
        elif any(
            old[position] != new[position]
            for position in (*range(0, 8), *range(15, 22), *range(26, 29))
        ):
            raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
        if old[8] is not None:
            if old[:22] != new[:22]:
                raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
            continue
        if new[8] is None:
            dynamic = {5, 7, 26, 28} if index == provisional_index else set()
            if any(
                old[position] != new[position]
                for position in range(22)
                if position not in dynamic
            ):
                raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
            continue
        if old[14] == "LOW_CYCLE_SUPPORT":
            if (
                new[14] != "LOW_CYCLE_SUPPORT"
                or old[9:15] != new[9:15]
                or old[19:22] != new[19:22]
            ):
                raise RefreshError("REFRESH_PROCESSED_THERMAL_TRANSITION_INVALID")
            continue
        if old[14] != "NO_EXACT_OUTDOOR_TEMPERATURE":
            raise RefreshError("REFRESH_PROCESSED_THERMAL_TRANSITION_INVALID")
        transitions.add(index)
        affected_months.add(new[1][:7])
    changed_sg5 = {
        index
        for index in range(len(active))
        if active[index][22:26] != candidate[index][22:26]
    }
    allowed_sg5: set[int] = set()
    for index in transitions:
        allowed_sg5.update(range(max(0, index - 2), min(len(active), index + 3)))
    if provisional_index is not None:
        allowed_sg5.update(
            range(max(0, provisional_index - 2), min(len(active), provisional_index + 3))
        )
    if len(candidate) > len(active):
        for center in range(max(0, len(active) - 2), len(active)):
            support = range(max(0, center - 2), min(len(candidate), center + 3))
            if (
                center < len(candidate) - 2
                and any(index >= len(active) and candidate[index][8] is not None for index in support)
            ):
                allowed_sg5.add(center)
    if not changed_sg5 <= allowed_sg5:
        raise RefreshError("REFRESH_PROCESSED_THERMAL_TRANSITION_INVALID")
    return affected_months


def _validate_processed_transition_values(
    active_payload: Mapping[str, object],
    candidate_payload: Mapping[str, object],
    active_review: Mapping[str, object],
    candidate_review: Mapping[str, object],
    *,
    initial_anchor: bool,
) -> None:
    _validate_baseline_proof(active_payload)
    _validate_baseline_proof(candidate_payload)
    for name in {"events", "offsets", "origin_starts", "resumptions", "thermal"}:
        if active_payload[name] != candidate_payload[name]:
            raise RefreshError("REFRESH_PROCESSED_STATIC_PAYLOAD_DIVERGED")
    active_hourly = active_payload["hourly"]
    candidate_hourly = candidate_payload["hourly"]
    active_global = active_payload["global_hourly"]
    candidate_global = candidate_payload["global_hourly"]
    if len(candidate_hourly) < len(active_hourly) or len(candidate_global) < len(active_global):
        raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
    if initial_anchor:
        stable_count = _PROCESSED_BASELINE_PROOF["hourly_prefix_count"]
        sg5_count = _PROCESSED_BASELINE_PROOF[
            "global_hourly_stable_sg5_prefix_count"
        ]
        if (
            active_hourly[:stable_count] != candidate_hourly[:stable_count]
            or active_global[:sg5_count] != candidate_global[:sg5_count]
            or [row[:6] + row[8:] for row in active_global[:stable_count]]
            != [row[:6] + row[8:] for row in candidate_global[:stable_count]]
        ):
            raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
        provisional = stable_count
        old = active_hourly[provisional]
        new = candidate_hourly[provisional]
        if (
            any(old[position] != new[position] for position in (0, 1, 2, 3, 9))
            or new[10] < old[10]
        ):
            raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
    elif (
        candidate_hourly[: len(active_hourly)] != active_hourly
        or candidate_global[: len(active_global)] != active_global
    ):
        raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")
    active_end = active_payload["metadata"]["coverage_end"]
    _validate_closed_daily_history(
        active_payload["daily"], candidate_payload["daily"], active_end
    )
    _validate_closed_daily_history(
        active_payload["global_daily"], candidate_payload["global_daily"], active_end
    )
    affected_months = _validate_thermal_transition(
        active_payload["thermal_extended"],
        candidate_payload["thermal_extended"],
        initial_anchor=initial_anchor,
    )
    _merge_processed_origins(active_payload["origins"], candidate_payload["origins"])
    active_coverage = active_payload["thermal_coverage"]
    candidate_coverage = candidate_payload["thermal_coverage"]
    for index, (old, new) in enumerate(
        zip(active_coverage, candidate_coverage, strict=True)
    ):
        if (
            not _coverage_progressed(old, new)
            or new["historical_hour_count"] != old["historical_hour_count"]
            or (index < 36 and new["measured_hour_count"] != old["measured_hour_count"])
            or {
                key: value
                for key, value in new.items()
                if key != "analysis_origin_regime_id"
            }
            != candidate_payload["origins"][index]["thermal"]
        ):
            raise RefreshError("REFRESH_PROCESSED_ORIGIN_DIVERGED")
    candidate_metadata_update = {
        name: candidate_payload["metadata"][name]
        for name in _PROCESSED_DYNAMIC_METADATA_KEYS
    }
    candidate_metadata_update["thermal_extension"] = {
        name: candidate_payload["metadata"]["thermal_extension"][name]
        for name in _PROCESSED_DYNAMIC_THERMAL_EXTENSION_KEYS
    }
    if (
        _merge_processed_metadata(
            active_payload["metadata"], candidate_metadata_update
        )
        != candidate_payload["metadata"]
    ):
        raise RefreshError("REFRESH_PROCESSED_MODEL_DIVERGED")
    for name in _PROCESSED_REVIEW_KEYS - _PROCESSED_REVIEW_UPDATE_KEYS:
        if active_review[name] != candidate_review[name]:
            raise RefreshError("REFRESH_PROCESSED_REVIEW_STATIC_DIVERGED")
    _validate_review_against_payload(active_review, active_payload)
    _validate_review_against_payload(candidate_review, candidate_payload)
    old_monthly = {
        item["month"]: item for item in active_review["monthlyThermalAdjustments"]
    }
    new_monthly = {
        item["month"]: item for item in candidate_review["monthlyThermalAdjustments"]
    }
    for month in set(old_monthly) | set(new_monthly):
        if month not in affected_months and old_monthly.get(month) != new_monthly.get(month):
            raise RefreshError("REFRESH_PROCESSED_HISTORY_DIVERGED")


def validate_processed_transition(active: bytes, candidate: bytes) -> bytes:
    active_match, active_payload, _, active_review = _processed_document(active)
    candidate_match, candidate_payload, _, candidate_review = _processed_document(candidate)
    initial_anchor = (
        hashlib.sha256(active_match.group(2)).hexdigest()
        == PROCESSED_BASE_PAYLOAD_SHA256
    )
    del candidate_match
    if (
        processed_data_only_skeleton(active) != processed_data_only_skeleton(candidate)
        or processed_template_sha256(active) != PROCESSED_BASE_TEMPLATE_SHA256
    ):
        raise RefreshError("REFRESH_PROCESSED_TEMPLATE_DIVERGED")
    _validate_processed_transition_values(
        active_payload,
        candidate_payload,
        active_review,
        candidate_review,
        initial_anchor=initial_anchor,
    )
    return candidate


def refresh_processed(active: bytes, patch_payload: bytes) -> bytes:
    patch = _parse_processed_patch(patch_payload)
    payload_match, active_payload, review_match, active_review = _processed_document(active)
    initial_anchor = (
        hashlib.sha256(payload_match.group(2)).hexdigest()
        == PROCESSED_BASE_PAYLOAD_SHA256
    )
    if processed_template_sha256(active) != patch["base_template_sha256"]:
        raise RefreshError("REFRESH_PROCESSED_TEMPLATE_DIVERGED")
    replacements = patch["replacements"]
    candidate_payload = dict(active_payload)
    for name in _PROCESSED_REPLACEMENT_KEYS - {"metadata", "origins"}:
        candidate_payload[name] = replacements[name]
    candidate_payload["metadata"] = _merge_processed_metadata(
        active_payload["metadata"], replacements["metadata"]
    )
    candidate_payload["origins"] = _merge_processed_origins(
        active_payload["origins"], replacements["origins"]
    )
    candidate_payload = _validate_processed_payload(candidate_payload)
    sensor = patch["sensor_source"]
    if candidate_payload["metadata"]["coverage_end"] != sensor["closed_source_hour"]:
        raise RefreshError("REFRESH_PROCESSED_WATERMARK_DIVERGED")
    review_update = patch["review_diagnostics_update"]
    candidate_review = dict(active_review)
    candidate_review.update(review_update)
    candidate_review = _validate_processed_review(candidate_review)
    _validate_processed_transition_values(
        active_payload,
        candidate_payload,
        active_review,
        candidate_review,
        initial_anchor=initial_anchor,
    )
    result = _replace_span(active, review_match, _canonical_json(candidate_review))
    result = _replace_span(result, payload_match, _canonical_json(candidate_payload))
    validate_processed_transition(active, result)
    return result


def _replace_ranges(
    payload: bytes, replacements: Iterable[tuple[int, int, bytes]]
) -> bytes:
    result = payload
    ordered = sorted(replacements, key=lambda item: item[0])
    if any(start < 0 or end < start for start, end, _ in ordered):
        raise RefreshError("REFRESH_PATTERN_TEMPLATE_INVALID")
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise RefreshError("REFRESH_PATTERN_TEMPLATE_INVALID")
    for start, end, replacement in reversed(ordered):
        result = result[:start] + replacement + result[end:]
    return result


def _pattern_metadata_assignment(
    payload: bytes,
) -> tuple[dict[str, object], int, int]:
    prefix = _one(
        _PATTERN_METADATA_PREFIX,
        payload,
        "REFRESH_PATTERN_METADATA_UNEXPECTED",
    )
    start = prefix.end()
    try:
        text = payload[start:].decode("utf-8")
        value, consumed = json.JSONDecoder(
            parse_constant=_reject_json_constant
        ).raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RefreshError("REFRESH_PATTERN_METADATA_INVALID") from error
    end = start + len(text[:consumed].encode("utf-8"))
    semicolon = end
    while payload[semicolon : semicolon + 1] in {b" ", b"\t", b"\r", b"\n"}:
        semicolon += 1
    if payload[semicolon : semicolon + 1] != b";" or not isinstance(value, dict):
        raise RefreshError("REFRESH_PATTERN_METADATA_INVALID")
    return value, start, end


def _pattern_document(
    payload: bytes,
) -> tuple[
    re.Match[bytes],
    dict[str, object],
    tuple[int, int],
    dict[str, object],
    re.Match[bytes],
]:
    pattern_payload = _one(
        _PATTERN_PAYLOAD, payload, "REFRESH_PATTERN_PAYLOAD_UNEXPECTED"
    )
    value = _strict_json(
        pattern_payload.group(2), "REFRESH_PATTERN_PAYLOAD_INVALID"
    )
    metadata, metadata_start, metadata_end = _pattern_metadata_assignment(payload)
    cards = _one(_PATTERN_CARDS, payload, "REFRESH_PATTERN_CARDS_UNEXPECTED")
    if not isinstance(value, dict):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_INVALID")
    _validate_json_tree(value, "REFRESH_PATTERN_JSON_TREE_INVALID")
    _validate_json_tree(metadata, "REFRESH_PATTERN_JSON_TREE_INVALID")
    return (
        pattern_payload,
        value,
        (metadata_start, metadata_end),
        metadata,
        cards,
    )


def pattern_data_only_skeleton(payload: bytes) -> bytes:
    pattern_payload, value, metadata_span, metadata, cards = _pattern_document(payload)
    kind = _pattern_kind(metadata)
    _validate_pattern_payload(kind, value, metadata)
    if cards.group(0) != _render_pattern_cards(kind, value):
        raise RefreshError("REFRESH_PATTERN_PUBLIC_CARDS_DIVERGED")
    static_metadata = dict(metadata)
    static_metadata["bootstrap"] = "__PATTERN_BOOTSTRAP__"
    static_metadata["counts"] = "__PATTERN_COUNTS__"
    return _replace_ranges(
        payload,
        (
            (pattern_payload.start(2), pattern_payload.end(2), b"__PATTERN_PAYLOAD__"),
            (*metadata_span, _html_safe_json(static_metadata)),
            (cards.start(), cards.end(), b"__PATTERN_CARDS__"),
        ),
    )


def _pattern_kind(metadata: Mapping[str, object]) -> str:
    figure_id = metadata.get("figure_id")
    if figure_id == "D2-CAP-LEGACY-MEDIAN-DAY":
        return "median"
    if figure_id == "D2-CAP-LEGACY-EXTREMA-DISTRIBUTIONS":
        return "extrema"
    raise RefreshError("REFRESH_PATTERN_FIGURE_ID_INVALID")


def _validate_pattern_counts(counts: Mapping[str, object]) -> None:
    flags = {
        "daily_extrema_day_partition_is_exhaustive",
        "legacy_thinning_partition_is_exhaustive",
        "source_partition_is_exhaustive",
    }
    if any(counts.get(name) is not True for name in flags):
        raise RefreshError("REFRESH_PATTERN_COUNTS_INVALID")
    numeric = set(counts) - flags
    if any(type(counts[name]) is not int or counts[name] < 0 for name in numeric):
        raise RefreshError("REFRESH_PATTERN_COUNTS_INVALID")
    if (
        counts["source_record_count"]
        != counts["eligible_timestamp_and_finite_value_record_count"]
        + counts["excluded_both_timestamp_and_value_record_count"]
        + counts["excluded_non_finite_value_only_record_count"]
        + counts["excluded_unanalyzable_timestamp_only_record_count"]
        or counts["finite_source_value_record_count"]
        != counts["eligible_timestamp_and_finite_value_record_count"]
        + counts["excluded_unanalyzable_timestamp_only_record_count"]
        or counts["timestamp_analyzable_record_count"]
        != counts["eligible_timestamp_and_finite_value_record_count"]
        + counts["excluded_non_finite_value_only_record_count"]
        or counts["timestamp_records_before_legacy_thinning"]
        != counts["timestamp_analyzable_record_count"]
        or counts["timestamp_records_after_legacy_thinning"]
        + counts["timestamp_records_excluded_by_legacy_thinning"]
        != counts["timestamp_records_before_legacy_thinning"]
        or counts["source_naive_day_count_with_finite_retained_records"]
        != counts["daily_extrema_accepted_day_count"]
        + counts["daily_extrema_excluded_day_count"]
        or counts["minimum_primary_cluster_day_count"]
        + counts["minimum_outside_primary_cluster_day_count"]
        != counts["daily_extrema_accepted_day_count"]
        or counts["maximum_primary_cluster_day_count"]
        + counts["maximum_outside_primary_cluster_day_count"]
        != counts["daily_extrema_accepted_day_count"]
        or counts["finite_records_after_legacy_thinning"]
        > counts["timestamp_records_after_legacy_thinning"]
    ):
        raise RefreshError("REFRESH_PATTERN_COUNTS_COHERENCE_INVALID")


def _pattern_metadata_transition(
    active: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    if set(active) != _PATTERN_METADATA_KEYS or set(candidate) != _PATTERN_METADATA_KEYS:
        raise RefreshError("REFRESH_PATTERN_METADATA_SCHEMA_DIVERGED")
    if active.get("review_status") != "VALIDÉ":
        raise RefreshError("REFRESH_PATTERN_PUBLIC_STATUS_DIVERGED")
    if candidate.get("review_status") not in {
        "EXÉCUTÉ_NON_VALIDÉ — validation visuelle requise",
        "VALIDÉ",
    }:
        raise RefreshError("REFRESH_PATTERN_CANDIDATE_STATUS_INVALID")
    if any(active[name] != candidate[name] for name in _PATTERN_STATIC_METADATA_KEYS):
        raise RefreshError("REFRESH_PATTERN_STATIC_METADATA_DIVERGED")
    active_counts = active.get("counts")
    candidate_counts = candidate.get("counts")
    if not isinstance(active_counts, dict) or not isinstance(candidate_counts, dict):
        raise RefreshError("REFRESH_PATTERN_COUNTS_INVALID")
    if set(active_counts) != set(candidate_counts):
        raise RefreshError("REFRESH_PATTERN_COUNTS_SCHEMA_DIVERGED")
    _validate_pattern_counts(active_counts)
    _validate_pattern_counts(candidate_counts)
    for name in (
        "source_record_count",
        "source_naive_day_count_with_finite_retained_records",
        "daily_extrema_accepted_day_count",
        "profile_day_slot_cell_count",
    ):
        old = active_counts.get(name)
        new = candidate_counts.get(name)
        if type(old) is not int or type(new) is not int or old < 0 or new < old:
            raise RefreshError("REFRESH_PATTERN_COUNT_REGRESSION")
    if not isinstance(candidate.get("bootstrap"), dict):
        raise RefreshError("REFRESH_PATTERN_BOOTSTRAP_INVALID")
    merged = dict(active)
    merged["bootstrap"] = candidate["bootstrap"]
    merged["counts"] = candidate_counts
    merged["review_status"] = "VALIDÉ"
    return merged


def _finite_list(value: object, *, allow_empty: bool = False) -> list[object]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not _number(item) for item in value)
    ):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    return value


def _hour_observations(value: object, *, allow_empty: bool = False) -> list[object]:
    values = _finite_list(value, allow_empty=allow_empty)
    if any(not 0.0 <= float(item) < 24.0 for item in values):
        raise RefreshError("REFRESH_PATTERN_HOUR_DOMAIN_INVALID")
    return values


def _highest_interior_peak(density: list[object]) -> int | None:
    """Mirror the producer's non-flat interior peak selection."""
    peaks: list[int] = []
    index = 1
    while index < len(density) - 1:
        if density[index] <= density[index - 1]:
            index += 1
            continue
        plateau_end = index
        while (
            plateau_end + 1 < len(density)
            and density[plateau_end + 1] == density[index]
        ):
            plateau_end += 1
        if (
            plateau_end < len(density) - 1
            and density[plateau_end] > density[plateau_end + 1]
        ):
            peaks.append((index + plateau_end) // 2)
        index = plateau_end + 1
    return max(peaks, key=lambda item: density[item]) if peaks else None


def _validate_median_pattern_payload(
    payload: Mapping[str, object], metadata: Mapping[str, object]
) -> None:
    keys = {
        "day_count",
        "estimate",
        "slot_index",
        "slot_start_hours",
        "source_naive_time",
        "step_estimate",
        "step_hours",
        "step_source_naive_time",
    }
    if set(payload) != keys:
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_SCHEMA_DIVERGED")
    counts = payload["day_count"]
    estimates = payload["estimate"]
    slot_indices = payload["slot_index"]
    slot_hours = payload["slot_start_hours"]
    source_times = payload["source_naive_time"]
    step_estimates = payload["step_estimate"]
    step_hours = payload["step_hours"]
    step_times = payload["step_source_naive_time"]
    expected_times = [
        f"{index // 2:02d}:{(index % 2) * 30:02d}" for index in range(48)
    ]
    if (
        not isinstance(counts, list)
        or len(counts) != 48
        or any(type(item) is not int or item < 1 for item in counts)
        or not isinstance(estimates, list)
        or len(estimates) != 48
        or any(not _number(item) for item in estimates)
        or slot_indices != list(range(48))
        or slot_hours != [index / 2 for index in range(48)]
        or not isinstance(source_times, list)
        or source_times != expected_times
        or step_estimates != estimates + [estimates[-1]]
        or step_hours != [index / 2 for index in range(49)]
        or step_times != expected_times + ["24:00"]
    ):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    metadata_counts = metadata.get("counts")
    if (
        not isinstance(metadata_counts, dict)
        or metadata_counts.get("profile_day_slot_cell_count") != sum(counts)
    ):
        raise RefreshError("REFRESH_PATTERN_COUNTS_PAYLOAD_DIVERGED")


def _validate_extrema_item(
    name: str, value: object, metadata: Mapping[str, object]
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "hour_kde",
        "hours",
        "outside_hours",
        "primary_hour_cluster",
        "retained_hours",
        "timing",
    }:
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_SCHEMA_DIVERGED")
    hours = _hour_observations(value["hours"])
    retained = _hour_observations(value["retained_hours"])
    outside = _hour_observations(value["outside_hours"], allow_empty=True)
    timing = value["timing"]
    cluster = value["primary_hour_cluster"]
    kde = value["hour_kde"]
    metadata_counts = metadata.get("counts")
    metadata_method = metadata.get("method")
    metadata_bootstrap = metadata.get("bootstrap")
    primary_method = (
        metadata_method.get("primary_hour_cluster")
        if isinstance(metadata_method, dict)
        else None
    )
    interval = timing.get("ci95") if isinstance(timing, dict) else None
    interval_start = interval.get("arc_start_hours") if isinstance(interval, dict) else None
    interval_end = interval.get("arc_end_hours") if isinstance(interval, dict) else None
    wraps_midnight = interval.get("wraps_midnight") if isinstance(interval, dict) else None
    central = timing.get("central_time_hours") if isinstance(timing, dict) else None
    mode = cluster.get("kde_mode_hours") if isinstance(cluster, dict) else None
    half_width = cluster.get("half_width_hours") if isinstance(cluster, dict) else None
    window_width = cluster.get("window_width_hours") if isinstance(cluster, dict) else None
    if (
        not isinstance(timing, dict)
        or not isinstance(cluster, dict)
        or not isinstance(kde, dict)
        or not isinstance(metadata_counts, dict)
        or not isinstance(primary_method, dict)
        or not isinstance(metadata_bootstrap, dict)
        or set(timing)
        != {
            "central_estimator",
            "central_time_hours",
            "ci95",
            "day_count",
            "outside_primary_cluster_day_count",
            "primary_cluster_day_count",
        }
        or not isinstance(interval, dict)
        or set(interval)
        != {
            "arc_end_hours",
            "arc_start_hours",
            "method",
            "successful_replicates",
            "wraps_midnight",
        }
        or set(cluster)
        != {
            "half_width_hours",
            "kde_mode_hours",
            "outside_cluster_day_count",
            "retained_day_count",
            "window_width_hours",
        }
        or set(kde) != {"density", "grid_hours", "method"}
        or timing.get("central_estimator") != "PRIMARY_GAUSSIAN_KDE_MODE"
        or interval.get("method")
        != "CONSERVATIVE_ENVELOPE_OF_CIRCULAR_MOVING_BLOCK_SENSITIVITIES"
        or kde.get("method") != "GAUSSIAN_KDE"
        or not _number(interval_start)
        or not _number(interval_end)
        or not 0.0 <= float(interval_start) <= 24.0
        or not 0.0 <= float(interval_end) <= 24.0
        or type(wraps_midnight) is not bool
        or wraps_midnight != (float(interval_start) > float(interval_end))
        or not _number(central)
        or not 0.0 <= float(central) < 24.0
        or not _number(mode)
        or not 0.0 <= float(mode) < 24.0
        or not _number(half_width)
        or not 0.0 < float(half_width) <= 24.0
        or not _number(window_width)
        or not 0.0 < float(window_width) <= 24.0
        or not _same_number(window_width, float(half_width) * 2.0)
        or not _same_number(
            window_width, primary_method.get("window_width_hours")
        )
        or primary_method.get("method")
        != "HIGHEST_GAUSSIAN_KDE_DENSITY_PEAK_ON_0_TO_24_HOUR_GRID"
        or type(primary_method.get("grid_steps")) is not int
        or primary_method["grid_steps"] < 2
        or type(interval.get("successful_replicates")) is not int
        or interval["successful_replicates"] < 1
        or interval["successful_replicates"]
        != metadata_bootstrap.get(f"{name}_successful_replicates")
        or type(timing.get("day_count")) is not int
        or type(timing.get("primary_cluster_day_count")) is not int
        or type(timing.get("outside_primary_cluster_day_count")) is not int
        or timing["day_count"] != len(hours)
        or timing["primary_cluster_day_count"] != len(retained)
        or timing["outside_primary_cluster_day_count"] != len(outside)
        or len(retained) + len(outside) != len(hours)
        or sorted(retained + outside) != sorted(hours)
        or cluster.get("retained_day_count") != len(retained)
        or cluster.get("outside_cluster_day_count") != len(outside)
        or not _same_number(
            mode, central
        )
        or metadata_counts.get(f"{name}_primary_cluster_day_count") != len(retained)
        or metadata_counts.get(f"{name}_outside_primary_cluster_day_count")
        != len(outside)
    ):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    grid = _finite_list(kde.get("grid_hours"))
    density = _finite_list(kde.get("density"))
    if (
        len(grid) != len(density)
        or len(grid) != primary_method["grid_steps"]
        or any(not 0.0 <= float(item) <= 24.0 for item in grid)
        or any(left >= right for left, right in zip(grid, grid[1:]))
        or any(float(item) < 0.0 for item in density)
    ):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    peak_index = _highest_interior_peak(density)
    expected_mode = (
        grid[peak_index]
        if peak_index is not None
        else sum(float(hour) for hour in hours) / len(hours)
    )
    if (
        not _same_number(grid[0], 0.0)
        or not _same_number(grid[-1], 24.0)
        or not _same_number(mode, expected_mode)
    ):
        raise RefreshError("REFRESH_PATTERN_KDE_MODE_DIVERGED")

    def circular_distance(hour: object) -> float:
        return abs(((float(hour) - float(mode) + 12.0) % 24.0) - 12.0)

    if any(
        circular_distance(hour) > float(half_width)
        for hour in retained
    ) or any(
        circular_distance(hour) <= float(half_width)
        for hour in outside
    ):
        raise RefreshError("REFRESH_PATTERN_CLUSTER_PARTITION_DIVERGED")


def _validate_extrema_pattern_payload(
    payload: Mapping[str, object], metadata: Mapping[str, object]
) -> None:
    if set(payload) != {"maximum", "minimum"}:
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_SCHEMA_DIVERGED")
    counts = metadata.get("counts")
    if not isinstance(counts, dict):
        raise RefreshError("REFRESH_PATTERN_COUNTS_INVALID")
    for name in ("minimum", "maximum"):
        _validate_extrema_item(name, payload[name], metadata)
    minimum_days = payload["minimum"]["timing"]["day_count"]
    maximum_days = payload["maximum"]["timing"]["day_count"]
    if (
        minimum_days != maximum_days
        or counts.get("daily_extrema_accepted_day_count") != minimum_days
        or type(counts.get("daily_extrema_excluded_day_count")) is not int
        or counts.get("source_naive_day_count_with_finite_retained_records")
        != minimum_days + counts["daily_extrema_excluded_day_count"]
    ):
        raise RefreshError("REFRESH_PATTERN_COUNTS_PAYLOAD_DIVERGED")


def _format_pattern_hour(
    value: object,
    *,
    bound: str = "nearest",
    preserve_upper_24: bool = False,
) -> str:
    if not _number(value):
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    number = float(value)
    if (
        bound == "upper"
        and preserve_upper_24
        and math.isclose(number, 24.0, rel_tol=0.0, abs_tol=1e-12)
    ):
        return "24 h 00"
    scaled = (number % 24.0) * 4.0
    if bound == "lower":
        quarter = math.floor(scaled + 1e-12)
    elif bound == "upper":
        quarter = math.ceil(scaled - 1e-12)
    elif bound == "nearest":
        quarter = int(round(scaled))
    else:
        raise RefreshError("REFRESH_PATTERN_PAYLOAD_COHERENCE_INVALID")
    if bound == "upper" and preserve_upper_24 and quarter == 96:
        return "24 h 00"
    quarter %= 96
    return f"{quarter // 4:02d} h {(quarter % 4) * 15:02d}"


def _render_pattern_cards(kind: str, payload: Mapping[str, object]) -> bytes:
    if kind == "median":
        counts = payload["day_count"]
        return (
            '<section class="cards" aria-label="Repères statistiques">'
            '<div class="card"><strong>Médiane par demi-heure</strong>'
            f"<span>{len(counts)} créneaux ; {min(counts)} à {max(counts)} jours "
            "observés selon le créneau.</span></div></section>"
        ).encode("utf-8")
    cards: list[str] = []
    for name, label in (("minimum", "Minimum"), ("maximum", "Maximum")):
        timing = payload[name]["timing"]
        interval = timing["ci95"]
        midnight_suffix = " (par minuit)" if interval["wraps_midnight"] else ""
        cards.append(
            '<div class="card"><strong>'
            f'{label} : {_format_pattern_hour(timing["central_time_hours"])}'
            "</strong><span>Horaire principal · intervalle d’incertitude à 95 % : "
            f'{_format_pattern_hour(interval["arc_start_hours"], bound="lower")} à '
            f'{_format_pattern_hour(interval["arc_end_hours"], bound="upper", preserve_upper_24=not interval["wraps_midnight"])}'
            f"{midnight_suffix} · "
            f'{timing["primary_cluster_day_count"]} jours dans le groupe horaire '
            f'principal sur {timing["day_count"]} ; '
            f'{timing["outside_primary_cluster_day_count"]} autres horaires '
            "observés.</span></div>"
        )
    return (
        '<section class="cards" aria-label="Repères statistiques">'
        + "".join(cards)
        + "</section>"
    ).encode("utf-8")


def _validate_pattern_payload(
    kind: str, payload: Mapping[str, object], metadata: Mapping[str, object]
) -> None:
    if kind == "median":
        _validate_median_pattern_payload(payload, metadata)
    else:
        _validate_extrema_pattern_payload(payload, metadata)


def refresh_pattern(active: bytes, candidate: bytes) -> bytes:
    active_document = _pattern_document(active)
    candidate_document = _pattern_document(candidate)
    active_match, active_payload, active_metadata_span, active_metadata, active_cards = (
        active_document
    )
    _, candidate_payload, _, candidate_metadata, _ = candidate_document
    active_kind = _pattern_kind(active_metadata)
    if _pattern_kind(candidate_metadata) != active_kind:
        raise RefreshError("REFRESH_PATTERN_FIGURE_ID_INVALID")
    merged_metadata = _pattern_metadata_transition(active_metadata, candidate_metadata)
    _validate_pattern_payload(active_kind, active_payload, active_metadata)
    _validate_pattern_payload(active_kind, candidate_payload, merged_metadata)
    if active_cards.group(0) != _render_pattern_cards(active_kind, active_payload):
        raise RefreshError("REFRESH_PATTERN_PUBLIC_CARDS_DIVERGED")
    if active_kind == "median":
        if any(
            new < old
            for old, new in zip(
                active_payload["day_count"],
                candidate_payload["day_count"],
                strict=True,
            )
        ):
            raise RefreshError("REFRESH_PATTERN_DAY_COUNT_REGRESSION")
    else:
        for name in ("minimum", "maximum"):
            if (
                candidate_payload[name]["timing"]["day_count"]
                < active_payload[name]["timing"]["day_count"]
            ):
                raise RefreshError("REFRESH_PATTERN_DAY_COUNT_REGRESSION")
    result = _replace_ranges(
        active,
        (
            (
                active_match.start(2),
                active_match.end(2),
                _html_safe_json(candidate_payload) + b"\n",
            ),
            (*active_metadata_span, _html_safe_json(merged_metadata)),
            (
                active_cards.start(),
                active_cards.end(),
                _render_pattern_cards(active_kind, candidate_payload),
            ),
        ),
    )
    result_document = _pattern_document(result)
    if result_document[3].get("review_status") != "VALIDÉ":
        raise RefreshError("REFRESH_PATTERN_PUBLIC_STATUS_DIVERGED")
    return result


def _validate_pattern_pair_documents(
    documents: Mapping[
        str,
        tuple[
            re.Match[bytes],
            dict[str, object],
            tuple[int, int],
            dict[str, object],
            re.Match[bytes],
        ],
    ]
) -> None:
    median_payload = documents[PATTERN_MEDIAN][1]
    median_metadata = documents[PATTERN_MEDIAN][3]
    extrema_payload = documents[PATTERN_EXTREMA][1]
    extrema_metadata = documents[PATTERN_EXTREMA][3]
    if (
        _pattern_kind(median_metadata) != "median"
        or _pattern_kind(extrema_metadata) != "extrema"
        or median_metadata.get("analysis_id") != extrema_metadata.get("analysis_id")
        or median_metadata.get("counts") != extrema_metadata.get("counts")
        or median_metadata.get("bootstrap") != extrema_metadata.get("bootstrap")
    ):
        raise RefreshError("REFRESH_PATTERN_PAIR_DIVERGED")
    _validate_median_pattern_payload(median_payload, median_metadata)
    _validate_extrema_pattern_payload(extrema_payload, extrema_metadata)


def refresh_pattern_pair(
    active: Mapping[str, bytes], candidate: Mapping[str, bytes]
) -> dict[str, bytes]:
    if set(active) != PATTERN_TARGETS or set(candidate) != PATTERN_TARGETS:
        raise RefreshError("REFRESH_PATTERN_PAIR_INCOMPLETE")
    active_documents = {name: _pattern_document(active[name]) for name in PATTERN_TARGETS}
    candidate_documents = {
        name: _pattern_document(candidate[name]) for name in PATTERN_TARGETS
    }
    _validate_pattern_pair_documents(active_documents)
    _validate_pattern_pair_documents(candidate_documents)
    return {
        name: refresh_pattern(active[name], candidate[name])
        for name in PATTERN_TARGETS
    }


def _plotly_data_span(payload: bytes) -> tuple[int, int]:
    """Return the JSON data argument of exactly one Plotly.newPlot call."""
    marker = b"Plotly.newPlot("
    starts = [m.start() for m in re.finditer(re.escape(marker), payload)]
    if len(starts) != 1:
        raise RefreshError("REFRESH_LEGACY_PLOTLY_CALL_UNEXPECTED")
    cursor = starts[0] + len(marker)
    # The first argument is the target div.  Find the following top-level comma
    # without being confused by a quoted target selector.
    quote, escaped, depth = 0, False, 0
    for index in range(cursor, len(payload)):
        char = payload[index]
        if quote:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == quote:
                quote = 0
        elif char in (34, 39):
            quote = char
        elif char in (40, 91, 123):
            depth += 1
        elif char in (41, 93, 125) and depth:
            depth -= 1
        elif char == 44 and depth == 0:
            cursor = index + 1
            break
    else:
        raise RefreshError("REFRESH_LEGACY_DATA_MISSING")
    start = cursor
    while start < len(payload) and payload[start] in b" \t\r\n":
        start += 1
    opener = payload[start:start + 1]
    if opener not in (b"[", b"{"):
        raise RefreshError("REFRESH_LEGACY_DATA_NOT_JSON")
    closer = b"]" if opener == b"[" else b"}"
    depth, quote, escaped = 0, 0, False
    for index in range(start, len(payload)):
        char = payload[index]
        if quote:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == quote:
                quote = 0
            continue
        if char in (34, 39):
            quote = char
        elif char == opener[0]:
            depth += 1
        elif char == closer[0]:
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise RefreshError("REFRESH_LEGACY_DATA_UNTERMINATED")


def legacy_data_only_skeleton(payload: bytes) -> bytes:
    start, end = _plotly_data_span(payload)
    return payload[:start] + b"__DATA__" + payload[end:]


def refresh_legacy(active: bytes, candidate: bytes) -> bytes:
    a_start, a_end = _plotly_data_span(active)
    c_start, c_end = _plotly_data_span(candidate)
    if legacy_data_only_skeleton(active) != legacy_data_only_skeleton(candidate):
        raise RefreshError("REFRESH_LEGACY_SKELETON_DIVERGED")
    return active[:a_start] + candidate[c_start:c_end] + active[a_end:]


def _strip_candidate_paragraph(payload: bytes) -> bytes:
    matches = [
        match
        for match in _PARAGRAPH.finditer(payload)
        if re.search(br"candidat\s+automatis", match.group(0), re.I)
    ]
    if len(matches) != 1:
        raise RefreshError("REFRESH_RAW_CANDIDATE_PARAGRAPH_UNEXPECTED")
    match = matches[0]
    line_start = payload.rfind(b"\n", 0, match.start()) + 1
    line_end = payload.find(b"\n", match.end())
    if payload[line_start:match.start()].strip() or line_end < 0:
        raise RefreshError("REFRESH_RAW_CANDIDATE_PARAGRAPH_UNEXPECTED")
    return payload[:line_start] + payload[line_end + 1:]


def raw_data_only_skeleton(payload: bytes, *, candidate: bool = False) -> bytes:
    if candidate:
        payload = _strip_candidate_paragraph(payload)
    meta = _one(_FIGURE_METADATA, payload, "REFRESH_RAW_METADATA_UNEXPECTED")
    payload = payload[:meta.start()] + b"__METADATA__" + payload[meta.end():]
    data = _one(_RAW_PAYLOAD, payload, "REFRESH_RAW_PAYLOAD_UNEXPECTED")
    return _replace_span(payload, data, b"__COMPRESSED_DATA__")


def _public_raw_metadata(payload: bytes) -> bytes:
    """Remove review-workflow state from metadata copied into the public master."""
    match = _one(_FIGURE_METADATA, payload, "REFRESH_RAW_METADATA_UNEXPECTED")
    assignment = match.group(0)
    try:
        value = json.loads(assignment[assignment.index(b"=") + 1 : -1])
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise RefreshError("REFRESH_RAW_METADATA_INVALID") from error
    if not isinstance(value, dict):
        raise RefreshError("REFRESH_RAW_METADATA_INVALID")
    validation = value.get("validation")
    if validation is not None:
        if not isinstance(validation, dict):
            raise RefreshError("REFRESH_RAW_METADATA_INVALID")
        candidate_status = validation.pop("candidate_status", None)
        review_required = validation.pop("review_required", None)
        substitution = validation.pop("automatic_master_substitution_permitted", None)
        if (
            candidate_status not in {None, "EXÉCUTÉ_NON_VALIDÉ"}
            or review_required not in {None, True}
            or substitution not in {None, False}
        ):
            raise RefreshError("REFRESH_RAW_METADATA_INVALID")
    replacement = b"const FIGURE_METADATA = " + _canonical_json(value) + b";"
    return payload[:match.start()] + replacement + payload[match.end():]


def refresh_raw(active: bytes, candidate: bytes) -> bytes:
    cleaned = _public_raw_metadata(_strip_candidate_paragraph(candidate))
    if raw_data_only_skeleton(active) != raw_data_only_skeleton(candidate, candidate=True):
        raise RefreshError("REFRESH_RAW_SKELETON_DIVERGED")
    active_meta = _one(_FIGURE_METADATA, active, "REFRESH_RAW_METADATA_UNEXPECTED")
    candidate_meta = _one(_FIGURE_METADATA, cleaned, "REFRESH_RAW_METADATA_UNEXPECTED")
    result = active[:active_meta.start()] + cleaned[candidate_meta.start():candidate_meta.end()] + active[active_meta.end():]
    active_data = _one(_RAW_PAYLOAD, result, "REFRESH_RAW_PAYLOAD_UNEXPECTED")
    candidate_data = _one(_RAW_PAYLOAD, cleaned, "REFRESH_RAW_PAYLOAD_UNEXPECTED")
    return _replace_span(result, active_data, candidate_data.group(2))


def _payload(payload: bytes) -> tuple[re.Match[bytes], object]:
    match = _one(_SCRIPT_PAYLOAD, payload, "REFRESH_COMPLEMENT_PAYLOAD_UNEXPECTED")
    try:
        value = json.loads(match.group(2))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RefreshError("REFRESH_COMPLEMENT_PAYLOAD_INVALID") from error
    if not isinstance(value, dict):
        raise RefreshError("REFRESH_COMPLEMENT_PAYLOAD_INVALID")
    return match, value


def _facts_content(payload: bytes) -> tuple[int, int, bytes]:
    marker = b'<div class="facts">'
    if payload.count(marker) != 1:
        raise RefreshError("REFRESH_COMPLEMENT_FACTS_UNEXPECTED")
    start = payload.index(marker) + len(marker)
    tag = re.compile(br"<div\b|</div>", re.I)
    depth = 1
    for match in tag.finditer(payload, start):
        depth += 1 if match.group(0).lower().startswith(b"<div") else -1
        if depth == 0:
            return start, match.start(), payload[start:match.start()]
    raise RefreshError("REFRESH_COMPLEMENT_FACTS_UNEXPECTED")


def _parse_integer_fact(value: bytes) -> int:
    compact = value.decode("utf-8").replace(",", "").replace("\u202f", "")
    if not compact.isdigit():
        raise RefreshError("REFRESH_COMPLEMENT_FACTS_INVALID")
    return int(compact)


def _candidate_fact_values(kind: str, candidate: bytes, value: object) -> tuple[bytes, ...]:
    if not isinstance(value, dict):
        raise RefreshError("REFRESH_COMPLEMENT_PAYLOAD_INVALID")
    _, _, content = _facts_content(candidate)
    strong = list(_STRONG.finditer(content))
    if len(strong) != 4:
        raise RefreshError("REFRESH_COMPLEMENT_FACTS_UNEXPECTED")
    facts = tuple(match.group(2) for match in strong)
    if kind == "explorer":
        times, series = value.get("times"), value.get("series")
        if not isinstance(times, list) or not isinstance(series, list):
            raise RefreshError("REFRESH_COMPLEMENT_SCHEMA_UNEXPECTED")
        if (
            _parse_integer_fact(facts[0]) != len(series)
            or _parse_integer_fact(facts[1]) != len(times)
            or _parse_integer_fact(facts[2]) < 0
            or facts[3].decode("utf-8") != value.get("offset")
        ):
            raise RefreshError("REFRESH_COMPLEMENT_FACTS_DIVERGED")
        return facts
    completeness, gaps, overlaps = value.get("completeness"), value.get("gaps"), value.get("overlaps")
    if not isinstance(completeness, list) or not isinstance(gaps, list) or not isinstance(overlaps, list):
        raise RefreshError("REFRESH_COMPLEMENT_SCHEMA_UNEXPECTED")
    timestamps = max(
        (item.get("count", 0) for item in completeness if isinstance(item, dict)),
        default=0,
    )
    if (
        _parse_integer_fact(facts[0]) != timestamps
        or _parse_integer_fact(facts[1]) != len(completeness)
        or _parse_integer_fact(facts[2]) != len(gaps)
        or _parse_integer_fact(facts[3]) < 0
    ):
        raise RefreshError("REFRESH_COMPLEMENT_FACTS_DIVERGED")
    return facts


def refresh_complement(active: bytes, candidate: bytes, kind: str) -> bytes:
    active_match, _ = _payload(active)
    candidate_match, value = _payload(candidate)
    # The candidate is intentionally never used as a presentation source.
    facts_start, facts_end, facts_content = _facts_content(active)
    values = _candidate_fact_values(kind, candidate, value)
    strong = list(_STRONG.finditer(facts_content))
    if len(strong) != 4:
        raise RefreshError("REFRESH_COMPLEMENT_FACTS_UNEXPECTED")
    replacement = facts_content
    for match, number in reversed(list(zip(strong, values))):
        replacement = replacement[:match.start(2)] + number + replacement[match.end(2):]
    result = _replace_span(active, active_match, candidate_match.group(2))
    # Payload replacement may change byte offsets, so locate the active facts again.
    facts_start, facts_end, _ = _facts_content(result)
    return result[:facts_start] + replacement + result[facts_end:]


def _json_assignment(payload: bytes, variable: bytes) -> tuple[object, int, int]:
    marker = b"const " + variable + b" = "
    if payload.count(marker) != 1:
        raise RefreshError("REFRESH_MANUAL_ASSIGNMENT_UNEXPECTED")
    start = payload.index(marker) + len(marker)
    try:
        value, consumed = json.JSONDecoder().raw_decode(payload[start:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RefreshError("REFRESH_MANUAL_ASSIGNMENT_INVALID") from error
    encoded = payload[start:].decode("utf-8")
    end = start + len(encoded[:consumed].encode("utf-8"))
    if payload[end:end + 1] != b";":
        raise RefreshError("REFRESH_MANUAL_ASSIGNMENT_INVALID")
    return value, start, end


def _normalise_manual_trace(data: object, name: str) -> object:
    if not isinstance(data, list):
        raise RefreshError("REFRESH_MANUAL_DATA_INVALID")
    matches = [item for item in data if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1 or matches[0].get("mode") != "markers":
        raise RefreshError("REFRESH_MANUAL_SOURCE_TRACE_INVALID")
    normalised = json.loads(json.dumps(data))
    match = next(item for item in normalised if item.get("name") == name)
    match["x"] = ["__SOURCE_DATES__"]
    match["y"] = ["__SOURCE_VALUES__"]
    return normalised


def _normalise_manual_layout(layout: object) -> object:
    if not isinstance(layout, dict) or not isinstance(layout.get("xaxis"), dict):
        raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID")
    normalised = json.loads(json.dumps(layout))
    if "range" not in normalised["xaxis"]:
        raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID")
    normalised["xaxis"]["range"] = ["__PRIMARY_RANGE__"]
    return normalised


def _recent_layout_assignments(payload: bytes) -> tuple[list[object], list[tuple[int, int]]]:
    marker = b"const layouts = {"
    if payload.count(marker) != 1:
        raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID")
    cursor = payload.index(marker) + len(marker)
    values: list[object] = []
    spans: list[tuple[int, int]] = []
    for index, mode in enumerate((b"desktop", b"tablet", b"mobile")):
        prefix = mode + b":"
        if not payload.startswith(prefix, cursor):
            raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID")
        start = cursor + len(prefix)
        try:
            text = payload[start:].decode("utf-8")
            value, consumed = json.JSONDecoder().raw_decode(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID") from error
        end = start + len(text[:consumed].encode("utf-8"))
        values.append(_normalise_manual_layout(value))
        spans.append((start, end))
        cursor = end
        expected = b"," if index < 2 else b"};"
        if not payload.startswith(expected, cursor):
            raise RefreshError("REFRESH_MANUAL_LAYOUT_INVALID")
        cursor += len(expected)
    return values, spans


def manual_data_only_skeleton(payload: bytes) -> bytes:
    """Mask only source points, their count, and the primary temporal extent."""
    if b"const data = " in payload and b"const layouts = {" in payload:
        data, start, end = _json_assignment(payload, b"data")
        replacements = [(start, end, _canonical_json(_normalise_manual_trace(data, "Mesures récentes")))]
        layouts, spans = _recent_layout_assignments(payload)
        replacements.extend(
            (span[0], span[1], _canonical_json(layout))
            for layout, span in zip(layouts, spans, strict=True)
        )
    elif b"const payload = " in payload:
        value, start, end = _json_assignment(payload, b"payload")
        if not isinstance(value, dict) or set(value.get("layouts", {})) != {
            "desktop", "tablet", "mobile"
        }:
            raise RefreshError("REFRESH_MANUAL_PAYLOAD_INVALID")
        normalised = json.loads(json.dumps(value))
        normalised["data"] = _normalise_manual_trace(
            normalised.get("data"), "Mesures manuelles"
        )
        normalised["layouts"] = {
            mode: _normalise_manual_layout(layout)
            for mode, layout in normalised["layouts"].items()
        }
        replacements = [(start, end, _canonical_json(normalised))]
    else:
        raise RefreshError("REFRESH_MANUAL_TEMPLATE_UNEXPECTED")
    for start, end, replacement in sorted(replacements, reverse=True):
        payload = payload[:start] + replacement + payload[end:]
    return _MEASURE_COUNT.sub(b"__COUNT__", payload)


def refresh_manual(active: bytes, refreshed: bytes) -> bytes:
    if manual_data_only_skeleton(active) != manual_data_only_skeleton(refreshed):
        raise RefreshError("REFRESH_MANUAL_SKELETON_DIVERGED")
    return refreshed


def _ready_updates(
    roots: Iterable[Path],
) -> tuple[dict[str, bytes], bytes | None]:
    found: dict[str, bytes] = {}
    processed_patch: bytes | None = None
    for root in roots:
        inventory = _verified_ready_files(Path(root))
        inventory_patterns = PATTERN_TARGETS.intersection(inventory.files)
        if inventory_patterns:
            if inventory_patterns != PATTERN_TARGETS:
                raise RefreshError("REFRESH_PATTERN_PAIR_INCOMPLETE")
            if any(
                inventory.files[name].role != PATTERN_ROLES[name]
                for name in PATTERN_TARGETS
            ):
                raise RefreshError("REFRESH_PATTERN_ROLE_INVALID")
        for relative, entry in inventory.files.items():
            if PurePosixPath(relative).suffix.lower() in {".html", ".htm"}:
                if relative in found:
                    raise RefreshError("REFRESH_READY_CANDIDATE_AMBIGUOUS")
                found[relative] = entry.payload
            elif relative == PROCESSED_PATCH:
                if processed_patch is not None:
                    raise RefreshError("REFRESH_READY_CANDIDATE_AMBIGUOUS")
                processed_patch = entry.payload
    return found, processed_patch


def ready_payloads(roots: Iterable[Path]) -> dict[str, bytes]:
    found, _ = _ready_updates(roots)
    return found


def build_staging(active_root: Path, ready_roots: Iterable[Path], *, manual: Mapping[str, bytes] | None = None) -> dict[PurePosixPath, bytes]:
    """Return every approved replacement, or fail before returning any mapping."""
    active_root = Path(active_root)
    candidates, processed_patch = _ready_updates(ready_roots)
    staged: dict[PurePosixPath, bytes] = {}
    pattern_candidates = PATTERN_TARGETS.intersection(candidates)
    if pattern_candidates and pattern_candidates != PATTERN_TARGETS:
        raise RefreshError("REFRESH_PATTERN_PAIR_INCOMPLETE")
    if pattern_candidates:
        active_patterns = {
            name: (active_root / FIGURES / name).read_bytes()
            for name in PATTERN_TARGETS
        }
        refreshed_patterns = refresh_pattern_pair(
            active_patterns,
            {name: candidates[name] for name in PATTERN_TARGETS},
        )
        for name, payload in refreshed_patterns.items():
            staged[FIGURES / name] = payload
    for name in LEGACY:
        source = f"weather/legacy/{name}"
        if source in candidates:
            relative = FIGURES / source
            target = active_root.joinpath(*relative.parts)
            staged[relative] = refresh_legacy(target.read_bytes(), candidates[source])
    raw_source = "retaining-wall-sensor-raw.html"
    if raw_source in candidates:
        relative = FIGURES / "retaining-wall-sensor-source-values.html"
        target = active_root.joinpath(*relative.parts)
        staged[relative] = refresh_raw(target.read_bytes(), candidates[raw_source])
    if processed_patch is not None:
        relative = FIGURES / PROCESSED_TARGET
        target = active_root.joinpath(*relative.parts)
        staged[relative] = refresh_processed(target.read_bytes(), processed_patch)
    for name, kind in (("meteo_explorateur_toutes_mesures.html", "explorer"), ("meteo_qualite_acquisition.html", "quality")):
        source = f"complements/{name}"
        if source in candidates:
            relative = FIGURES / "weather" / source
            target = active_root.joinpath(*relative.parts)
            staged[relative] = refresh_complement(target.read_bytes(), candidates[source], kind)
    for relative, payload in (manual or {}).items():
        if relative not in {"fissure-recente-meme-format.html", "joint-dilatation-rendu-site.html"}:
            raise RefreshError("REFRESH_MANUAL_TARGET_UNEXPECTED")
        target_relative = FIGURES / relative
        target = active_root.joinpath(*target_relative.parts)
        staged[target_relative] = refresh_manual(target.read_bytes(), payload)
    return staged


def apply_staging(staged: Mapping[PurePosixPath, bytes], staging_root: Path) -> None:
    """Write a separate staging tree; this never overwrites an active master."""
    staging_root = Path(staging_root)
    for relative, payload in staged.items():
        destination = staging_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-root", action="append", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()
    staged = build_staging(SITE_ROOT, args.ready_root)
    apply_staging(staged, args.staging)
    print(f"STAGED {len(staged)} data-only masters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
