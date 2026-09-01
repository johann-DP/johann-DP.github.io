#!/usr/bin/env python3
"""Import a closed Nérivane V2 package as an inactive, create-only site release.

The command deliberately cannot activate the release or remove the maintenance
state.  Its only writable target is the content-addressed collection below
``assets/validated-releases/nerivane-v2``.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping


SITE_ROOT = Path(__file__).resolve().parents[1]
DESTINATION_RELATIVE = PurePosixPath("assets/validated-releases/nerivane-v2")
MANIFEST_PATH = "site-release-manifest.json"
READY_PATH = ".READY"
READY_CONTENT = b"nerivane-v2-inactive-site-import-ready\n"
CONTRACT_ID = "DATAPREDICT-NERIVANE-INACTIVE-SITE-RELEASE-V2"
REPLAY_CONTRACT_ID = "NERIVANE-PUBLIC-REPLAY-V2"
REPLAY_STATUS = "SEALED_PUBLIC_REPLAY"
REPOSITORY = "johann-DP/datapredict-governed-kpi-demo"
STATE = "READY_FOR_INACTIVE_SITE_IMPORT"
PUBLICATION = {
    "automatic_activation_permitted": False,
    "maintenance_removal_permitted": False,
}
GATES = {
    "ai_local_fail_closed": "VALIDÉ",
    "bigquery_h1_sample": "VALIDÉ",
    "full_h1": "VALIDÉ",
    "public_sanitization": "VALIDÉ",
    "seven_step_replay": "VALIDÉ",
}
REQUIRED_FILES = {
    "SHA256SUMS": "public_checksum",
    "index.html": "public_html",
    "replay-manifest.json": "public_json",
    **{f"steps/{index:02d}.html": "public_html" for index in range(1, 8)},
}
ALLOWED_ROLES = {
    "public_asset",
    "public_checksum",
    "public_evidence",
    "public_html",
    "public_json",
    "public_script",
    "public_stylesheet",
}
TEXT_SUFFIXES = {
    "",
    ".css",
    ".csv",
    ".html",
    ".htm",
    ".js",
    ".json",
    ".md",
    ".svg",
    ".txt",
    ".xml",
}
ALLOWED_BINARY_SUFFIXES = {".gif", ".jpeg", ".jpg", ".pdf", ".png", ".webp", ".woff2"}
HASH_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}", flags=re.ASCII)
PRIVATE_TEXT_PATTERNS = (
    re.compile(r"/(?:home|media|run/media)/", flags=re.IGNORECASE),
    re.compile(
        r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
        r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
        r"|\b(?:169\.254|192\.168)\.\d{1,3}\.\d{1,3}\b"
    ),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"file://", flags=re.IGNORECASE),
    re.compile(r"\b[A-Z]:\\(?:Users|home)\\", flags=re.IGNORECASE),
)
MAX_FILES = 2_000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024

ACTIVE_FILES = (
    PurePosixPath("demonstrations/nerivane-distribution.html"),
    PurePosixPath("assets/data/nerivane-governance-replay.json"),
    PurePosixPath("assets/js/demo-nerivane.js"),
    PurePosixPath("assets/css/demo-nerivane.css"),
    PurePosixPath("demonstrations.html"),
)
ACTIVE_BUNDLE = PurePosixPath("assets/nerivane-public-v1")


class NerivaneReleaseImportError(RuntimeError):
    """Stable fail-closed error exposed by the command-line interface."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NerivaneReleaseImportError:
    return NerivaneReleaseImportError(code)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise _fail("NERIVANE_V2_JSON_INVALID") from None
    return f"{rendered}\n".encode("utf-8")


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
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _fail(code)
    return value


def _read_regular(path: Path, mode: int, code: str) -> bytes:
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
        while chunk := os.read(descriptor, CHUNK_SIZE):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        payload = b"".join(chunks)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(payload) != before.st_size
        ):
            raise _fail(code)
        return payload
    finally:
        os.close(descriptor)


def _mode_profile(root: Path) -> tuple[int, int, int, int]:
    try:
        root_mode = stat.S_IMODE(root.lstat().st_mode)
    except OSError:
        raise _fail("NERIVANE_V2_TREE_INVALID") from None
    if root_mode == 0o700:
        return 0o700, 0o500, 0o400, 0o444
    if root_mode == 0o755:
        return 0o755, 0o755, 0o644, 0o644
    raise _fail("NERIVANE_V2_TREE_INVALID")


