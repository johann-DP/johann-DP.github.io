#!/usr/bin/env python3
"""Import an approved Demo 2 bundle as an inactive, create-only site release."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from typing import Any, Iterable, Mapping


SITE_ROOT = Path(__file__).resolve().parents[1]
DESTINATION_RELATIVE = PurePosixPath("assets/validated-releases/demo-2")
CONTENT_MANIFEST_PATH = "content-manifest.json"
APPROVAL_PATH = "validation-approval.json"
ATTESTATION_PATH = "source-release-attestation.json"
SOURCE_MANIFEST_PATH = "source-review-content-manifest.json"
SOURCE_GATE_PATH = "source-review-gate.json"
FORBIDDEN_METADATA = {
    SOURCE_MANIFEST_PATH,
    SOURCE_GATE_PATH,
    "extraction-manifest.json",
    "reconstruction-manifest.json",
    "review-required.json",
    "source-generation-manifest.json",
}
READY_PATH = ".READY"
READY_PENDING_PATH = ".READY.pending"
READY_CONTENT = b"atomic-directory-publication-v1\n"
HASH_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
APPROVAL_ID_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}", flags=re.ASCII)
APPROVER_PATTERN = re.compile(r"[^\x00-\x1f\x7f]{1,80}", flags=re.ASCII)
UTC_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
    flags=re.ASCII,
)
FORBIDDEN_PUBLIC_MARKERS = (
    b"http://",
    b"https://",
    b"file://",
    b"/home/jo",
    b"/media/jo",
    b"nvme_gen",
    b".xlsx",
    b".xls",
    b".csv",
    b".parquet",
)


class SiteReleaseImportError(RuntimeError):
    """Stable failure raised before an inactive release can be trusted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> SiteReleaseImportError:
    return SiteReleaseImportError(code)


@dataclass(frozen=True)
class ReleaseRule:
    logical_paths: Mapping[str, str]
    dependency_paths: tuple[str, ...]


@dataclass(frozen=True)
class SourceModeProfile:
    root: int
    directory: int
    file: int
    ready: int


ATOMIC_SOURCE_MODES = SourceModeProfile(0o700, 0o500, 0o400, 0o444)
GIT_CHECKOUT_SOURCE_MODES = SourceModeProfile(0o755, 0o755, 0o644, 0o644)


PLOTLY = "weather/assets/plotly-2.35.2.min.js"
PLOTLY_LICENSE = f"{PLOTLY}.LICENSE.txt"
WEATHER_PLOTLY = "assets/plotly-2.35.2.min.js"
WEATHER_PLOTLY_LICENSE = f"{WEATHER_PLOTLY}.LICENSE.txt"


def legacy_weather_rule(logical_figure_id: str, html_path: str) -> ReleaseRule:
    return ReleaseRule(
        logical_paths={logical_figure_id: html_path},
        dependency_paths=(PLOTLY, PLOTLY_LICENSE),
    )


RELEASE_RULES: dict[str, ReleaseRule] = {
    "manual_measurement_review": ReleaseRule(
        logical_paths={
            "crack-recent": "recent-cracks-raw.html",
            "expansion-joint": "road-expansion-joint-raw.html",
        },
        dependency_paths=(PLOTLY, PLOTLY_LICENSE),
    ),
    "retaining_wall_sensor_review": ReleaseRule(
        logical_paths={
            "retaining-wall-source-values": "retaining-wall-sensor-raw.html",
        },
        dependency_paths=(PLOTLY, PLOTLY_LICENSE),
    ),
    "weather_complement_review": ReleaseRule(
        logical_paths={
            "weather-explorer": "complements/meteo_explorateur_toutes_mesures.html",
            "weather-quality": "complements/meteo_qualite_acquisition.html",
        },
        dependency_paths=(WEATHER_PLOTLY, WEATHER_PLOTLY_LICENSE),
    ),
    "weather_legacy_temperature_review": legacy_weather_rule(
        "weather-temperature",
        "weather/legacy/meteo_temperature.html",
    ),
    "weather_legacy_minmax_review": legacy_weather_rule(
        "weather-temperature-range",
        "weather/legacy/meteo_temp_minmax.html",
    ),
    "weather_legacy_humidity_review": legacy_weather_rule(
        "weather-humidity",
        "weather/legacy/meteo_humidity.html",
    ),
    "weather_legacy_light_uv_review": legacy_weather_rule(
        "weather-light",
        "weather/legacy/meteo_light_uv.html",
    ),
    "weather_legacy_precipitation_review": legacy_weather_rule(
        "weather-rainfall",
        "weather/legacy/meteo_precipitation.html",
    ),
    "weather_legacy_wind_speed_review": legacy_weather_rule(
        "weather-wind-speed",
        "weather/legacy/meteo_wind_speed.html",
    ),
    "weather_legacy_wind_direction_review": legacy_weather_rule(
        "weather-wind-direction",
        "weather/legacy/meteo_wind_dir.html",
    ),
    "weather_legacy_pairplots_review": legacy_weather_rule(
        "weather-pairplots",
        "weather/legacy/meteo_pairplots.html",
    ),
}

