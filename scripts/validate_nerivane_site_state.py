#!/usr/bin/env python3
"""Validate the two and only two publishable Nérivane site states.

The maintenance baseline is byte-bound to the protected site tree updated as
``96ebe4313c65284b7f86c708015d62df482f9008``.  The active state is accepted
only when its five promoted targets are exactly derivable from one verified,
content-addressed V2 release and its public data obey the complete closed V2
schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Iterable, Mapping

import import_nerivane_v2_release as importer
import promote_nerivane_v2_release as promoter


SITE_ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_STATE = "MAINTENANCE_V1"
ACTIVE_STATE = "ACTIVE_V2"
CATALOGUE_START = b"<!-- NERIVANE_CATALOGUE_CARD_START -->"
CATALOGUE_END = b"<!-- NERIVANE_CATALOGUE_CARD_END -->"
PAGE_RELATIVE = "demonstrations/nerivane-distribution.html"
DATA_RELATIVE = "assets/data/nerivane-governance-replay.json"
SCRIPT_RELATIVE = "assets/js/demo-nerivane.js"
STYLE_RELATIVE = "assets/css/demo-nerivane.css"
CATALOGUE_RELATIVE = "demonstrations.html"
ACTIVE_TARGETS = (
    PAGE_RELATIVE,
    DATA_RELATIVE,
    SCRIPT_RELATIVE,
    STYLE_RELATIVE,
)
PROMOTED_TARGETS = (*ACTIVE_TARGETS, CATALOGUE_RELATIVE)
SITE_FILE_MODE = 0o644
SITE_DIRECTORY_MODE = 0o755
PROTECTED_PATHS = tuple(
    sorted(
        {
            *promoter._protected_paths(),
            "assets/css/demo-ormevia.css",
            "assets/data/ormevia-scenarios.json",
            "assets/js/demo-ormevia.js",
            "contracts/nerivane-v2-site-promotion-v1.json",
            "demonstrations/ormevia-batiment.html",
        }
    )
)
RELEASE_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
ACTIVE_PAGE_RELEASE_PATTERN = re.compile(
    rb'<body\b[^>]*\bdata-release-id="([0-9a-f]{64})"[^>]*>',
    flags=re.IGNORECASE,
)
ACTIVE_CATALOGUE_RELEASE_PATTERN = re.compile(
    rb'data-release="assets/validated-releases/nerivane-v2/([0-9a-f]{64})"',
    flags=re.IGNORECASE,
)
MAINTENANCE_PAGE_MARKER = b'data-maintenance="true"'
ACTIVE_HEADER_MARKER = (
    '<span id="nerivane-public-state" class="nerivane-header__state" '
    'data-status="verification" role="status" aria-live="polite" '
    'aria-busy="true" aria-label="Vérification du replay public en cours">'
    '<span aria-hidden="true">●</span><span data-state-label>Vérification…</span></span>'
).encode("utf-8")
ACTIVE_SEO_MARKERS = (
    '<title>Nérivane Distribution — gouvernance d’un KPI à l’échelle Big Data | datapredict</title>',
    '<meta name="description" content="Explorez une reprise de gouvernance Data étayée par un corpus H1 massif, un lignage contrôlé et un veto IA local fail-closed.">',
    '<link rel="canonical" href="https://www.datapredict.org/demonstrations/nerivane-distribution.html">',
    '<meta property="og:locale" content="fr_FR">',
    '<meta property="og:type" content="website">',
    '<meta property="og:title" content="Nérivane Distribution — gouvernance d’un KPI à l’échelle Big Data | datapredict">',
    '<meta property="og:description" content="Un replay en sept étapes pour examiner une gouvernance Data prouvée à grande échelle et son veto IA fail-closed.">',
    '<meta property="og:url" content="https://www.datapredict.org/demonstrations/nerivane-distribution.html">',
    '<meta property="og:image" content="https://www.datapredict.org/assets/img/social-datapredict.png">',
    '<meta name="twitter:card" content="summary_large_image">',
)

# Exact maintenance/protected baseline at 96ebe431.  The values are populated
# and causally tested below; changing a protected byte requires a deliberate
# review of this contract rather than broadening one of the two states.
DEFAULT_BASELINE: dict[str, Any] = {
    "contract_id": "DATAPREDICT-NERIVANE-SITE-STATES-V1",
    "source_commit": "96ebe4313c65284b7f86c708015d62df482f9008",
    "maintenance_targets": {
        PAGE_RELATIVE: "561362e06e1d7f60bfe875f71dd5cccccd0b766abacd40abdaa45028679215c6",
        DATA_RELATIVE: "1d2e423d11be19e7884c509654264433c32d4d2227f908e764e9689e8152def9",
        SCRIPT_RELATIVE: "7767604e4b392294b487ca0ae523f4fa08f2bc09239d48f5c5bdf577f8556dfe",
        STYLE_RELATIVE: "1a9334a0d4fea1d3062186861c3460cab1af4b07c66072cbe5f7e542c86ce214",
    },
    "maintenance_catalogue_fragment_sha256": "24f984b4ce8bfe678b0dc175331337623fd9c9fae2cde36a900dcd78d69d90f1",
    "catalogue_outside_sha256": "957f81a06a825d09ff2bb61d64ca5c1cef521a1830c01a51b5d791ad321b7c82",
    "protected_snapshot_sha256": "919b6eccc5e66a6bcda146bf80697eb4bde1bb9ceb7b07a855ad171213ae6907",
}


class NerivaneSiteStateError(RuntimeError):
    """Stable fail-closed error for a non-publishable site state."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NerivaneSiteStateError:
    return NerivaneSiteStateError(code)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise _fail("NERIVANE_SITE_STATE_JSON_INVALID") from None
    return f"{rendered}\n".encode("utf-8")


def _root(site_root: Path) -> Path:
    try:
        return importer._site_root(site_root)
    except importer.NerivaneReleaseImportError as error:
        raise _fail("NERIVANE_SITE_ROOT_INVALID") from error


def _read_regular(root: Path, relative: str) -> bytes:
    relative_path = PurePosixPath(relative)
    if (
        relative_path.is_absolute()
        or relative_path.as_posix() != relative
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise _fail("NERIVANE_SITE_PATH_INVALID")
    path = root
    for index, part in enumerate(relative_path.parts):
        path /= part
        try:
            component = path.lstat()
        except OSError:
            raise _fail("NERIVANE_SITE_FILE_INVALID") from None
        is_leaf = index == len(relative_path.parts) - 1
        expected_mode = SITE_FILE_MODE if is_leaf else SITE_DIRECTORY_MODE
        expected_kind = stat.S_ISREG if is_leaf else stat.S_ISDIR
        if (
            stat.S_ISLNK(component.st_mode)
            or not expected_kind(component.st_mode)
            or stat.S_IMODE(component.st_mode) != expected_mode
            or (is_leaf and component.st_nlink != 1)
        ):
            raise _fail("NERIVANE_SITE_PATH_CONTRACT_INVALID")
    try:
        metadata = path.lstat()
    except OSError:
        raise _fail("NERIVANE_SITE_FILE_INVALID") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise _fail("NERIVANE_SITE_FILE_INVALID")
    try:
        return path.read_bytes()
    except OSError:
        raise _fail("NERIVANE_SITE_FILE_INVALID") from None


def _validate_promoted_path_contract(root: Path) -> None:
    """Close modes and symlink ancestry for publication and protected paths."""

    try:
        root_metadata = root.lstat()
    except OSError:
        raise _fail("NERIVANE_SITE_PATH_CONTRACT_INVALID") from None
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != SITE_DIRECTORY_MODE
    ):
        raise _fail("NERIVANE_SITE_PATH_CONTRACT_INVALID")
    for relative in PROMOTED_TARGETS:
        _read_regular(root, relative)
    for relative in PROTECTED_PATHS:
        current = root
        for part in PurePosixPath(relative).parts[:-1]:
            current /= part
            try:
                metadata = current.lstat()
            except OSError:
                raise _fail("NERIVANE_SITE_PATH_CONTRACT_INVALID") from None
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != SITE_DIRECTORY_MODE
            ):
                raise _fail("NERIVANE_SITE_PATH_CONTRACT_INVALID")