def _inventory(
    root: Path,
    *,
    root_mode: int,
    directory_mode: int,
    file_mode: int,
    ready_mode: int,
) -> set[str]:
    try:
        root_stat = root.lstat()
    except OSError:
        raise _fail("NERIVANE_V2_TREE_INVALID") from None
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != root_mode
    ):
        raise _fail("NERIVANE_V2_TREE_INVALID")

    observed: set[str] = set()

    def visit(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            raise _fail("NERIVANE_V2_TREE_INVALID") from None
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            if relative in observed:
                raise _fail("NERIVANE_V2_TREE_INVALID")
            observed.add(relative)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                raise _fail("NERIVANE_V2_TREE_INVALID") from None
            if stat.S_ISLNK(metadata.st_mode):
                raise _fail("NERIVANE_V2_TREE_INVALID")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != directory_mode:
                    raise _fail("NERIVANE_V2_TREE_INVALID")
                visit(Path(entry.path))
            elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise _fail("NERIVANE_V2_TREE_INVALID")
            else:
                expected_mode = ready_mode if relative == READY_PATH else file_mode
                if stat.S_IMODE(metadata.st_mode) != expected_mode:
                    raise _fail("NERIVANE_V2_TREE_INVALID")

    visit(root)
    return observed


def _expected_descendants(files: set[str]) -> set[str]:
    expected = set(files)
    for value in files:
        for parent in PurePosixPath(value).parents:
            if parent.as_posix() != ".":
                expected.add(parent.as_posix())
    return expected


def _parse_records(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FILES:
        raise _fail("NERIVANE_V2_MANIFEST_INVALID")
    records: dict[str, dict[str, object]] = {}
    ordered: list[str] = []
    total_bytes = 0
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "path",
            "role",
            "sha256",
            "size_bytes",
        }:
            raise _fail("NERIVANE_V2_MANIFEST_INVALID")
        path = _safe_relative(raw["path"], "NERIVANE_V2_MANIFEST_INVALID")
        role = raw["role"]
        digest = raw["sha256"]
        size = raw["size_bytes"]
        suffix = PurePosixPath(path).suffix.lower()
        if (
            path in records
            or path in {MANIFEST_PATH, READY_PATH}
            or role not in ALLOWED_ROLES
            or not isinstance(digest, str)
            or HASH_PATTERN.fullmatch(digest) is None
            or type(size) is not int
            or size < 1
            or suffix not in TEXT_SUFFIXES | ALLOWED_BINARY_SUFFIXES
        ):
            raise _fail("NERIVANE_V2_MANIFEST_INVALID")
        records[path] = {
            "path": path,
            "role": role,
            "sha256": digest,
            "size_bytes": size,
        }
        ordered.append(path)
        total_bytes += size
    if ordered != sorted(ordered) or total_bytes > MAX_TOTAL_BYTES:
        raise _fail("NERIVANE_V2_MANIFEST_INVALID")
    for path, role in REQUIRED_FILES.items():
        if records.get(path, {}).get("role") != role:
            raise _fail("NERIVANE_V2_MANIFEST_INVALID")
    return records


def _manifest_identity(manifest: Mapping[str, object]) -> dict[str, object]:
    return {key: manifest[key] for key in manifest if key != "release_id"}


def _validate_manifest(
    payload: bytes, root_name: str
) -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    manifest = _canonical_json(payload, "NERIVANE_V2_MANIFEST_INVALID")
    if set(manifest) != {
        "contract_id",
        "files",
        "gates",
        "manifest_version",
        "publication",
        "release_id",
        "source",
        "state",
    }:
        raise _fail("NERIVANE_V2_MANIFEST_INVALID")
    source = manifest["source"]
    if (
        manifest["contract_id"] != CONTRACT_ID
        or manifest["manifest_version"] != 2
        or manifest["publication"] != PUBLICATION
        or manifest["gates"] != GATES
        or manifest["state"] != STATE
        or not isinstance(source, dict)
        or set(source) != {"commit", "repository"}
        or source.get("repository") != REPOSITORY
        or not isinstance(source.get("commit"), str)
        or COMMIT_PATTERN.fullmatch(source["commit"]) is None
        or not isinstance(manifest["release_id"], str)
        or HASH_PATTERN.fullmatch(manifest["release_id"]) is None
        or manifest["release_id"] != root_name
        or _sha256(_canonical_json_bytes(_manifest_identity(manifest))) != root_name
    ):
        raise _fail("NERIVANE_V2_MANIFEST_INVALID")
    return manifest, _parse_records(manifest["files"])


def _validate_text(path: str, payload: bytes) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("NERIVANE_V2_PUBLIC_TEXT_INVALID") from None
    for pattern in PRIVATE_TEXT_PATTERNS:
        if pattern.search(text):
            raise _fail("NERIVANE_V2_PUBLIC_TEXT_NOT_SANITIZED")
    if suffix in {".html", ".htm"} and not text.lower().startswith("<!doctype html>"):
        raise _fail("NERIVANE_V2_PUBLIC_HTML_INVALID")


def _validate_checksums(payload: bytes, records: Mapping[str, Mapping[str, object]]) -> None:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise _fail("NERIVANE_V2_CHECKSUMS_INVALID") from None
    observed: dict[str, str] = {}
    ordered: list[str] = []
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or HASH_PATTERN.fullmatch(parts[0]) is None:
            raise _fail("NERIVANE_V2_CHECKSUMS_INVALID")
        path = _safe_relative(parts[1], "NERIVANE_V2_CHECKSUMS_INVALID")
        if path in observed or path == "SHA256SUMS":
            raise _fail("NERIVANE_V2_CHECKSUMS_INVALID")
        observed[path] = parts[0]
        ordered.append(path)
    expected_paths = set(records) - {"SHA256SUMS"}
    if (
        ordered != sorted(ordered)
        or set(observed) != expected_paths
        or any(observed[path] != records[path]["sha256"] for path in expected_paths)
    ):
        raise _fail("NERIVANE_V2_CHECKSUMS_INVALID")


def _validate_replay(payload: bytes) -> None:
    try:
        replay = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("NERIVANE_V2_REPLAY_INVALID") from None
    status = replay.get("status") if isinstance(replay, dict) else None
    counts = replay.get("counts") if isinstance(replay, dict) else None
    contract = replay.get("contract_id") if isinstance(replay, dict) else None
    if (
        status != REPLAY_STATUS
        or not isinstance(counts, dict)
        or counts.get("steps") != 7
        or replay.get("fictional") is not True
        or contract != REPLAY_CONTRACT_ID
    ):
        raise _fail("NERIVANE_V2_REPLAY_INVALID")


def _verify_source(root: Path) -> tuple[str, bytes, dict[str, bytes]]:
    absolute = Path(os.path.abspath(root))
    try:
        resolved = absolute.resolve(strict=True)
    except OSError:
        raise _fail("NERIVANE_V2_SOURCE_INVALID") from None
    if (
        absolute != resolved
        or resolved.is_symlink()
        or HASH_PATTERN.fullmatch(resolved.name) is None
    ):
        raise _fail("NERIVANE_V2_SOURCE_INVALID")

    root_mode, directory_mode, file_mode, ready_mode = _mode_profile(resolved)
    before = _inventory(
        resolved,
        root_mode=root_mode,
        directory_mode=directory_mode,
        file_mode=file_mode,
        ready_mode=ready_mode,
    )
    manifest_payload = _read_regular(
        resolved / MANIFEST_PATH,
        file_mode,
        "NERIVANE_V2_MANIFEST_INVALID",
    )
    _, records = _validate_manifest(manifest_payload, resolved.name)
    expected = _expected_descendants(set(records) | {MANIFEST_PATH, READY_PATH})
    if before != expected:
        raise _fail("NERIVANE_V2_INVENTORY_DIVERGED")
    if (
        _read_regular(
            resolved / READY_PATH,
            ready_mode,
            "NERIVANE_V2_READY_INVALID",
        )
        != READY_CONTENT
    ):
        raise _fail("NERIVANE_V2_READY_INVALID")

    payloads: dict[str, bytes] = {}
    for relative, record in records.items():
        payload = _read_regular(
            resolved.joinpath(*PurePosixPath(relative).parts),
            file_mode,
            "NERIVANE_V2_FILE_INVALID",
        )
        if len(payload) != record["size_bytes"] or _sha256(payload) != record["sha256"]:
            raise _fail("NERIVANE_V2_FILE_DIVERGED")
        _validate_text(relative, payload)
        payloads[relative] = payload
    _validate_checksums(payloads["SHA256SUMS"], records)
    _validate_replay(payloads["replay-manifest.json"])
    after = _inventory(
        resolved,
        root_mode=root_mode,
        directory_mode=directory_mode,
        file_mode=file_mode,
        ready_mode=ready_mode,
    )
    if after != before:
        raise _fail("NERIVANE_V2_SOURCE_CHANGED")
    return resolved.name, manifest_payload, payloads


def _site_root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        resolved = absolute.resolve(strict=True)
    except OSError:
        raise _fail("NERIVANE_V2_SITE_ROOT_INVALID") from None
    if absolute != resolved or resolved.is_symlink() or not resolved.is_dir():
        raise _fail("NERIVANE_V2_SITE_ROOT_INVALID")
    return resolved


def _collection(site_root: Path) -> Path:
    current = site_root
    for part in DESTINATION_RELATIVE.parts:
        current /= part
        if current.exists() or current.is_symlink():
            try:
                metadata = current.lstat()
            except OSError:
                raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID") from None
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o755
            ):
                raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID")
        else:
            try:
                current.mkdir(mode=0o755)
            except FileExistsError:
                try:
                    metadata = current.lstat()
                except OSError:
                    raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID") from None
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o755
                ):
                    raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID")
            except OSError:
                raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID") from None
            else:
                try:
                    os.chmod(current, 0o755, follow_symlinks=False)
                    _fsync_directory(current.parent)
                except OSError:
                    raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID") from None
    if current.resolve() != current:
        raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID")
    return current