VALIDATION = {
    "automatic_site_publication_permitted": False,
    "decision": "VALIDÉ",
    "scientific_interpretation": "NOT_CLAIMED",
    "scope": "GRAPHICAL_PUBLICATION_ONLY",
}


@dataclass(frozen=True)
class VerifiedSourceBundle:
    promotion_id: str
    payloads: Mapping[str, bytes]
    manifest: bytes


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any] | list[Any]) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise _fail("SITE_RELEASE_JSON_INVALID") from None
    return f"{rendered}\n".encode()


def _canonical_json(payload: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail(code) from None
    if not isinstance(value, dict) or _canonical_json_bytes(value) != payload:
        raise _fail(code)
    return value


def _safe_relative(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise _fail(code)
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _fail(code)
    return value


def _expect_keys(value: object, expected: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise _fail(code)
    return value


def _hash_value(value: object, code: str) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise _fail(code)
    return value


def _file_record(value: object, code: str) -> dict[str, Any]:
    record = _expect_keys(value, {"path", "role", "sha256", "size_bytes"}, code)
    path = _safe_relative(record["path"], code)
    role = record["role"]
    digest = _hash_value(record["sha256"], code)
    size = record["size_bytes"]
    if not isinstance(role, str) or type(size) is not int or size < 0:
        raise _fail(code)
    return {"path": path, "role": role, "sha256": digest, "size_bytes": size}


def _file_records(value: object, code: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise _fail(code)
    records: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for raw in value:
        record = _file_record(raw, code)
        path = record["path"]
        if path in records or path in {CONTENT_MANIFEST_PATH, READY_PATH}:
            raise _fail(code)
        records[path] = record
        ordered.append(path)
    if ordered != sorted(ordered):
        raise _fail(code)
    return records


def _read_stable_regular(path: Path, mode: int, code: str) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise _fail(code) from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != mode
        ):
            raise _fail(code)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        payload = b"".join(chunks)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(payload) != before.st_size:
            raise _fail(code)
        return payload
    finally:
        os.close(descriptor)


def _inventory(
    root: Path,
    root_mode: int,
    directory_mode: int,
    file_mode: int,
    *,
    ready_mode: int = 0o444,
) -> set[str]:
    try:
        root_stat = root.lstat()
    except OSError:
        raise _fail("SITE_RELEASE_TREE_INVALID") from None
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != root_mode
    ):
        raise _fail("SITE_RELEASE_TREE_INVALID")

    found: set[str] = set()

    def visit(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            raise _fail("SITE_RELEASE_TREE_INVALID") from None
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            if relative in found:
                raise _fail("SITE_RELEASE_TREE_INVALID")
            found.add(relative)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                raise _fail("SITE_RELEASE_TREE_INVALID") from None
            if stat.S_ISLNK(metadata.st_mode):
                raise _fail("SITE_RELEASE_TREE_INVALID")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != directory_mode:
                    raise _fail("SITE_RELEASE_TREE_INVALID")
                visit(Path(entry.path))
            elif (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != file_mode
            ):
                if relative == READY_PATH and (
                    stat.S_ISREG(metadata.st_mode)
                    and metadata.st_nlink == 1
                    and stat.S_IMODE(metadata.st_mode) == ready_mode
                ):
                    continue
                raise _fail("SITE_RELEASE_TREE_INVALID")

    visit(root)
    return found


def _expected_descendants(files: set[str]) -> set[str]:
    expected = set(files)
    for value in files:
        for parent in PurePosixPath(value).parents:
            if parent.as_posix() != ".":
                expected.add(parent.as_posix())
    return expected


def _parse_approval(payload: bytes) -> tuple[dict[str, Any], ReleaseRule]:
    approval = _canonical_json(payload, "SITE_RELEASE_APPROVAL_INVALID")
    _expect_keys(
        approval,
        {
            "schema_version",
            "approval_id",
            "decision",
            "validation_scope",
            "scientific_interpretation",
            "approved_by",
            "approved_at_utc",
            "source",
            "selected_figures",
            "publication",
        },
        "SITE_RELEASE_APPROVAL_INVALID",
    )
    if (
        type(approval["schema_version"]) is not int
        or approval["schema_version"] != 1
        or approval["decision"] != "VALIDÉ"
        or approval["validation_scope"] != "GRAPHICAL_PUBLICATION_ONLY"
        or approval["scientific_interpretation"] != "NOT_CLAIMED"
        or not isinstance(approval["approval_id"], str)
        or APPROVAL_ID_PATTERN.fullmatch(approval["approval_id"]) is None
        or not isinstance(approval["approved_by"], str)
        or APPROVER_PATTERN.fullmatch(approval["approved_by"]) is None
        or not isinstance(approval["approved_at_utc"], str)
        or UTC_TIMESTAMP_PATTERN.fullmatch(approval["approved_at_utc"]) is None
    ):
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    try:
        datetime.strptime(approval["approved_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise _fail("SITE_RELEASE_APPROVAL_INVALID") from None

    source = _expect_keys(
        approval["source"],
        {
            "release_kind",
            "release_id",
            "content_manifest_sha256",
            "review_gate_sha256",
        },
        "SITE_RELEASE_APPROVAL_INVALID",
    )
    release_kind = source["release_kind"]
    rule = RELEASE_RULES.get(release_kind) if isinstance(release_kind, str) else None
    if rule is None:
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    for key in ("release_id", "content_manifest_sha256", "review_gate_sha256"):
        _hash_value(source[key], "SITE_RELEASE_APPROVAL_INVALID")

    publication = _expect_keys(
        approval["publication"],
        {
            "preserve_current_validated_masters",
            "automatic_site_publication_permitted",
            "expected_current_manifest_sha256",
        },
        "SITE_RELEASE_APPROVAL_INVALID",
    )
    if (
        publication["preserve_current_validated_masters"] is not True
        or publication["automatic_site_publication_permitted"] is not False
    ):
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    _hash_value(
        publication["expected_current_manifest_sha256"],
        "SITE_RELEASE_APPROVAL_INVALID",
    )

    selected = approval["selected_figures"]
    if not isinstance(selected, list) or not 1 <= len(selected) <= 2:
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    pairs: list[tuple[str, str]] = []
    for raw in selected:
        item = _expect_keys(
            raw,
            {"logical_figure_id", "release_path", "sha256", "size_bytes"},
            "SITE_RELEASE_APPROVAL_INVALID",
        )
        logical_id = item["logical_figure_id"]
        release_path = _safe_relative(
            item["release_path"], "SITE_RELEASE_APPROVAL_INVALID"
        )
        digest = _hash_value(item["sha256"], "SITE_RELEASE_APPROVAL_INVALID")
        size = item["size_bytes"]
        if (
            not isinstance(logical_id, str)
            or rule.logical_paths.get(logical_id) != release_path
            or type(size) is not int
            or size < 1
            or not digest
        ):
            raise _fail("SITE_RELEASE_APPROVAL_INVALID")
        pairs.append((logical_id, release_path))
    if len(set(pairs)) != len(pairs):
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    if len({logical_id for logical_id, _ in pairs}) != len(pairs):
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    if len({path for _, path in pairs}) != len(pairs):
        raise _fail("SITE_RELEASE_APPROVAL_INVALID")
    return approval, rule


def _source_attestation(
    approval: Mapping[str, Any], approval_sha256: str
) -> dict[str, Any]:
    source = approval["source"]
    return {
        "approval_id": approval["approval_id"],
        "approval_sha256": approval_sha256,
        "candidate_status_before_approval": "EXÉCUTÉ_NON_VALIDÉ",
        "content_manifest_sha256": source["content_manifest_sha256"],
        "release_id": source["release_id"],
        "release_kind": source["release_kind"],
        "review_gate_sha256": source["review_gate_sha256"],
        "scientific_interpretation": "NOT_CLAIMED",
        "validation_scope": "GRAPHICAL_PUBLICATION_ONLY",
    }


def _attested_approval_sha256(
    payload: bytes,
    approval: Mapping[str, Any],
    code: str,
) -> str:
    attestation = _canonical_json(payload, code)
    approval_sha256 = _hash_value(attestation.get("approval_sha256"), code)
    if attestation != _source_attestation(approval, approval_sha256):
        raise _fail(code)
    return approval_sha256


def _validate_public_html(
    selected: list[dict[str, Any]], payloads: Mapping[str, bytes]
) -> None:
    for item in selected:
        payload = payloads[item["release_path"]]
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            raise _fail("SITE_RELEASE_HTML_INVALID") from None
        lowered = payload.lower()
        if not lowered.startswith(b"<!doctype html>") or any(
            marker in lowered for marker in FORBIDDEN_PUBLIC_MARKERS
        ):
            raise _fail("SITE_RELEASE_HTML_INVALID")


def _source_mode_profile(root: Path) -> SourceModeProfile:
    try:
        mode = stat.S_IMODE(root.lstat().st_mode)
    except OSError:
        raise _fail("SITE_RELEASE_TREE_INVALID") from None
    if mode == ATOMIC_SOURCE_MODES.root:
        return ATOMIC_SOURCE_MODES
    if mode == GIT_CHECKOUT_SOURCE_MODES.root:
        return GIT_CHECKOUT_SOURCE_MODES
    raise _fail("SITE_RELEASE_TREE_INVALID")


def _verify_source_bundle(bundle_root: Path) -> VerifiedSourceBundle:
    absolute = Path(os.path.abspath(bundle_root))
    try:
        root = absolute.resolve(strict=True)
    except OSError:
        raise _fail("SITE_RELEASE_SOURCE_INVALID") from None
    if (
        absolute != root
        or HASH_PATTERN.fullmatch(root.name) is None
        or root.is_symlink()
    ):
        raise _fail("SITE_RELEASE_SOURCE_INVALID")

    modes = _source_mode_profile(root)
    observed = _inventory(
        root,
        modes.root,
        modes.directory,
        modes.file,
        ready_mode=modes.ready,
    )
    manifest_payload = _read_stable_regular(
        root / CONTENT_MANIFEST_PATH,
        modes.file,
        "SITE_RELEASE_MANIFEST_INVALID",
    )
    manifest = _canonical_json(manifest_payload, "SITE_RELEASE_MANIFEST_INVALID")
    _expect_keys(
        manifest,
        {"files", "manifest_version", "promotion_id", "source", "validation"},
        "SITE_RELEASE_MANIFEST_INVALID",
    )
    if (
        type(manifest["manifest_version"]) is not int
        or manifest["manifest_version"] != 1
        or manifest["promotion_id"] != root.name
        or manifest["validation"] != VALIDATION
    ):
        raise _fail("SITE_RELEASE_MANIFEST_INVALID")
    records = _file_records(manifest["files"], "SITE_RELEASE_MANIFEST_INVALID")
    expected_tree = _expected_descendants(
        set(records) | {CONTENT_MANIFEST_PATH, READY_PATH}
    )
    if observed != expected_tree:
        raise _fail("SITE_RELEASE_INVENTORY_DIVERGED")
    if (
        _read_stable_regular(
            root / READY_PATH,
            modes.ready,
            "SITE_RELEASE_READY_INVALID",
        )
        != READY_CONTENT
    ):
        raise _fail("SITE_RELEASE_READY_INVALID")

    payloads: dict[str, bytes] = {}
    for relative, record in records.items():
        payload = _read_stable_regular(
            root.joinpath(*PurePosixPath(relative).parts),
            modes.file,
            "SITE_RELEASE_FILE_INVALID",
        )
        if len(payload) != record["size_bytes"] or _sha256(payload) != record["sha256"]:
            raise _fail("SITE_RELEASE_FILE_DIVERGED")
        payloads[relative] = payload

    if not {APPROVAL_PATH, ATTESTATION_PATH} <= set(
        payloads
    ) or FORBIDDEN_METADATA & set(payloads):
        raise _fail("SITE_RELEASE_INVENTORY_DIVERGED")
    approval_payload = payloads[APPROVAL_PATH]
    approval, rule = _parse_approval(approval_payload)
    selected = approval["selected_figures"]
    selected_paths = {item["release_path"] for item in selected}
    published_paths = selected_paths | set(rule.dependency_paths)
    expected_roles = {
        **{
            path: "approved_figure" if path in selected_paths else "runtime_dependency"
            for path in published_paths
        },
        APPROVAL_PATH: "human_validation_approval",
        ATTESTATION_PATH: "source_release_attestation",
    }
    if (
        set(records) != set(expected_roles)
        or any(records[path]["role"] != role for path, role in expected_roles.items())
        or any(records[path]["size_bytes"] < 1 for path in published_paths)
    ):
        raise _fail("SITE_RELEASE_INVENTORY_DIVERGED")

    for item in selected:
        record = records[item["release_path"]]
        if (
            record["sha256"] != item["sha256"]
            or record["size_bytes"] != item["size_bytes"]
        ):
            raise _fail("SITE_RELEASE_SELECTION_DIVERGED")
    _validate_public_html(selected, payloads)

    source = approval["source"]
    approval_sha256 = _attested_approval_sha256(
        payloads[ATTESTATION_PATH],
        approval,
        "SITE_RELEASE_SOURCE_ATTESTATION_DIVERGED",
    )

    source_identity = _expect_keys(
        manifest["source"],
        {
            "approval_sha256",
            "canonical_approval_sha256",
            "files",
            "protocol_version",
            "source_content_manifest_sha256",
            "source_release_id",
        },
        "SITE_RELEASE_IDENTITY_INVALID",
    )
    identity_records = _file_records(
        source_identity["files"], "SITE_RELEASE_IDENTITY_INVALID"
    )
    if (
        type(source_identity["protocol_version"]) is not int
        or source_identity["protocol_version"] != 2
        or source_identity["approval_sha256"] != approval_sha256
        or source_identity["canonical_approval_sha256"]
        != _sha256(approval_payload)
        or source_identity["source_content_manifest_sha256"]
        != source["content_manifest_sha256"]
        or source_identity["source_release_id"] != source["release_id"]
        or set(identity_records) != published_paths
        or any(identity_records[path] != records[path] for path in published_paths)
        or _sha256(_canonical_json_bytes(source_identity)) != root.name
    ):
        raise _fail("SITE_RELEASE_IDENTITY_INVALID")

    if (
        _inventory(
            root,
            modes.root,
            modes.directory,
            modes.file,
            ready_mode=modes.ready,
        )
        != observed
    ):
        raise _fail("SITE_RELEASE_SOURCE_CHANGED")
    return VerifiedSourceBundle(root.name, payloads, manifest_payload)


def _public_bundle(root: Path) -> tuple[bytes, dict[str, bytes]]:
    if HASH_PATTERN.fullmatch(root.name) is None or root.is_symlink():
        raise _fail("SITE_RELEASE_PUBLIC_INVALID")
    observed = _inventory(root, 0o755, 0o755, 0o644, ready_mode=0o644)
    manifest_payload = _read_stable_regular(
        root / CONTENT_MANIFEST_PATH, 0o644, "SITE_RELEASE_PUBLIC_INVALID"
    )
    manifest = _canonical_json(manifest_payload, "SITE_RELEASE_PUBLIC_INVALID")
    _expect_keys(
        manifest,
        {
            "files",
            "manifest_version",
            "promotion_id",
            "source",
            "validation",
        },
        "SITE_RELEASE_PUBLIC_INVALID",
    )
    if (
        type(manifest["manifest_version"]) is not int
        or manifest["manifest_version"] != 1
        or manifest["promotion_id"] != root.name
        or manifest["validation"] != VALIDATION
    ):
        raise _fail("SITE_RELEASE_PUBLIC_INVALID")
    records = _file_records(manifest["files"], "SITE_RELEASE_PUBLIC_INVALID")
    expected = _expected_descendants(set(records) | {CONTENT_MANIFEST_PATH, READY_PATH})
    if observed != expected:
        raise _fail("SITE_RELEASE_PUBLIC_INVENTORY_DIVERGED")
    if not {APPROVAL_PATH, ATTESTATION_PATH} <= set(
        records
    ) or FORBIDDEN_METADATA & set(records):
        raise _fail("SITE_RELEASE_PUBLIC_INVENTORY_DIVERGED")
    if (
        _read_stable_regular(root / READY_PATH, 0o644, "SITE_RELEASE_PUBLIC_INVALID")
        != READY_CONTENT
    ):
        raise _fail("SITE_RELEASE_PUBLIC_INVALID")

    payloads: dict[str, bytes] = {}
    for relative, record in records.items():
        payload = _read_stable_regular(
            root.joinpath(*PurePosixPath(relative).parts),
            0o644,
            "SITE_RELEASE_PUBLIC_INVALID",
        )
        if len(payload) != record["size_bytes"] or _sha256(payload) != record["sha256"]:
            raise _fail("SITE_RELEASE_PUBLIC_DIVERGED")
        payloads[relative] = payload

    approval_payload = payloads[APPROVAL_PATH]
    approval, rule = _parse_approval(approval_payload)
    selected = approval["selected_figures"]
    selected_paths = {item["release_path"] for item in selected}
    expected_roles = {
        **{path: "approved_figure" for path in selected_paths},
        **{path: "runtime_dependency" for path in rule.dependency_paths},
        APPROVAL_PATH: "human_validation_approval",
        ATTESTATION_PATH: "source_release_attestation",
    }
    if (
        set(records) != set(expected_roles)
        or any(records[path]["role"] != role for path, role in expected_roles.items())
        or any(
            records[path]["size_bytes"] < 1
            for path in selected_paths | set(rule.dependency_paths)
        )
    ):
        raise _fail("SITE_RELEASE_PUBLIC_INVENTORY_DIVERGED")

    for item in selected:
        record = records[item["release_path"]]
        if (
            record["sha256"] != item["sha256"]
            or record["size_bytes"] != item["size_bytes"]
        ):
            raise _fail("SITE_RELEASE_PUBLIC_INVALID")
    _validate_public_html(selected, payloads)
    approval_sha256 = _attested_approval_sha256(
        payloads[ATTESTATION_PATH],
        approval,
        "SITE_RELEASE_PUBLIC_INVALID",
    )

    source_identity = _expect_keys(
        manifest["source"],
        {
            "approval_sha256",
            "canonical_approval_sha256",
            "files",
            "protocol_version",
            "source_content_manifest_sha256",
            "source_release_id",
        },
        "SITE_RELEASE_PUBLIC_INVALID",
    )
    identity_records = _file_records(
        source_identity["files"], "SITE_RELEASE_PUBLIC_INVALID"
    )
    published_paths = selected_paths | set(rule.dependency_paths)
    if (
        type(source_identity["protocol_version"]) is not int
        or source_identity["protocol_version"] != 2
        or source_identity["approval_sha256"] != approval_sha256
        or source_identity["canonical_approval_sha256"]
        != _sha256(approval_payload)
        or source_identity["source_content_manifest_sha256"]
        != approval["source"]["content_manifest_sha256"]
        or source_identity["source_release_id"] != approval["source"]["release_id"]
        or set(identity_records) != published_paths
        or any(identity_records[path] != records[path] for path in published_paths)
        or _sha256(_canonical_json_bytes(source_identity)) != root.name
    ):
        raise _fail("SITE_RELEASE_PUBLIC_INVALID")
    return manifest_payload, payloads


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _write_exclusive(path: Path, payload: bytes, final_mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, final_mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise _fail("SITE_RELEASE_RENAME_NOREPLACE_UNAVAILABLE") from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), destination)
        raise OSError(error_number, os.strerror(error_number), destination)


def _ready_name_visible(destination: Path) -> bool:
    try:
        destination.joinpath(READY_PATH).lstat()
    except OSError:
        return False
    return True


def _site_root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        resolved = absolute.resolve(strict=True)
    except OSError:
        raise _fail("SITE_RELEASE_SITE_ROOT_INVALID") from None
    if absolute != resolved or not resolved.is_dir() or resolved.is_symlink():
        raise _fail("SITE_RELEASE_SITE_ROOT_INVALID")
    return resolved


def _destination_collection(site_root: Path) -> Path:
    collection = site_root.joinpath(*DESTINATION_RELATIVE.parts)
    current = site_root
    for part in DESTINATION_RELATIVE.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            try:
                metadata = current.lstat()
            except OSError:
                raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID") from None
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o755
            ):
                raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID")
        else:
            try:
                current.mkdir(mode=0o755)
            except FileExistsError:
                try:
                    metadata = current.lstat()
                except OSError:
                    raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID") from None
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o755
                ):
                    raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID")
            else:
                os.chmod(current, 0o755, follow_symlinks=False)
                _fsync_directory(current.parent)
    if collection.resolve() != collection:
        raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID")
    return collection


def _verify_expected_destination(
    destination: Path,
    expected_manifest: bytes,
    expected_payloads: Mapping[str, bytes],
) -> None:
    try:
        manifest, payloads = _public_bundle(destination)
    except SiteReleaseImportError as error:
        raise _fail("SITE_RELEASE_DESTINATION_DIVERGED") from error
    if manifest != expected_manifest or payloads != expected_payloads:
        raise _fail("SITE_RELEASE_DESTINATION_DIVERGED")


def _create_destination(
    destination: Path,
    manifest: bytes,
    payloads: Mapping[str, bytes],
) -> str:
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        _verify_expected_destination(destination, manifest, payloads)
        return "ALREADY_PRESENT"
    except OSError:
        raise _fail("SITE_RELEASE_DESTINATION_CREATE_FAILED") from None

    ready_visible = False
    try:
        for relative, payload in sorted(
            {**payloads, CONTENT_MANIFEST_PATH: manifest}.items()
        ):
            path = destination.joinpath(*PurePosixPath(relative).parts)
            missing: list[Path] = []
            parent = path.parent
            while parent != destination and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700)
            _write_exclusive(path, payload, 0o644)

        directories = sorted(
            (path for path in destination.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            os.chmod(directory, 0o755, follow_symlinks=False)
            _fsync_directory(directory)
        os.chmod(destination, 0o755, follow_symlinks=False)
        _fsync_directory(destination)
        pending = destination / READY_PENDING_PATH
        _write_exclusive(pending, READY_CONTENT, 0o644)
        _fsync_directory(destination)
        _rename_noreplace(pending, destination / READY_PATH)
        ready_visible = True
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
    except Exception as error:
        ready_visible = ready_visible or _ready_name_visible(destination)
        if not ready_visible:
            try:
                os.chmod(destination, 0o700, follow_symlinks=False)
                for path in destination.rglob("*"):
                    if path.is_dir():
                        os.chmod(path, 0o700, follow_symlinks=False)
                shutil.rmtree(destination)
            except OSError:
                pass
        if isinstance(error, SiteReleaseImportError):
            raise
        raise _fail("SITE_RELEASE_DESTINATION_CREATE_FAILED") from error

    _verify_expected_destination(destination, manifest, payloads)
    return "CREATED"


def import_validated_release(
    source_bundle: Path,
    *,
    site_root: Path = SITE_ROOT,
) -> dict[str, object]:
    """Verify and create one inactive public bundle without changing active paths."""

    verified = _verify_source_bundle(source_bundle)
    root = _site_root(site_root)
    collection = _destination_collection(root)
    destination = collection / verified.promotion_id
    status = _create_destination(
        destination,
        verified.manifest,
        verified.payloads,
    )
    return {
        "content_manifest_sha256": _sha256(verified.manifest),
        "promotion_id": verified.promotion_id,
        "published_file_count": len(verified.payloads),
        "state": "IMPORTED_INACTIVE",
        "status": status,
    }


def verify_imported_releases(*, site_root: Path = SITE_ROOT) -> tuple[str, ...]:
    """Verify every already imported inactive release and reject stray entries."""

    root = _site_root(site_root)
    collection = root.joinpath(*DESTINATION_RELATIVE.parts)
    current = root
    for part in DESTINATION_RELATIVE.parts:
        current = current / part
        if not current.exists() and not current.is_symlink():
            return ()
        try:
            metadata = current.lstat()
        except OSError:
            raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID") from None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o755
        ):
            raise _fail("SITE_RELEASE_DESTINATION_ROOT_INVALID")
    identifiers: list[str] = []
    for entry in sorted(collection.iterdir(), key=lambda path: path.name):
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or HASH_PATTERN.fullmatch(entry.name) is None
        ):
            raise _fail("SITE_RELEASE_PUBLIC_COLLECTION_INVALID")
        _public_bundle(entry)
        identifiers.append(entry.name)
    return tuple(identifiers)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--source-bundle", type=Path)
    action.add_argument("--verify-existing", action="store_true")
    parser.add_argument("--site-root", type=Path, default=SITE_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify_existing:
            identifiers = verify_imported_releases(site_root=args.site_root)
            result: Mapping[str, object] = {
                "promotion_ids": list(identifiers),
                "release_count": len(identifiers),
                "status": "VERIFIED",
            }
        else:
            result = import_validated_release(
                args.source_bundle,
                site_root=args.site_root,
            )
    except SiteReleaseImportError as error:
        print(f"SITE_RELEASE_IMPORT_FAILED: {error.code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