def _catalogue_parts(payload: bytes) -> tuple[bytes, bytes, bytes]:
    if payload.count(CATALOGUE_START) != 1 or payload.count(CATALOGUE_END) != 1:
        raise _fail("NERIVANE_CATALOGUE_BOUNDARY_INVALID")
    start = payload.index(CATALOGUE_START)
    end = payload.index(CATALOGUE_END)
    if start >= end:
        raise _fail("NERIVANE_CATALOGUE_BOUNDARY_INVALID")
    fragment_start = start + len(CATALOGUE_START)
    return payload[:start], payload[fragment_start:end], payload[end + len(CATALOGUE_END):]


def _catalogue_outside_sha256(payload: bytes) -> str:
    prefix, _, suffix = _catalogue_parts(payload)
    return _sha256(prefix + b"\x00" + suffix)


def _inventory(path: Path, relative: str) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}

    def visit(current: Path, current_relative: str) -> None:
        try:
            metadata = current.lstat()
        except OSError:
            raise _fail("NERIVANE_PROTECTED_TREE_INVALID") from None
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            raise _fail("NERIVANE_PROTECTED_TREE_INVALID")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise _fail("NERIVANE_PROTECTED_TREE_INVALID")
            try:
                payload = current.read_bytes()
            except OSError:
                raise _fail("NERIVANE_PROTECTED_TREE_INVALID") from None
            result[current_relative] = {
                "kind": "file",
                "mode": mode,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise _fail("NERIVANE_PROTECTED_TREE_INVALID")
        result[current_relative] = {"kind": "directory", "mode": mode}
        try:
            children = sorted(os.scandir(current), key=lambda child: child.name)
        except OSError:
            raise _fail("NERIVANE_PROTECTED_TREE_INVALID") from None
        for child in children:
            visit(Path(child.path), f"{current_relative}/{child.name}")

    visit(path, relative)
    return result


def protected_snapshot_sha256(site_root: Path) -> str:
    root = _root(site_root)
    snapshot: dict[str, dict[str, object]] = {}
    for relative in PROTECTED_PATHS:
        snapshot.update(_inventory(root / relative, relative))
    return _sha256(_canonical(snapshot))


def capture_baseline(site_root: Path) -> dict[str, Any]:
    """Capture one explicit maintenance baseline for causal fixture tests."""

    root = _root(site_root)
    catalogue = _read_regular(root, CATALOGUE_RELATIVE)
    _, fragment, _ = _catalogue_parts(catalogue)
    return {
        "contract_id": "DATAPREDICT-NERIVANE-SITE-STATES-V1",
        "source_commit": "fixture",
        "maintenance_targets": {
            relative: _sha256(_read_regular(root, relative))
            for relative in ACTIVE_TARGETS
        },
        "maintenance_catalogue_fragment_sha256": _sha256(fragment),
        "catalogue_outside_sha256": _catalogue_outside_sha256(catalogue),
        "protected_snapshot_sha256": protected_snapshot_sha256(root),
    }


def _validate_baseline(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "contract_id",
        "source_commit",
        "maintenance_targets",
        "maintenance_catalogue_fragment_sha256",
        "catalogue_outside_sha256",
        "protected_snapshot_sha256",
    }
    targets = value.get("maintenance_targets")
    digests = (
        value.get("maintenance_catalogue_fragment_sha256"),
        value.get("catalogue_outside_sha256"),
        value.get("protected_snapshot_sha256"),
    )
    if (
        set(value) != expected_keys
        or value.get("contract_id") != "DATAPREDICT-NERIVANE-SITE-STATES-V1"
        or not isinstance(targets, dict)
        or set(targets) != set(ACTIVE_TARGETS)
        or any(RELEASE_ID_PATTERN.fullmatch(str(item)) is None for item in targets.values())
        or any(RELEASE_ID_PATTERN.fullmatch(str(item)) is None for item in digests)
    ):
        raise _fail("NERIVANE_SITE_BASELINE_INVALID")


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_object(value: object, fields: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _fail(code)
    return value


def _resolve_release_reference(
    release_root: Path,
    release_id: str,
    href: object,
    expected_relative: str,
) -> Path:
    expected_href = (
        "../assets/validated-releases/nerivane-v2/"
        f"{release_id}/{expected_relative}"
    )
    if href != expected_href:
        raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")
    target = release_root.joinpath(*PurePosixPath(expected_relative).parts)
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(release_root.resolve(strict=True))
    except (OSError, ValueError):
        raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID") from None
    if not resolved.is_file() or resolved.is_symlink():
        raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")
    return resolved


def _evidence_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _fail(code) from None
    if not isinstance(value, dict) or payload != _canonical(value):
        raise _fail(code)
    return value, payload


def _digest_value(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or RELEASE_ID_PATTERN.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise _fail(code)
    return value


def _validate_replay_evidence(
    value: Mapping[str, Any],
    *,
    expected_source_commit: str,
    h1_sha256: str,
    resource_sha256: str,
    ai_sha256: str,
) -> dict[str, str]:
    code = "NERIVANE_ACTIVE_REPLAY_EVIDENCE_INVALID"
    _strict_object(
        value,
        {
            "contract_id", "counts", "evidence", "fictional", "gates",
            "limitations", "publication", "scenario_id", "schema_version",
            "source", "source_bindings", "status", "steps",
        },
        code,
    )
    if (
        value.get("schema_version") != 2
        or value.get("contract_id") != "NERIVANE-PUBLIC-REPLAY-V2"
        or value.get("status") != "SEALED_PUBLIC_REPLAY"
        or value.get("fictional") is not True
        or value.get("scenario_id") != "NERIVANE-KPI-2026-07"
        or value.get("counts") != {
            "assignments": 37, "documents": 28, "people": 26, "roles": 18,
            "sites": 10, "source_systems": 4, "steps": 7,
        }
        or value.get("gates") != {
            "ai_local_fail_closed": "VALIDÉ", "bigquery_h1_sample": "VALIDÉ",
            "full_h1": "VALIDÉ", "public_sanitization": "VALIDÉ",
            "seven_step_replay": "VALIDÉ",
        }
        or value.get("publication") != {
            "automatic_activation_permitted": False,
            "maintenance_removal_permitted": False,
        }
        or value.get("evidence") != {
            "ai_local_fail_closed": "evidence/ai-local-fail-closed.json",
            "bigquery_h1_sample": "evidence/bigquery-h1-sample-public.json",
            "full_h1": "evidence/full-h1-final-public.json",
            "park_resource_windows": "evidence/resource-windows/manifest.json",
        }
        or value.get("steps") != [f"steps/{index:02d}.html" for index in range(1, 8)]
        or value.get("limitations") != [
            "INACTIVE_SITE_IMPORT_ONLY", "NO_AUTOMATIC_ACTIVATION",
            "NO_MAINTENANCE_REMOVAL", "NO_GCP_V2_LOAD_CLAIM_LOCAL_SAMPLE_ONLY",
            "SELECTED_AI_MODEL_REJECTED_NOT_DEPLOYED",
        ]
    ):
        raise _fail(code)
    source = _strict_object(value.get("source"), {"commit", "repository"}, code)
    if source != {
        "commit": expected_source_commit,
        "repository": "johann-DP/datapredict-governed-kpi-demo",
    }:
        raise _fail(code)
    bindings = _strict_object(
        value.get("source_bindings"),
        {
            "ai_fail_closed_overlay_sha256", "full_h1_public_report_sha256",
            "h1_resource_windows_manifest_sha256",
            "full_h1_sample_selection_plan_sha256", "local_36_controls_proof_sha256",
            "local_materialization_proof_sha256", "replay_candidate_v1_tree_sha256",
        },
        code,
    )
    normalized = {key: _digest_value(item, code) for key, item in bindings.items()}
    if (
        normalized["full_h1_public_report_sha256"] != h1_sha256
        or normalized["ai_fail_closed_overlay_sha256"] != ai_sha256
        or normalized["h1_resource_windows_manifest_sha256"] != resource_sha256
    ):
        raise _fail(code)
    return normalized


def _validate_h1_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    code = "NERIVANE_ACTIVE_H1_EVIDENCE_INVALID"
    _strict_object(
        value,
        {
            "contract_id", "durable_storage", "execution", "limitations",
            "period", "proof_scope", "safety", "sanitization", "schema_version",
            "source_bindings", "status", "thresholds",
        },
        code,
    )
    if (
        value.get("schema_version") != 1
        or value.get("contract_id") != "NERIVANE-FULL-H1-FINAL-PUBLIC-EVIDENCE-V1"
        or value.get("status") != "PASS_FULL_H1_1320_DURABLE_TRIPLETS"
        or value.get("proof_scope")
        != "ANCHORED_FINAL_PROOF_1320_RECEIPTS_AND_THREE_ATTESTED_DATA_TIERS"
        or value.get("period") != {
            "start_month": "2021-01", "end_month": "2021-06", "month_count": 6,
        }
        or value.get("limitations") != [
            "NO_KPI_CERTIFICATION_CLAIM", "NO_GCP_V2_LOAD_CLAIM",
            "NO_ARCHIVE_REDUNDANCY_OR_RESTORE_CLAIM",
            "NO_PERFORMANCE_OR_CONCURRENCY_BENCHMARK_CLAIM",
        ]
        or value.get("safety") != {
            "source_deleted_or_modified": False, "automatic_deletion": False,
            "gcp_accessed_or_modified": False, "kpi_claimed_or_certified": False,
            "gpu_used_by_h1_pipeline": False,
        }
    ):
        raise _fail(code)
    sanitization = _strict_object(
        value.get("sanitization"), {"status", "node_identity", "removed_categories"}, code,
    )
    removed = sanitization.get("removed_categories")
    allowed_removed = {
        "FILESYSTEM_PATHS", "HOSTNAMES", "IP_ADDRESSES", "DEVICE_SERIALS",
        "FILESYSTEM_UUIDS", "USER_IDENTITIES", "RECEIPT_LEVEL_DETAILS",
    }
    if (
        sanitization.get("status") != "PASS"
        or sanitization.get("node_identity") != "PSEUDONYMIZED"
        or not isinstance(removed, list)
        or any(not isinstance(item, str) for item in removed)
        or len(removed) != len(set(removed))
        or not {"FILESYSTEM_PATHS", "HOSTNAMES", "USER_IDENTITIES"}.issubset(removed)
        or not set(removed).issubset(allowed_removed)
    ):
        raise _fail(code)
    bindings = _strict_object(
        value.get("source_bindings"),
        {
            "deployed_runtime_sha256", "full_h1_proof_sha256",
            "receipt_anchor_set_sha256", "storage_topology_contract_sha256",
        },
        code,
    )
    normalized_bindings = {
        key: _digest_value(item, code) for key, item in bindings.items()
    }
    execution = _strict_object(
        value.get("execution"),
        {
            "by_node", "file_count", "node_count", "physical_rows",
            "rows_per_layer", "task_count", "triplet_count",
        },
        code,
    )
    if (
        execution.get("node_count") != 4
        or execution.get("triplet_count") != 1_320
        or execution.get("task_count") != 3_960
        or execution.get("rows_per_layer") != 668_121_398
        or execution.get("physical_rows") != 2_004_364_194
        or execution.get("file_count") != 3_960
    ):
        raise _fail(code)
    nodes = _strict_object(
        execution.get("by_node"), {"node-a", "node-b", "node-c", "node-d"}, code,
    )
    totals = {field: 0 for field in ("rows", "encoded_bytes", "allocated_bytes", "file_count")}
    for node in ("node-a", "node-b", "node-c", "node-d"):
        metrics = _strict_object(
            nodes[node],
            {"triplet_count", "task_count", "rows", "encoded_bytes", "allocated_bytes", "file_count"},
            code,
        )
        if (
            metrics.get("triplet_count") != 330
            or metrics.get("task_count") != 990
            or metrics.get("file_count") != 990
            or any(type(metrics.get(field)) is not int or metrics[field] <= 0 for field in ("rows", "encoded_bytes", "allocated_bytes"))
            or metrics["allocated_bytes"] < metrics["encoded_bytes"]
        ):
            raise _fail(code)
        for field in totals:
            totals[field] += metrics[field]
    storage = _strict_object(
        value.get("durable_storage"),
        {"data_tier_count", "distinct_physical_devices_attested", "layers", "total"},
        code,
    )
    if storage.get("data_tier_count") != 3 or storage.get("distinct_physical_devices_attested") != 3:
        raise _fail(code)
    layers = _strict_object(storage.get("layers"), {"RAW", "BRONZE", "SILVER"}, code)
    layer_totals = {field: 0 for field in totals}
    for layer, role, media in (
        ("RAW", "RAW_PRIMARY", "HDD"),
        ("BRONZE", "BRONZE_PRIMARY", "NVME"),
        ("SILVER", "SILVER_PRIMARY", "NVME"),
    ):
        metrics = _strict_object(
            layers[layer],
            {"storage_role", "media_class", "rows", "encoded_bytes", "allocated_bytes", "file_count"},
            code,
        )
        if (
            metrics.get("storage_role") != role
            or metrics.get("media_class") != media
            or metrics.get("rows") != 668_121_398
            or metrics.get("file_count") != 1_320
            or type(metrics.get("encoded_bytes")) is not int
            or metrics["encoded_bytes"] <= 0
            or type(metrics.get("allocated_bytes")) is not int
            or metrics["allocated_bytes"] < metrics["encoded_bytes"]
        ):
            raise _fail(code)
        for field in layer_totals:
            layer_totals[field] += metrics[field]
    total = _strict_object(
        storage.get("total"), {"rows", "encoded_bytes", "allocated_bytes", "file_count"}, code,
    )
    binary_threshold = 3 * (1024**4) // 2
    if (
        type(total.get("encoded_bytes")) is not int
        or total["encoded_bytes"] <= binary_threshold
        or type(total.get("allocated_bytes")) is not int
        or total["allocated_bytes"] < total["encoded_bytes"]
        or total.get("rows") != 2_004_364_194
        or total.get("file_count") != 3_960
        or totals != dict(total)
        or layer_totals != dict(total)
    ):
        raise _fail(code)
    thresholds = _strict_object(
        value.get("thresholds"),
        {
            "allocated_exceeds_binary_1_5_tib", "allocated_exceeds_decimal_1_5_tb",
            "binary_1_5_tib_bytes", "decimal_1_5_tb_bytes",
            "encoded_exceeds_binary_1_5_tib", "encoded_exceeds_decimal_1_5_tb",
        },
        code,
    )
    if thresholds != {
        "allocated_exceeds_binary_1_5_tib": True,
        "allocated_exceeds_decimal_1_5_tb": True,
        "binary_1_5_tib_bytes": binary_threshold,
        "decimal_1_5_tb_bytes": 1_500_000_000_000,
        "encoded_exceeds_binary_1_5_tib": True,
        "encoded_exceeds_decimal_1_5_tb": True,
    }:
        raise _fail(code)
    return {
        "encoded_bytes": total["encoded_bytes"],
        "physical_rows": total["rows"],
        "source_bindings": normalized_bindings,
    }


def _validate_sample_evidence(
    value: Mapping[str, Any],
    *,
    h1: Mapping[str, Any],
    replay_bindings: Mapping[str, str],
) -> None:
    code = "NERIVANE_ACTIVE_SAMPLE_EVIDENCE_INVALID"
    _strict_object(
        value,
        {
            "cloud_boundary", "contract_id", "deterministic_controls",
            "fictional_scenario", "materialization", "period", "publication_boundary",
            "sample_id", "sanitization", "schema_version", "source_bindings", "status",
        },
        code,
    )
    if (
        value.get("schema_version") != 2
        or value.get("contract_id") != "NERIVANE-BIGQUERY-H1-SAMPLE-PUBLIC-EVIDENCE-V2"
        or value.get("status") != "VALIDÉ_LOCAL_H1_SAMPLE_AND_36_CONTROLS"
        or value.get("fictional_scenario") is not True
        or value.get("sample_id") != "NERIVANE-2021-H1-GCP-V2"
        or value.get("period") != {"start_month": "2021-01", "end_month": "2021-06", "month_count": 6}
        or value.get("materialization") != {
            "execution_surface": "LOCAL_ONLY_NO_GCP_ACCESS", "table_count": 17,
            "physical_rows": 210_724, "rows_are_non_round": True,
            "source_scope": "FULL_H1_RECEIPT_BOUND_LOCAL_MATERIALIZATION",
            "pilot_25m_inputs_used": False,
        }
        or value.get("cloud_boundary") != {
            "bigquery_project_mutated": False, "gcp_accessed_or_modified": False,
            "gcp_load_claimed": False,
            "meaning": "L'échantillon au schéma BigQuery a été matérialisé et contrôlé localement; ce paquet ne prétend ni chargement ni mutation GCP.",
        }
        or value.get("publication_boundary") != {
            "kpi_deterministically_certified": True,
            "business_publication_automatically_unblocked": False,
        }
        or value.get("sanitization") != {"status": "PASS", "private_paths_included": False}
    ):
        raise _fail(code)
    controls = _strict_object(
        value.get("deterministic_controls"),
        {"certification_status", "certified_months", "executed", "failed", "measurement_sha256", "passed", "values_are_integer_cents"},
        code,
    )
    if (
        controls.get("executed") != 36
        or controls.get("passed") != 36
        or controls.get("failed") != 0
        or controls.get("certified_months") != 6
        or controls.get("values_are_integer_cents") is not True
        or controls.get("certification_status")
        != "DETERMINISTICALLY_RECONCILED_PUBLICATION_BLOCKED_PENDING_AI_HUMAN"
    ):
        raise _fail(code)
    _digest_value(controls.get("measurement_sha256"), code)
    bindings = _strict_object(
        value.get("source_bindings"),
        {"deterministic_controls_proof_sha256", "full_h1_proof_sha256", "materialization_proof_sha256", "receipt_anchor_set_sha256", "selection_plan_sha256"},
        code,
    )
    normalized = {key: _digest_value(item, code) for key, item in bindings.items()}
    h1_bindings = h1["source_bindings"]
    if (
        normalized["full_h1_proof_sha256"] != h1_bindings["full_h1_proof_sha256"]
        or normalized["receipt_anchor_set_sha256"] != h1_bindings["receipt_anchor_set_sha256"]
        or normalized["selection_plan_sha256"] != replay_bindings["full_h1_sample_selection_plan_sha256"]
        or normalized["materialization_proof_sha256"] != replay_bindings["local_materialization_proof_sha256"]
        or normalized["deterministic_controls_proof_sha256"] != replay_bindings["local_36_controls_proof_sha256"]
    ):
        raise _fail(code)


def _validate_ai_evidence(value: Mapping[str, Any]) -> None:
    code = "NERIVANE_ACTIVE_AI_EVIDENCE_INVALID"
    _strict_object(
        value,
        {
            "artifact_kind", "candidate_veto", "contract", "contract_id", "execution",
            "fail_closed", "fictional_scenario", "model", "publication_decision",
            "publication_gate", "qualification", "safety", "schema_version", "status",
        },
        code,
    )
    if (
        value.get("schema_version") != 1
        or value.get("contract_id") != "NERIVANE-AI-PUBLIC-POST-RUN-OVERLAY-V17R3"
        or value.get("artifact_kind") != "SANITIZED_POST_RUN_QUALIFICATION_OVERLAY"
        or value.get("status") != "REJECTED_BY_QUALIFICATION"
        or value.get("fail_closed") is not True
        or value.get("fictional_scenario") is not True
        or value.get("contract") != {
            "path": "contracts/ai_public_post_run_overlay_v17r3.schema.json",
            "sha256": "a16ab56e4ce98e3ead0475e70f75638a5fc76a96d673c9ca81ebbd07f7e0d83f",
        }
    ):
        raise _fail(code)


    execution = _strict_object(
        value.get("execution"),
        {"candidate_capture", "live_inference_in_public_replay", "policy_id", "policy_sha256", "surface", "validated"},
        code,
    )
    capture = _strict_object(execution.get("candidate_capture"), {"path", "replay_kind", "sha256"}, code)
    if (
        execution.get("validated") is not True
        or execution.get("surface") != "LOCAL_BLACKWELL"
        or execution.get("live_inference_in_public_replay") is not False
        or execution.get("policy_id") != "NERIVANE-AI-LOCAL-EXECUTION-V17R3"
        or _digest_value(execution.get("policy_sha256"), code) != "e031248cb06c01194b0f12872d04b666ce82a1239efb25cc7394f2f8f58b48a4"
        or capture != {
            "path": "candidate-veto-replay.json",
            "replay_kind": "SANITIZED_CAPTURE_NO_LIVE_INFERENCE",
            "sha256": "194f8967c8e56e0cfc8ca31b349c407ee0ca81bd728dd48ebca1063bade174ef",
        }
    ):
        raise _fail(code)
    candidate = _strict_object(
        value.get("candidate_veto"),
        {"effective_finding_count", "effective_verdict", "findings", "kpi_certification_performed", "kpi_computation_performed", "publication_status", "status"},
        code,
    )
    findings = candidate.get("findings")
    if (
        candidate.get("status") != "EXECUTED_CANDIDATE_VETO"
        or candidate.get("effective_verdict") != "BLOCK"
        or candidate.get("effective_finding_count") != 1
        or candidate.get("publication_status") != "BLOCKED"
        or candidate.get("kpi_computation_performed") is not False
        or candidate.get("kpi_certification_performed") is not False
        or not isinstance(findings, list)
        or len(findings) != 1
    ):
        raise _fail(code)
    finding = _strict_object(
        findings[0],
        {"applied_rule_ids", "arbitration_question", "arbitration_question_template_id", "claim", "claim_template_id", "effective_category", "effective_severity", "effective_verdict", "evidence_ids", "finding_id", "materiality_basis"},
        code,
    )
    if (
        finding.get("finding_id") != "F-001"
        or finding.get("effective_category") != "KPI_DEFINITION"
        or finding.get("effective_severity") != "CRITICAL"
        or finding.get("effective_verdict") != "BLOCK"
        or finding.get("materiality_basis") != "CONFLICTING_KPI_POPULATION_OR_CUTOFF"
        or finding.get("applied_rule_ids") != ["MAT6-SEVERITY-KPI-POPULATION-001"]
        or finding.get("claim_template_id") != "MAT6-CLAIM-KPI-DEFINITION"
        or finding.get("arbitration_question_template_id") != "MAT6-QUESTION-KPI-DEFINITION"
        or not isinstance(finding.get("evidence_ids"), list)
        or len(finding["evidence_ids"]) != 2
        or any(not _nonempty_text(item) for item in finding["evidence_ids"])
        or not _nonempty_text(finding.get("claim"))
        or not _nonempty_text(finding.get("arbitration_question"))
    ):
        raise _fail(code)
    qualification = _strict_object(
        value.get("qualification"),
        {"eligible", "evidence", "failure_codes", "metrics", "report_id", "route", "status"},
        code,
    )
    qualification_evidence = _strict_object(qualification.get("evidence"), {"path", "sha256"}, code)
    failure_sha = "9e1ec028f83109ff226021cf9ba70c185b1dede1818bc6236166a9b2b2bde4de"
    if (
        qualification.get("status") != "REJECTED_BY_QUALIFICATION"
        or qualification.get("eligible") is not False
        or qualification.get("route") != "BLIND_HOLDOUT"
        or qualification_evidence != {"path": "qualification-failure.json", "sha256": failure_sha}
        or qualification.get("failure_codes") != [
            "ANOMALY_RECALL_FAILURE", "CATEGORY_EXACT_FAILURE", "SEVERITY_EXACT_FAILURE",
            "VERDICT_EXACT_FAILURE", "CITATIONS_EXACT_FAILURE", "EXACT_CLASSIFICATION_FAILURE",
        ]
        or qualification.get("metrics") != {
            "anomalies_expected": 12, "anomalies_recalled": 4,
            "cases_authenticated": 24, "cases_expected": 24,
            "exact_classification_cases": 16, "executions_authenticated": 120,
            "executions_expected": 120, "false_publication_vetoes_on_controls": 0,
            "raw_block_safety_violations": 0, "resolved_controls_clean": 12,
            "resolved_controls_expected": 12, "stable_cases": 24,
        }
        or not _nonempty_text(qualification.get("report_id"))
    ):
        raise _fail(code)
    if value.get("model") != {
        "deployment_status": "NOT_DEPLOYED",
        "qualification_status": "REJECTED_BY_QUALIFICATION",
        "repository_id": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
        "revision": "5a5a776300a41aaa681dd7ff0106608ef2bc90db",
    } or value.get("publication_decision") != {
        "decision": "BLOCK_PUBLICATION", "external_evidence_sha256": failure_sha,
    }:
        raise _fail(code)
    gate = _strict_object(
        value.get("publication_gate"),
        {"human_authority", "reason", "status"},
        code,
    )
    if gate != {
        "human_authority": {
            "may_arbitrate_business_conflicts": True,
            "may_deploy_this_model": False,
            "may_mark_this_model_pass": False,
            "may_unblock_publication_while_this_model_is_selected": False,
            "must_compile_business_arbitration_as_deterministic_control": True,
        },
        "reason": "SELECTED_MODEL_REJECTED_BY_QUALIFICATION",
        "status": "BLOCKED",
    } or value.get("safety") != {
        "candidate_capture_is_sanitized": True,
        "kpi_calculated_or_certified_by_ai": False,
        "private_case_identity_included": False,
        "private_paths_included": False,
        "private_truth_included": False,
        "raw_model_output_included": False,
    }:
        raise _fail(code)


def _validate_resource_evidence(
    value: Mapping[str, Any],
    *,
    payload: bytes,
    release_root: Path,
) -> str:
    code = "NERIVANE_ACTIVE_RESOURCE_EVIDENCE_INVALID"
    pinned_manifest_sha256 = "0140c6c939844c1a213c5188b3d8d48d4dbd3976fa01f11b00020a5a716caa21"
    _strict_object(
        value,
        {
            "contract_id", "full_campaign_claim_allowed", "gpu", "limitations",
            "node_count", "reports", "schema_version", "status", "summary",
        },
        code,
    )
    if (
        _sha256(payload) != pinned_manifest_sha256
        or value.get("schema_version") != 1
        or value.get("contract_id")
        != "NERIVANE-FULL-H1-RESOURCE-WINDOWS-PUBLIC-PACKAGE-V1"
        or value.get("status") != "PASS_OBSERVED_WINDOWS"
        or value.get("full_campaign_claim_allowed") is not False
        or value.get("gpu") != {"h1_used": False, "status": "NOT_USED_BY_H1_PIPELINE"}
        or value.get("limitations") != [
            "OBSERVED_WINDOWS_NOT_COMPLETE_CAMPAIGN_MEASUREMENT",
            "NETWORK_COUNTERS_HOST_AGGREGATE_NOT_PROCESS_ATTRIBUTED",
            "NO_CONCURRENCY_OR_PERFORMANCE_BENCHMARK_CLAIM",
        ]
        or value.get("node_count") != 4
        or value.get("summary") != {
            "active_process_windows": 2, "completed_jobs_observed": 639,
            "failed_jobs_observed": 0, "nodes_with_completed_jobs": 4,
            "orphaned_jobs_observed": 0, "peak_rss_bytes_observed": 1_652_461_568,
            "process_write_bytes_delta_observed": 38_416_384,
        }
    ):
        raise _fail(code)
    reports = value.get("reports")
    expected_reports = (
        ("node-a", "1c2f5df0f3bc314eec09b001ba46167fa3acf1783071c4cbda4ab2991ba13979"),
        ("node-b", "2d79bdba25af23a212eafe2d8303bde031cb6be82c670aa1d2e9d6ed82b9e04c"),
        ("node-c", "4e9cd6ef21996e25c0777c62935715c2d9df3b2cbf1e8d826a8953a5bd849053"),
        ("node-d", "6d411baca99f0a1318a6d60ca0025a345852ed1288a5a18a6b643017fe7f0f5f"),
    )
    if not isinstance(reports, list) or len(reports) != 4:
        raise _fail(code)
    for item, (node_ref, expected_sha256) in zip(reports, expected_reports):
        report = _strict_object(item, {"node_ref", "path", "sha256"}, code)
        expected_path = f"evidence/resource-windows/{node_ref}.json"
        if report != {
            "node_ref": node_ref, "path": f"{node_ref}.json", "sha256": expected_sha256,
        }:
            raise _fail(code)
        target = release_root.joinpath(*PurePosixPath(expected_path).parts)
        try:
            raw = importer._read_regular(target, 0o644, code)
            parsed = json.loads(raw)
        except (importer.NerivaneReleaseImportError, UnicodeDecodeError, json.JSONDecodeError):
            raise _fail(code) from None
        if (
            _sha256(raw) != expected_sha256
            or not isinstance(parsed, dict)
            or raw != _canonical(parsed)
            or set(parsed) != {
                "campaign_health", "complete_campaign_observation", "contract_id",
                "full_campaign_claim_allowed", "gpu", "jobs", "mutation_boundary",
                "node_ref", "observation_scope", "resources", "sanitization",
                "schema_version", "source_reported_error_count", "status", "window",
            }
            or parsed.get("node_ref") != node_ref
            or parsed.get("status") != "PASS_OBSERVED_WINDOW"
            or parsed.get("full_campaign_claim_allowed") is not False
            or parsed.get("gpu") != {"h1_used": False, "status": "NOT_USED_BY_H1_PIPELINE"}
        ):
            raise _fail(code)
    return pinned_manifest_sha256


def validate_active_data(
    payload: bytes,
    *,
    release_id: str,
    release_root: Path,
    expected_source_commit: str,
) -> dict[str, Any]:
    """Validate every field of the active V2 data contract and its evidence."""

    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("NERIVANE_ACTIVE_DATA_JSON_INVALID") from None
    if not isinstance(data, dict) or payload != _canonical(data):
        raise _fail("NERIVANE_ACTIVE_DATA_JSON_INVALID")
    _strict_object(
        data,
        {
            "boundaries",
            "contract_id",
            "evidence",
            "fictional_scenario",
            "format_version",
            "metrics",
            "publication_boundary",
            "release_reference",
            "source_commit",
            "status",
            "steps",
            "subtitle",
            "title",
        },
        "NERIVANE_ACTIVE_DATA_SCHEMA_INVALID",
    )
    release_reference = (
        "../assets/validated-releases/nerivane-v2/" f"{release_id}"
    )
    if (
        data.get("contract_id") != "DATAPREDICT-NERIVANE-ACTIVE-SITE-DATA-V2"
        or data.get("format_version") != "2.0.0"
        or data.get("fictional_scenario") is not True
        or data.get("status") != "ACTIVE_REPLAY_AVAILABLE"
        or data.get("release_reference") != release_reference
        or data.get("source_commit") != expected_source_commit
        or COMMIT_PATTERN.fullmatch(str(data.get("source_commit"))) is None
        or not _nonempty_text(data.get("title"))
        or not _nonempty_text(data.get("subtitle"))
    ):
        raise _fail("NERIVANE_ACTIVE_DATA_IDENTITY_INVALID")

    metrics = data.get("metrics")
    expected_metric_labels = (
        "Volume H1 encodé",
        "Lignes physiques",
        "Production distribuée",
        "Échantillon gouverné",
    )
    if not isinstance(metrics, list) or len(metrics) != 4:
        raise _fail("NERIVANE_ACTIVE_DATA_METRICS_INVALID")
    for index, metric in enumerate(metrics):
        value = _strict_object(
            metric,
            {"label", "scope", "value"},
            "NERIVANE_ACTIVE_DATA_METRICS_INVALID",
        )
        if (
            value.get("label") != expected_metric_labels[index]
            or not _nonempty_text(value.get("value"))
            or not _nonempty_text(value.get("scope"))
        ):
            raise _fail("NERIVANE_ACTIVE_DATA_METRICS_INVALID")
    encoded_match = re.fullmatch(r"([1-9][0-9\u202f]*) octets", str(metrics[0]["value"]))
    if (
        encoded_match is None
        or int(encoded_match.group(1).replace("\u202f", "")) <= 3 * (1024**4) // 2
        or metrics[1]["value"] != "2\u202f004\u202f364\u202f194"
        or metrics[2]["value"] != "1\u202f320 triplets"
        or metrics[3]["value"] != "210\u202f724 lignes · 36/36 PASS"
    ):
        raise _fail("NERIVANE_ACTIVE_DATA_METRICS_INVALID")

    steps = data.get("steps")
    expected_step_ids = (
        "impasse-metier",
        "diagnostic-opposable",
        "h1-massif",
        "topologie-heterogene",
        "echantillon-controle",
        "veto-ia-fail-closed",
        "transfert-controle",
    )
    expected_titles = (
        "Constater l'impasse métier",
        "Rendre le diagnostic opposable",
        "Prouver le traitement massif H1",
        "Gouverner une topologie hétérogène",
        "Matérialiser et contrôler l'échantillon",
        "Exécuter le veto IA fail-closed",
        "Sceller un transfert inactif",
    )
    if not isinstance(steps, list) or len(steps) != 7:
        raise _fail("NERIVANE_ACTIVE_DATA_STEPS_INVALID")
    for index, step in enumerate(steps, start=1):
        value = _strict_object(
            step,
            {
                "action",
                "href",
                "id",
                "limitation",
                "order",
                "problem",
                "proof",
                "status",
                "title",
            },
            "NERIVANE_ACTIVE_DATA_STEPS_INVALID",
        )
        if (
            value.get("order") != index
            or value.get("id") != expected_step_ids[index - 1]
            or value.get("title") != expected_titles[index - 1]
            or value.get("status")
            != ("VALIDÉ_FAIL_CLOSED" if index == 6 else "VALIDÉ")
            or value.get("href") != f"{release_reference}/steps/{index:02d}.html"
            or any(
                not _nonempty_text(value.get(field))
                for field in ("action", "limitation", "problem", "proof")
            )
        ):
            raise _fail("NERIVANE_ACTIVE_DATA_STEPS_INVALID")

    evidence = data.get("evidence")
    expected_evidence = (
        ("replay-v2", "Manifeste du replay V2", "replay-manifest.json"),
        ("full-h1", "Preuve H1 finale assainie", "evidence/full-h1-final-public.json"),
        ("park-resources", "Fenêtres CPU et mémoire du parc H1", "evidence/resource-windows/manifest.json"),
        ("sample-controls", "Synthèse de l’échantillon et des 36 contrôles", "evidence/bigquery-h1-sample-public.json"),
        ("ai-fail-closed", "Overlay IA local fail-closed", "evidence/ai-local-fail-closed.json"),
    )
    if not isinstance(evidence, list) or len(evidence) != 5:
        raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")
    evidence_values: dict[str, dict[str, Any]] = {}
    evidence_payloads: dict[str, bytes] = {}
    for item, (expected_id, expected_label, expected_relative) in zip(evidence, expected_evidence):
        value = _strict_object(
            item,
            {"href", "id", "label", "sha256"},
            "NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID",
        )
        target = _resolve_release_reference(
            release_root,
            release_id,
            value.get("href"),
            expected_relative,
        )
        expected_digest = value.get("sha256")
        if (
            value.get("id") != expected_id
            or value.get("label") != expected_label
            or not isinstance(expected_digest, str)
            or RELEASE_ID_PATTERN.fullmatch(expected_digest) is None
            or expected_digest == "0" * 64
            or _sha256(target.read_bytes()) != expected_digest
        ):
            raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")
        parsed, raw = _evidence_json(target, "NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")
        evidence_values[expected_id] = parsed
        evidence_payloads[expected_id] = raw

    h1_semantics = _validate_h1_evidence(evidence_values["full-h1"])
    resource_sha256 = _validate_resource_evidence(
        evidence_values["park-resources"],
        payload=evidence_payloads["park-resources"],
        release_root=release_root,
    )
    _validate_ai_evidence(evidence_values["ai-fail-closed"])
    replay_bindings = _validate_replay_evidence(
        evidence_values["replay-v2"],
        expected_source_commit=expected_source_commit,
        h1_sha256=_sha256(evidence_payloads["full-h1"]),
        resource_sha256=resource_sha256,
        ai_sha256=_sha256(evidence_payloads["ai-fail-closed"]),
    )
    _validate_sample_evidence(
        evidence_values["sample-controls"],
        h1=h1_semantics,
        replay_bindings=replay_bindings,
    )
    encoded_value = f"{h1_semantics['encoded_bytes']:,}".replace(",", "\u202f") + " octets"
    if (
        metrics[0]["value"] != encoded_value
        or metrics[1]["value"] != "2\u202f004\u202f364\u202f194"
        or metrics[2]["value"] != "1\u202f320 triplets"
        or metrics[3]["value"] != "210\u202f724 lignes · 36/36 PASS"
    ):
        raise _fail("NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID")

    boundaries = data.get("boundaries")
    expected_boundaries = {
        "KPI métier": "Rapproché par règles déterministes, mais publication bloquée par le modèle IA rejeté.",
        "Cloud": "Échantillon au schéma BigQuery contrôlé localement; aucun chargement GCP V2 revendiqué.",
        "IA locale": "Inférence capturée, qualification échouée, modèle non déployé et porte fail-closed.",
    }
    if not isinstance(boundaries, list) or len(boundaries) != 3:
        raise _fail("NERIVANE_ACTIVE_DATA_BOUNDARIES_INVALID")
    observed_boundaries: dict[str, str] = {}
    for boundary in boundaries:
        value = _strict_object(
            boundary,
            {"text", "title"},
            "NERIVANE_ACTIVE_DATA_BOUNDARIES_INVALID",
        )
        if not _nonempty_text(value.get("title")) or not _nonempty_text(value.get("text")):
            raise _fail("NERIVANE_ACTIVE_DATA_BOUNDARIES_INVALID")
        observed_boundaries[str(value["title"])] = str(value["text"])
    if observed_boundaries != expected_boundaries:
        raise _fail("NERIVANE_ACTIVE_DATA_BOUNDARIES_INVALID")

    publication = _strict_object(
        data.get("publication_boundary"),
        {
            "ai_model_deployment_status",
            "gcp_v2_load_status",
            "kpi_publication_status",
            "site_replay_status",
        },
        "NERIVANE_ACTIVE_DATA_PUBLICATION_INVALID",
    )
    if publication != {
        "ai_model_deployment_status": "NOT_DEPLOYED",
        "gcp_v2_load_status": "NOT_CLAIMED_LOCAL_ONLY",
        "kpi_publication_status": "BLOCKED_BY_REJECTED_AI_MODEL",
        "site_replay_status": "ACTIVE",
    }:
        raise _fail("NERIVANE_ACTIVE_DATA_PUBLICATION_INVALID")
    return data


def _validate_demo2_maintenance(root: Path, catalogue: bytes) -> None:
    fissures = _read_regular(root, "demonstrations/fissures.html").decode("utf-8")
    catalogue_text = catalogue.decode("utf-8")
    demo2 = re.search(
        r'<a class="demonstrations-page__card-link" '
        r'href="demonstrations/fissures\.html".*?</a>',
        catalogue_text,
        flags=re.DOTALL,
    )
    if (
        '<body class="fissures-demo" data-maintenance="true">' not in fissures
        or "Démonstration 2 · En maintenance" not in fissures
        or demo2 is None
        or '<span class="demonstrations-page__card-status">En maintenance</span>'
        not in demo2.group(0)
        or "Consulter la version en maintenance" not in demo2.group(0)
    ):
        raise _fail("NERIVANE_DEMO2_MAINTENANCE_CHANGED")


def _validate_maintenance(
    root: Path,
    *,
    page: bytes,
    fragment: bytes,
    baseline: Mapping[str, Any],
) -> dict[str, object]:
    page_text = page.decode("utf-8")
    fragment_text = fragment.decode("utf-8")
    exact_markers = (
        page.count(MAINTENANCE_PAGE_MARKER) == 1,
        "Maintenance planifiée" in page_text,
        "La démonstration Nérivane est en cours de finalisation" in page_text,
        ">Disponible · maintenance<" in fragment_text,
        "Consulter la version de maintenance" in fragment_text,
        ACTIVE_PAGE_RELEASE_PATTERN.search(page) is None,
        ACTIVE_CATALOGUE_RELEASE_PATTERN.search(fragment) is None,
    )
    observed = {
        relative: _sha256(_read_regular(root, relative))
        for relative in ACTIVE_TARGETS
    }
    if not all(exact_markers):
        raise _fail("NERIVANE_MAINTENANCE_MARKERS_INVALID")
    if (
        observed != baseline["maintenance_targets"]
        or _sha256(fragment) != baseline["maintenance_catalogue_fragment_sha256"]
    ):
        raise _fail("NERIVANE_MAINTENANCE_BASELINE_CHANGED")
    return {"state": MAINTENANCE_STATE, "release_id": None, "status": "VALIDÉ"}


def _validate_active(
    root: Path,
    *,
    page: bytes,
    fragment: bytes,
    page_release_id: str,
    catalogue_release_id: str,
) -> dict[str, object]:
    if page_release_id != catalogue_release_id:
        raise _fail("NERIVANE_ACTIVE_RELEASE_ID_DIVERGED")
    release_id = page_release_id
    page_lower = page.lower()
    page_text = page.decode("utf-8")
    expected_replay_href = (
        "../assets/validated-releases/nerivane-v2/"
        f"{release_id}/index.html"
    )
    if (
        page.count(ACTIVE_HEADER_MARKER) != 1
        or any(page_text.count(marker) != 1 for marker in ACTIVE_SEO_MARKERS)
        or page_text.count(
            f'<body class="nerivane-demo-page" data-release-id="{release_id}">'
        ) != 1
        or page_text.count(expected_replay_href) != 1
        or page_text.count('<link rel="stylesheet" href="../assets/css/site.css">') != 1
        or page_text.count('<link rel="stylesheet" href="../assets/css/demo-nerivane.css">') != 1
        or page_text.count('<script src="../assets/js/demo-nerivane.js" defer></script>') != 1
        or page_text.count('<script src="../assets/js/audience-counter.js" defer></script>') != 1
        or page_lower.count(b"https://www.datapredict.org/demonstrations/nerivane-distribution.html") != 2
        or page_lower.count(b"https://www.datapredict.org/assets/img/social-datapredict.png") != 1
        or page_lower.count(b"https://") != 3
        or any(
            b"maintenance" in payload.lower()
            for payload in (
                page,
                fragment,
                _read_regular(root, DATA_RELATIVE),
                _read_regular(root, SCRIPT_RELATIVE),
                _read_regular(root, STYLE_RELATIVE),
            )
        )
        or page_lower.count(b'data-status="verification"') != 1
        or page.count(release_id.encode("ascii")) != 2
        or fragment.count(release_id.encode("ascii")) != 1
        or fragment.count(
            f'data-release="assets/validated-releases/nerivane-v2/{release_id}"'.encode("ascii")
        )
        != 1
    ):
        raise _fail("NERIVANE_ACTIVE_MARKERS_INVALID")
    try:
        imported = importer.verify_imported_releases(site_root=root)
        attestation = promoter.attest_release(release_id, site_root=root)
    except (importer.NerivaneReleaseImportError, promoter.NerivanePromotionError) as error:
        raise _fail("NERIVANE_ACTIVE_CONTENT_ADDRESS_INVALID") from error
    if release_id not in imported or attestation.get("state") != "ACTIVE":
        raise _fail("NERIVANE_ACTIVE_CONTENT_ADDRESS_INVALID")

    release_root = root.joinpath(*importer.DESTINATION_RELATIVE.parts, release_id)
    try:
        manifest = json.loads((release_root / importer.MANIFEST_PATH).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("NERIVANE_ACTIVE_CONTENT_ADDRESS_INVALID") from None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if not isinstance(source, dict) or set(source) != {"commit", "repository"}:
        raise _fail("NERIVANE_ACTIVE_CONTENT_ADDRESS_INVALID")
    active_data_payload = _read_regular(root, DATA_RELATIVE)
    if active_data_payload.count(release_id.encode("ascii")) != 13:
        raise _fail("NERIVANE_ACTIVE_RELEASE_ID_DIVERGED")
    validate_active_data(
        active_data_payload,
        release_id=release_id,
        release_root=release_root,
        expected_source_commit=str(source.get("commit")),
    )

    script = _read_regular(root, SCRIPT_RELATIVE).decode("utf-8")
    required_script_markers = (
        'const CONTRACT_ID = "DATAPREDICT-NERIVANE-ACTIVE-SITE-DATA-V2";',
        'function setHeaderState(status, label, ariaLabel)',
        'const labelNode = headerState.querySelector("[data-state-label]");',
        "headerState.dataset.status = status;",
        'headerState.setAttribute("aria-busy", "false");',
        'headerState.setAttribute("aria-label", ariaLabel);',
        "labelNode.textContent = label;",
        'setHeaderState("valide", "Replay scellé", "Replay authentifié et scellé");',
        '"indisponible",\n      "Indisponible / non authentifié",\n      "Replay public indisponible ou non authentifié",',
        'data.contract_id !== CONTRACT_ID',
        'data.format_version !== "2.0.0"',
        'data.fictional_scenario !== true',
        'data.status !== "ACTIVE_REPLAY_AVAILABLE"',
        'if (!/^[0-9a-f]{64}$/.test(releaseId))',
        'if (data.release_reference !== releaseRoot)',
        'function requireSha(value, label)',
        'data.evidence.length !== 5',
        '["park-resources", "evidence/resource-windows/manifest.json"],',
        'const [expectedId, expectedPath] = expectedEvidence[index];',
        'if (proof.id !== expectedId)',
        'if (proof.href !== `${releaseRoot}/${expectedPath}`)',
        'requireSha(proof.sha256, `evidence[${index}].sha256`);',
        'if (!response.ok) throw new Error("Registre public indisponible");',
        'return response.json();',
        ".then(validateData)\n    .then(render)\n    .catch(renderError);",
    )
    if any(marker not in script for marker in required_script_markers):
        raise _fail("NERIVANE_ACTIVE_FAIL_CLOSED_HEADER_INVALID")
    return {"state": ACTIVE_STATE, "release_id": release_id, "status": "VALIDÉ"}


def validate_site_state(
    *,
    site_root: Path = SITE_ROOT,
    baseline: Mapping[str, Any] = DEFAULT_BASELINE,
) -> dict[str, object]:
    """Validate one exact state, rejecting absent, mixed and hybrid states."""

    _validate_baseline(baseline)
    root = _root(site_root)
    _validate_promoted_path_contract(root)
    page = _read_regular(root, PAGE_RELATIVE)
    catalogue = _read_regular(root, CATALOGUE_RELATIVE)
    _, fragment, _ = _catalogue_parts(catalogue)

    if _catalogue_outside_sha256(catalogue) != baseline["catalogue_outside_sha256"]:
        raise _fail("NERIVANE_CATALOGUE_OUTSIDE_CHANGED")
    if protected_snapshot_sha256(root) != baseline["protected_snapshot_sha256"]:
        raise _fail("NERIVANE_PROTECTED_TREE_CHANGED")
    _validate_demo2_maintenance(root, catalogue)

    maintenance_present = MAINTENANCE_PAGE_MARKER in page.lower()
    page_matches = ACTIVE_PAGE_RELEASE_PATTERN.findall(page)
    catalogue_matches = ACTIVE_CATALOGUE_RELEASE_PATTERN.findall(fragment)
    active_present = bool(page_matches or catalogue_matches)
    if maintenance_present and active_present:
        raise _fail("NERIVANE_SITE_STATE_HYBRID")
    if maintenance_present:
        return _validate_maintenance(
            root,
            page=page,
            fragment=fragment,
            baseline=baseline,
        )
    if len(page_matches) == 1 and len(catalogue_matches) == 1:
        return _validate_active(
            root,
            page=page,
            fragment=fragment,
            page_release_id=page_matches[0].decode("ascii"),
            catalogue_release_id=catalogue_matches[0].decode("ascii"),
        )
    raise _fail("NERIVANE_SITE_STATE_UNRECOGNIZED")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, default=SITE_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = validate_site_state(site_root=args.site_root)
    except NerivaneSiteStateError as error:
        print(f"NERIVANE_SITE_STATE_FAILED: {error.code}", file=sys.stderr)
        return 1
    release = result.get("release_id") or "none"
    print(
        f"NERIVANE_SITE_STATE_OK state={result['state']} "
        f"release_id={release} protected=VALIDÉ demo2=MAINTENANCE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