def _active_snapshot(site_root: Path) -> dict[str, str]:
    files = [site_root.joinpath(*path.parts) for path in ACTIVE_FILES]
    bundle = site_root.joinpath(*ACTIVE_BUNDLE.parts)
    if not bundle.is_dir() or bundle.is_symlink():
        raise _fail("NERIVANE_V2_ACTIVE_TREE_INVALID")
    files.extend(path for path in sorted(bundle.rglob("*")) if path.is_file())
    snapshot: dict[str, str] = {}
    for path in files:
        try:
            metadata = path.lstat()
        except OSError:
            raise _fail("NERIVANE_V2_ACTIVE_TREE_INVALID") from None
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise _fail("NERIVANE_V2_ACTIVE_TREE_INVALID")
        snapshot[path.relative_to(site_root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return snapshot


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o644)
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
        raise _fail("NERIVANE_V2_RENAME_NOREPLACE_UNAVAILABLE") from None
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


def _public_inventory(root: Path) -> tuple[bytes, dict[str, bytes]]:
    observed = _inventory(
        root,
        root_mode=0o755,
        directory_mode=0o755,
        file_mode=0o644,
        ready_mode=0o644,
    )
    manifest_payload = _read_regular(root / MANIFEST_PATH, 0o644, "NERIVANE_V2_PUBLIC_INVALID")
    _, records = _validate_manifest(manifest_payload, root.name)
    if observed != _expected_descendants(set(records) | {MANIFEST_PATH, READY_PATH}):
        raise _fail("NERIVANE_V2_PUBLIC_INVENTORY_DIVERGED")
    if _read_regular(root / READY_PATH, 0o644, "NERIVANE_V2_PUBLIC_INVALID") != READY_CONTENT:
        raise _fail("NERIVANE_V2_PUBLIC_INVALID")
    payloads: dict[str, bytes] = {}
    for relative, record in records.items():
        payload = _read_regular(
            root.joinpath(*PurePosixPath(relative).parts),
            0o644,
            "NERIVANE_V2_PUBLIC_INVALID",
        )
        if len(payload) != record["size_bytes"] or _sha256(payload) != record["sha256"]:
            raise _fail("NERIVANE_V2_PUBLIC_DIVERGED")
        _validate_text(relative, payload)
        payloads[relative] = payload
    _validate_checksums(payloads["SHA256SUMS"], records)
    _validate_replay(payloads["replay-manifest.json"])
    return manifest_payload, payloads


def _verify_expected_destination(
    destination: Path,
    expected_manifest: bytes,
    expected_payloads: Mapping[str, bytes],
) -> None:
    try:
        observed_manifest, observed_payloads = _public_inventory(destination)
    except NerivaneReleaseImportError as error:
        raise _fail("NERIVANE_V2_DESTINATION_DIVERGED") from error
    if observed_manifest != expected_manifest or observed_payloads != expected_payloads:
        raise _fail("NERIVANE_V2_DESTINATION_DIVERGED")


def _remove_incomplete_tree(root: Path) -> None:
    try:
        os.chmod(root, 0o700, follow_symlinks=False)
        for path in root.rglob("*"):
            if path.is_dir():
                os.chmod(path, 0o700, follow_symlinks=False)
        shutil.rmtree(root)
    except OSError:
        pass


def _create_destination(
    destination: Path,
    manifest: bytes,
    payloads: Mapping[str, bytes],
) -> str:
    if destination.exists() or destination.is_symlink():
        _verify_expected_destination(destination, manifest, payloads)
        return "ALREADY_PRESENT"

    container: Path | None = None
    try:
        container = Path(
            tempfile.mkdtemp(
                prefix=f".nerivane-v2-{destination.name}.pending.",
                dir=destination.parent.parent,
            )
        )
        staging = container / destination.name
        staging.mkdir(mode=0o700)
    except OSError:
        if container is not None:
            _remove_incomplete_tree(container)
        raise _fail("NERIVANE_V2_DESTINATION_CREATE_FAILED") from None

    published = False
    try:
        for relative, payload in sorted({**payloads, MANIFEST_PATH: manifest}.items()):
            path = staging.joinpath(*PurePosixPath(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _write_exclusive(path, payload)
        for directory in sorted(
            (path for path in staging.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            os.chmod(directory, 0o755, follow_symlinks=False)
            _fsync_directory(directory)
        os.chmod(staging, 0o755, follow_symlinks=False)
        _write_exclusive(staging / READY_PATH, READY_CONTENT)
        _fsync_directory(staging)
        try:
            staged_manifest, staged_payloads = _public_inventory(staging)
        except NerivaneReleaseImportError as error:
            raise _fail("NERIVANE_V2_DESTINATION_CREATE_FAILED") from error
        if staged_manifest != manifest or staged_payloads != payloads:
            raise _fail("NERIVANE_V2_DESTINATION_CREATE_FAILED")
        _fsync_directory(container)
        try:
            _rename_noreplace(staging, destination)
        except FileExistsError:
            _verify_expected_destination(destination, manifest, payloads)
            _remove_incomplete_tree(container)
            return "ALREADY_PRESENT"
        published = True
        _fsync_directory(container)
        _fsync_directory(destination.parent)
    except Exception as error:
        if not published and (destination.exists() or destination.is_symlink()):
            try:
                _verify_expected_destination(destination, manifest, payloads)
            except NerivaneReleaseImportError:
                pass
            else:
                published = True
        _remove_incomplete_tree(container)
        if isinstance(error, NerivaneReleaseImportError):
            raise
        raise _fail("NERIVANE_V2_DESTINATION_CREATE_FAILED") from error

    _remove_incomplete_tree(container)
    _verify_expected_destination(destination, manifest, payloads)
    return "CREATED"


def import_release(source_bundle: Path, *, site_root: Path = SITE_ROOT) -> dict[str, object]:
    release_id, manifest, payloads = _verify_source(source_bundle)
    root = _site_root(site_root)
    protected_before = _active_snapshot(root)
    destination = _collection(root) / release_id
    status = _create_destination(destination, manifest, payloads)
    if _active_snapshot(root) != protected_before:
        raise _fail("NERIVANE_V2_ACTIVE_TREE_CHANGED")
    return {
        "release_id": release_id,
        "published_file_count": len(payloads),
        "state": "IMPORTED_INACTIVE",
        "status": status,
    }


def verify_imported_releases(*, site_root: Path = SITE_ROOT) -> tuple[str, ...]:
    root = _site_root(site_root)
    collection = root.joinpath(*DESTINATION_RELATIVE.parts)
    if not collection.exists() and not collection.is_symlink():
        return ()
    current = root
    for part in DESTINATION_RELATIVE.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID") from None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o755
        ):
            raise _fail("NERIVANE_V2_DESTINATION_ROOT_INVALID")
    identifiers: list[str] = []
    for entry in sorted(collection.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir() or HASH_PATTERN.fullmatch(entry.name) is None:
            raise _fail("NERIVANE_V2_PUBLIC_COLLECTION_INVALID")
        _public_inventory(entry)
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
            releases = verify_imported_releases(site_root=args.site_root)
            result: Mapping[str, object] = {
                "release_count": len(releases),
                "release_ids": list(releases),
                "status": "VERIFIED",
            }
        else:
            result = import_release(args.source_bundle, site_root=args.site_root)
    except NerivaneReleaseImportError as error:
        print(f"NERIVANE_V2_IMPORT_FAILED: {error.code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
