#!/usr/bin/env python3
"""Promote one verified inactive Nérivane V2 release transactionally.

The promotion contract is closed to four Nérivane-only files and the marked
Nérivane card inside ``demonstrations.html``.  Each file replacement is atomic;
the durable transaction journal provides exact rollback and crash recovery for
the multi-path commit.  The public maintenance page is replaced last.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping

import import_nerivane_v2_release as importer


TRANSACTION_CONTRACT_ID = "DATAPREDICT-NERIVANE-SITE-PROMOTION-TRANSACTION-V1"
TRANSACTION_VERSION = 1
TRANSACTION_ROOT_RELATIVE = PurePosixPath(
    "assets/validated-releases/.nerivane-v2-promotions"
)
JOURNAL_PATH = "transaction.json"
SNAPSHOT_ROOT = PurePosixPath("snapshot")
REPLACEMENT_ROOT = PurePosixPath("replacement")
PHASE_PREPARED = "PREPARED"
PHASE_COMMITTING = "COMMITTING"
PHASE_COMMITTED = "COMMITTED"
PHASE_ROLLING_BACK = "ROLLING_BACK"
ALLOWED_PHASES = {
    PHASE_PREPARED,
    PHASE_COMMITTING,
    PHASE_COMMITTED,
    PHASE_ROLLING_BACK,
}


class NerivanePromotionError(RuntimeError):
    """Stable fail-closed error exposed by the promotion command."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NerivanePromotionError:
    return NerivanePromotionError(code)


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
        raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID") from None
    return f"{rendered}\n".encode("utf-8")


def _contract() -> dict[str, Any]:
    try:
        _, value = importer._promotion_contract()
    except importer.NerivaneReleaseImportError as error:
        raise _fail(error.code) from error
    return value


def _safe_relative(value: object) -> str:
    if not isinstance(value, str):
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    return value


def _mappings() -> tuple[dict[str, str], ...]:
    raw = _contract().get("mappings")
    if not isinstance(raw, list):
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    mappings: list[dict[str, str]] = []
    observed_targets: set[str] = set()
    for entry in raw:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"kind", "source", "target"}
            or entry.get("kind") not in {"file", "fragment"}
        ):
            raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
        source = _safe_relative(entry["source"])
        target = _safe_relative(entry["target"])
        if target in observed_targets:
            raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
        observed_targets.add(target)
        mappings.append({"kind": entry["kind"], "source": source, "target": target})
    if len(mappings) != 5:
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    return tuple(mappings)


def _commit_order() -> tuple[str, ...]:
    targets = {entry["target"] for entry in _mappings()}
    order = (
        "assets/css/demo-nerivane.css",
        "assets/data/nerivane-governance-replay.json",
        "assets/js/demo-nerivane.js",
        "demonstrations.html",
        "demonstrations/nerivane-distribution.html",
    )
    if set(order) != targets:
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    return order


def _protected_paths() -> tuple[str, ...]:
    raw = _contract().get("protected_paths")
    if not isinstance(raw, list):
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    paths = tuple(_safe_relative(value) for value in raw)
    if not paths or list(paths) != sorted(set(paths)):
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    mapped = {entry["target"] for entry in _mappings()}
    for protected in paths:
        if any(
            protected == target
            or protected.startswith(f"{target}/")
            or target.startswith(f"{protected}/")
            for target in mapped
        ):
            raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    return paths


def _root(site_root: Path) -> Path:
    try:
        return importer._site_root(site_root)
    except importer.NerivaneReleaseImportError as error:
        raise _fail(error.code) from error


def _read_regular(path: Path, *, mode: int = 0o644) -> bytes:
    try:
        return importer._read_regular(path, mode, "NERIVANE_V2_PROMOTION_TARGET_INVALID")
    except importer.NerivaneReleaseImportError as error:
        raise _fail(error.code) from error


def _release(
    site_root: Path,
    release_id: str,
) -> tuple[Path, bytes, dict[str, bytes]]:
    if importer.HASH_PATTERN.fullmatch(release_id) is None:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_ID_INVALID")
    release = site_root.joinpath(*importer.DESTINATION_RELATIVE.parts, release_id)
    try:
        manifest, payloads = importer._public_inventory(release)
    except importer.NerivaneReleaseImportError as error:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_INVALID") from error
    try:
        value = json.loads(manifest)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_INVALID") from None
    if (
        not isinstance(value, dict)
        or value.get("release_id") != release_id
        or value.get("gates") != importer.GATES
        or value.get("contract_id") != importer.CONTRACT_ID
        or value.get("state") != importer.STATE
    ):
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_INVALID")
    return release, manifest, payloads


def _catalogue_parts(payload: bytes) -> tuple[bytes, bytes, bytes, bytes]:
    catalogue = _contract().get("catalogue")
    if not isinstance(catalogue, dict) or set(catalogue) != {"end_marker", "start_marker"}:
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    start = str(catalogue["start_marker"]).encode("utf-8")
    end = str(catalogue["end_marker"]).encode("utf-8")
    if payload.count(start) != 1 or payload.count(end) != 1:
        raise _fail("NERIVANE_V2_CATALOGUE_MARKERS_INVALID")
    before, remainder = payload.split(start, 1)
    middle, after = remainder.split(end, 1)
    if b"nerivane-title" not in middle.lower():
        raise _fail("NERIVANE_V2_CATALOGUE_FRAGMENT_INVALID")
    line = before.rsplit(b"\n", 1)[-1]
    if line.strip():
        raise _fail("NERIVANE_V2_CATALOGUE_MARKERS_INVALID")
    return before + start, middle, end + after, line


def _replace_catalogue(current: bytes, fragment: bytes) -> bytes:
    prefix, _, suffix, indentation = _catalogue_parts(current)
    stripped = fragment.strip()
    if (
        not stripped.lower().startswith(b"<li")
        or not stripped.lower().endswith(b"</li>")
        or b"nerivane-title" not in stripped.lower()
        or b"maintenance" in stripped.lower()
    ):
        raise _fail("NERIVANE_V2_CATALOGUE_FRAGMENT_INVALID")
    indented = b"\n".join(
        indentation + line if line else b""
        for line in stripped.splitlines()
    )
    return prefix + b"\n" + indented + b"\n" + indentation + suffix


def _validate_activation_payloads(
    release_id: str,
    payloads: Mapping[str, bytes],
) -> dict[str, bytes]:
    placeholder = _contract().get("release_id_placeholder")
    if not isinstance(placeholder, str) or not placeholder:
        raise _fail("NERIVANE_V2_PROMOTION_CONTRACT_INVALID")
    placeholder_bytes = placeholder.encode("ascii")
    outputs: dict[str, bytes] = {}
    observed_placeholders = 0
    for mapping in _mappings():
        source = mapping["source"]
        try:
            template = payloads[source]
        except KeyError:
            raise _fail("NERIVANE_V2_PROMOTION_PAYLOAD_INVALID") from None
        observed_placeholders += template.count(placeholder_bytes)
        if b"assets/nerivane-public-v1" in template.lower():
            raise _fail("NERIVANE_V2_PROMOTION_V1_REFERENCE_FORBIDDEN")
        rendered = template.replace(placeholder_bytes, release_id.encode("ascii"))
        if placeholder_bytes in rendered:
            raise _fail("NERIVANE_V2_PROMOTION_PAYLOAD_INVALID")
        outputs[mapping["target"]] = rendered
    if observed_placeholders < 1:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_REFERENCE_MISSING")

    page = outputs["demonstrations/nerivane-distribution.html"]
    page_lower = page.lower()
    required_page_markers = (
        b'<!doctype html>',
        b'name="viewport"',
        b'../assets/css/site.css',
        b'../assets/css/demo-nerivane.css',
        b'../assets/js/demo-nerivane.js',
        b'../assets/js/audience-counter.js',
        b'<h1',
    )
    if (
        not all(marker in page_lower for marker in required_page_markers)
        or b"maintenance" in page_lower
        or b'data-maintenance="true"' in page_lower
    ):
        raise _fail("NERIVANE_V2_PROMOTION_PAGE_INVALID")
    css = outputs["assets/css/demo-nerivane.css"].lower()
    if b"@media" not in css:
        raise _fail("NERIVANE_V2_PROMOTION_RESPONSIVE_INVALID")
    try:
        json.loads(outputs["assets/data/nerivane-governance-replay.json"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("NERIVANE_V2_PROMOTION_DATA_INVALID") from None
    reference = f"assets/validated-releases/nerivane-v2/{release_id}".encode("ascii")
    if not any(reference in payload for payload in outputs.values()):
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_REFERENCE_MISSING")
    return outputs


def _active_outputs(
    site_root: Path,
    release_id: str,
    payloads: Mapping[str, bytes],
) -> dict[str, bytes]:
    outputs = _validate_activation_payloads(release_id, payloads)
    catalogue = _read_regular(site_root / "demonstrations.html")
    fragment_source = next(
        mapping["source"]
        for mapping in _mappings()
        if mapping["kind"] == "fragment"
    )
    placeholder = str(_contract()["release_id_placeholder"]).encode("ascii")
    fragment = payloads[fragment_source].replace(
        placeholder,
        release_id.encode("ascii"),
    )
    outputs["demonstrations.html"] = _replace_catalogue(catalogue, fragment)
    return outputs


def _path_inventory(path: Path, relative: str) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}

    def visit(current: Path, current_relative: str) -> None:
        try:
            metadata = current.lstat()
        except OSError:
            raise _fail("NERIVANE_V2_PROTECTED_TREE_INVALID") from None
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            raise _fail("NERIVANE_V2_PROTECTED_TREE_INVALID")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise _fail("NERIVANE_V2_PROTECTED_TREE_INVALID")
            try:
                payload = importer._read_regular(
                    current,
                    mode,
                    "NERIVANE_V2_PROTECTED_TREE_INVALID",
                )
            except importer.NerivaneReleaseImportError as error:
                raise _fail(error.code) from error
            result[current_relative] = {
                "kind": "file",
                "mode": mode,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise _fail("NERIVANE_V2_PROTECTED_TREE_INVALID")
        result[current_relative] = {"kind": "directory", "mode": mode}
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError:
            raise _fail("NERIVANE_V2_PROTECTED_TREE_INVALID") from None
        for entry in entries:
            visit(Path(entry.path), f"{current_relative}/{entry.name}")

    visit(path, relative)
    return result


def _protected_snapshot(site_root: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for relative in _protected_paths():
        snapshot.update(_path_inventory(site_root / relative, relative))
    return snapshot


def _target_snapshot(site_root: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for relative in _commit_order():
        path = site_root / relative
        payload = _read_regular(path)
        snapshot[relative] = {
            "mode": 0o644,
            "sha256": _sha256(payload),
            "size_bytes": len(payload),
        }
    return snapshot


def _transaction_root(site_root: Path) -> Path:
    return site_root.joinpath(*TRANSACTION_ROOT_RELATIVE.parts)


def _transaction_path(site_root: Path, release_id: str) -> Path:
    if importer.HASH_PATTERN.fullmatch(release_id) is None:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_ID_INVALID")
    return _transaction_root(site_root) / release_id


def _ensure_transaction_root(site_root: Path) -> Path:
    root = _transaction_root(site_root)
    parent = root.parent
    try:
        parent_metadata = parent.lstat()
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_ROOT_INVALID") from None
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
        raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_ROOT_INVALID")
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_ROOT_INVALID") from None
    try:
        metadata = root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_ROOT_INVALID")
        os.chmod(root, 0o700, follow_symlinks=False)
        importer._fsync_directory(parent)
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_ROOT_INVALID") from None
    return root


@contextmanager
def _promotion_lock(site_root: Path) -> Iterable[None]:
    root = _ensure_transaction_root(site_root)
    lock = root / ".lock"
    try:
        descriptor = os.open(
            lock,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_LOCK_INVALID") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise _fail("NERIVANE_V2_PROMOTION_LOCK_INVALID")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _fail("NERIVANE_V2_PROMOTION_BUSY") from None
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def _write_new_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_private_tree(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        os.chmod(directory, 0o700, follow_symlinks=False)
        importer._fsync_directory(directory)


def _journal_payload(
    *,
    release_id: str,
    phase: str,
    targets: Mapping[str, Mapping[str, object]],
    replacements: Mapping[str, bytes],
    protected: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    return {
        "contract_id": TRANSACTION_CONTRACT_ID,
        "phase": phase,
        "protected_before": protected,
        "release_id": release_id,
        "replacements": {
            path: {
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
            for path, payload in sorted(replacements.items())
        },
        "targets_before": targets,
        "transaction_version": TRANSACTION_VERSION,
    }


def _prepare_transaction(
    site_root: Path,
    release_id: str,
    outputs: Mapping[str, bytes],
) -> tuple[Path, dict[str, object]]:
    transaction_root = _ensure_transaction_root(site_root)
    transaction = transaction_root / release_id
    if transaction.exists() or transaction.is_symlink():
        return transaction, _read_journal(transaction, release_id)
    temporary: Path | None = None
    try:
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{release_id}.pending.",
                dir=transaction_root,
            )
        )
        targets = _target_snapshot(site_root)
        protected = _protected_snapshot(site_root)
        journal = _journal_payload(
            release_id=release_id,
            phase=PHASE_PREPARED,
            targets=targets,
            replacements=outputs,
            protected=protected,
        )
        for relative in _commit_order():
            _write_new_private(
                temporary.joinpath(*SNAPSHOT_ROOT.parts, *PurePosixPath(relative).parts),
                _read_regular(site_root / relative),
            )
            _write_new_private(
                temporary.joinpath(*REPLACEMENT_ROOT.parts, *PurePosixPath(relative).parts),
                outputs[relative],
            )
        _write_new_private(temporary / JOURNAL_PATH, _canonical_json_bytes(journal))
        _sync_private_tree(temporary)
        importer._rename_noreplace(temporary, transaction)
        importer._fsync_directory(transaction_root)
        temporary = None
        return transaction, journal
    except FileExistsError:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        return transaction, _read_journal(transaction, release_id)
    except (OSError, importer.NerivaneReleaseImportError) as error:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        raise _fail("NERIVANE_V2_PROMOTION_PREPARE_FAILED") from error


def _read_journal(transaction: Path, release_id: str) -> dict[str, object]:
    try:
        metadata = transaction.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise OSError("invalid transaction directory")
        payload = importer._read_regular(
            transaction / JOURNAL_PATH,
            0o600,
            "NERIVANE_V2_PROMOTION_STATE_INVALID",
        )
        journal = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, importer.NerivaneReleaseImportError):
        raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID") from None
    if (
        not isinstance(journal, dict)
        or set(journal) != {
            "contract_id",
            "phase",
            "protected_before",
            "release_id",
            "replacements",
            "targets_before",
            "transaction_version",
        }
        or journal.get("contract_id") != TRANSACTION_CONTRACT_ID
        or journal.get("transaction_version") != TRANSACTION_VERSION
        or journal.get("release_id") != release_id
        or journal.get("phase") not in ALLOWED_PHASES
        or not isinstance(journal.get("protected_before"), dict)
        or not isinstance(journal.get("replacements"), dict)
        or not isinstance(journal.get("targets_before"), dict)
        or set(journal["replacements"]) != set(_commit_order())
        or set(journal["targets_before"]) != set(_commit_order())
        or _canonical_json_bytes(journal) != payload
    ):
        raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
    for relative in _commit_order():
        before = journal["targets_before"].get(relative)
        replacement = journal["replacements"].get(relative)
        if (
            not isinstance(before, dict)
            or set(before) != {"mode", "sha256", "size_bytes"}
            or before.get("mode") != 0o644
            or not isinstance(before.get("sha256"), str)
            or importer.HASH_PATTERN.fullmatch(before["sha256"]) is None
            or type(before.get("size_bytes")) is not int
            or before["size_bytes"] < 1
            or not isinstance(replacement, dict)
            or set(replacement) != {"sha256", "size_bytes"}
            or not isinstance(replacement.get("sha256"), str)
            or importer.HASH_PATTERN.fullmatch(replacement["sha256"]) is None
            or type(replacement.get("size_bytes")) is not int
            or replacement["size_bytes"] < 1
        ):
            raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
        snapshot_payload = _transaction_payload(transaction, SNAPSHOT_ROOT, relative)
        replacement_payload = _transaction_payload(
            transaction,
            REPLACEMENT_ROOT,
            relative,
        )
        if (
            _sha256(snapshot_payload) != before["sha256"]
            or len(snapshot_payload) != before["size_bytes"]
            or _sha256(replacement_payload) != replacement["sha256"]
            or len(replacement_payload) != replacement["size_bytes"]
        ):
            raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
    return journal


def _write_phase(transaction: Path, journal: dict[str, object], phase: str) -> None:
    if phase not in ALLOWED_PHASES:
        raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
    updated = {**journal, "phase": phase}
    temporary = transaction / f".{JOURNAL_PATH}.tmp"
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        _write_new_private(temporary, _canonical_json_bytes(updated))
        os.replace(temporary, transaction / JOURNAL_PATH)
        importer._fsync_directory(transaction)
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_STATE_WRITE_FAILED") from None
    journal.clear()
    journal.update(updated)


def _before_atomic_publish(path: Path, temporary: Path) -> None:
    """Test hook reached after durable temp write and before file replacement."""


def _atomic_replace(
    path: Path,
    payload: bytes,
    release_id: str,
    mode: int = 0o644,
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.nerivane-v2-{release_id}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        _before_atomic_publish(path, temporary)
        os.replace(temporary, path)
        importer._fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _transaction_payload(
    transaction: Path,
    root: PurePosixPath,
    relative: str,
) -> bytes:
    try:
        return importer._read_regular(
            transaction.joinpath(*root.parts, *PurePosixPath(relative).parts),
            0o600,
            "NERIVANE_V2_PROMOTION_STATE_INVALID",
        )
    except importer.NerivaneReleaseImportError as error:
        raise _fail(error.code) from error


def _verify_target_hashes(
    site_root: Path,
    expected: Mapping[str, Mapping[str, object]],
) -> None:
    observed = _target_snapshot(site_root)
    if observed != expected:
        raise _fail("NERIVANE_V2_ACTIVE_STATE_DIVERGED")


def _replacement_records(transaction: Path) -> dict[str, dict[str, object]]:
    return {
        relative: {
            "mode": 0o644,
            "sha256": _sha256(
                _transaction_payload(transaction, REPLACEMENT_ROOT, relative)
            ),
            "size_bytes": len(
                _transaction_payload(transaction, REPLACEMENT_ROOT, relative)
            ),
        }
        for relative in _commit_order()
    }


def _before_commit(transaction: Path) -> None:
    """Test hook reached after durable preparation and before COMMITTING."""


def _after_target_committed(index: int, relative: str) -> None:
    """Test hook reached after each atomic target replacement."""


def _after_target_rolled_back(index: int, relative: str) -> None:
    """Test hook reached after each atomic rollback replacement."""


def _apply_transaction(
    site_root: Path,
    release_id: str,
    release: Path,
    transaction: Path,
    journal: dict[str, object],
) -> None:
    _write_phase(transaction, journal, PHASE_COMMITTING)
    try:
        for index, relative in enumerate(_commit_order()):
            payload = _transaction_payload(transaction, REPLACEMENT_ROOT, relative)
            _atomic_replace(site_root / relative, payload, release_id)
            _after_target_committed(index, relative)
        _verify_target_hashes(site_root, _replacement_records(transaction))
        if _protected_snapshot(site_root) != journal["protected_before"]:
            raise _fail("NERIVANE_V2_PROTECTED_TREE_CHANGED")
        try:
            importer._public_inventory(release)
        except importer.NerivaneReleaseImportError as error:
            raise _fail("NERIVANE_V2_PROMOTION_RELEASE_CHANGED") from error
        _write_phase(transaction, journal, PHASE_COMMITTED)
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        try:
            _rollback_transaction(site_root, transaction, journal)
        except NerivanePromotionError as rollback_error:
            raise _fail("NERIVANE_V2_PROMOTION_RECOVERY_REQUIRED") from rollback_error
        _remove_transaction(transaction)
        raise _fail("NERIVANE_V2_PROMOTION_FAILED_ROLLED_BACK") from error


def _rollback_transaction(
    site_root: Path,
    transaction: Path,
    journal: dict[str, object],
) -> None:
    release_id = str(journal["release_id"])
    _write_phase(transaction, journal, PHASE_ROLLING_BACK)
    for index, relative in enumerate(reversed(_commit_order())):
        payload = _transaction_payload(transaction, SNAPSHOT_ROOT, relative)
        before = journal["targets_before"][relative]
        if not isinstance(before, dict) or before.get("mode") != 0o644:
            raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
        _atomic_replace(
            site_root / relative,
            payload,
            release_id,
            int(before["mode"]),
        )
        _after_target_rolled_back(index, relative)
    _verify_target_hashes(site_root, journal["targets_before"])
    if _protected_snapshot(site_root) != journal["protected_before"]:
        raise _fail("NERIVANE_V2_PROTECTED_TREE_CHANGED")


def _remove_transaction(transaction: Path) -> None:
    root = transaction.parent
    try:
        shutil.rmtree(transaction)
        importer._fsync_directory(root)
    except OSError:
        raise _fail("NERIVANE_V2_PROMOTION_TRANSACTION_CLEANUP_FAILED") from None


def _cleanup_pending(site_root: Path, release_id: str) -> int:
    if importer.HASH_PATTERN.fullmatch(release_id) is None:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_ID_INVALID")
    root = _transaction_root(site_root)
    if not root.exists():
        return 0
    removed = 0
    for candidate in root.glob(f".{release_id}.pending.*"):
        try:
            metadata = candidate.lstat()
        except OSError:
            continue
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            shutil.rmtree(candidate, ignore_errors=True)
            if not candidate.exists():
                removed += 1
    if removed:
        importer._fsync_directory(root)
    return removed


def _cleanup_target_temporaries(site_root: Path, release_id: str) -> int:
    if importer.HASH_PATTERN.fullmatch(release_id) is None:
        raise _fail("NERIVANE_V2_PROMOTION_RELEASE_ID_INVALID")
    removed = 0
    observed_parents: set[Path] = set()
    for relative in _commit_order():
        target = site_root / relative
        parent = target.parent
        prefix = f".{target.name}.nerivane-v2-{release_id}."
        for candidate in parent.glob(f"{prefix}*"):
            try:
                metadata = candidate.lstat()
            except OSError:
                continue
            if (
                stat.S_ISREG(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and metadata.st_nlink == 1
            ):
                try:
                    candidate.unlink()
                except OSError:
                    raise _fail("NERIVANE_V2_PROMOTION_TEMP_CLEANUP_FAILED") from None
                removed += 1
                observed_parents.add(parent)
    for parent in observed_parents:
        importer._fsync_directory(parent)
    return removed


def _matches_outputs(site_root: Path, outputs: Mapping[str, bytes]) -> bool:
    return all(
        _read_regular(site_root / relative) == outputs[relative]
        for relative in _commit_order()
    )


def attest_maintenance(*, site_root: Path = importer.SITE_ROOT) -> dict[str, object]:
    root = _root(site_root)
    page = _read_regular(root / "demonstrations/nerivane-distribution.html")
    catalogue = _read_regular(root / "demonstrations.html")
    _, fragment, _, _ = _catalogue_parts(catalogue)
    if b'data-maintenance="true"' not in page.lower() or b"maintenance" not in fragment.lower():
        raise _fail("NERIVANE_V2_MAINTENANCE_ATTESTATION_FAILED")
    return {
        "state": "MAINTENANCE",
        "status": "ATTESTED",
        "target_count": len(_commit_order()),
    }


def attest_release(
    release_id: str,
    *,
    site_root: Path = importer.SITE_ROOT,
) -> dict[str, object]:
    root = _root(site_root)
    _, _, payloads = _release(root, release_id)
    outputs = _active_outputs(root, release_id, payloads)
    if not _matches_outputs(root, outputs):
        raise _fail("NERIVANE_V2_ACTIVE_ATTESTATION_FAILED")
    transaction = _transaction_path(root, release_id)
    if transaction.exists() or transaction.is_symlink():
        journal = _read_journal(transaction, release_id)
        if journal["phase"] != PHASE_COMMITTED:
            raise _fail("NERIVANE_V2_ACTIVE_ATTESTATION_FAILED")
        if _protected_snapshot(root) != journal["protected_before"]:
            raise _fail("NERIVANE_V2_PROTECTED_TREE_CHANGED")
    return {
        "release_id": release_id,
        "state": "ACTIVE",
        "status": "ATTESTED",
        "target_count": len(_commit_order()),
    }


def _recover_locked(
    root: Path,
    release_id: str,
) -> dict[str, object]:
    _cleanup_pending(root, release_id)
    _cleanup_target_temporaries(root, release_id)
    transaction = _transaction_path(root, release_id)
    if not transaction.exists() and not transaction.is_symlink():
        return {"release_id": release_id, "status": "NOTHING_TO_RECOVER"}
    journal = _read_journal(transaction, release_id)
    phase = journal["phase"]
    if phase == PHASE_COMMITTED:
        attest_release(release_id, site_root=root)
        return {"release_id": release_id, "status": "ALREADY_COMMITTED"}
    if phase == PHASE_PREPARED:
        try:
            _verify_target_hashes(root, journal["targets_before"])
        except NerivanePromotionError:
            _rollback_transaction(root, transaction, journal)
            status = "ROLLED_BACK"
        else:
            if _protected_snapshot(root) != journal["protected_before"]:
                raise _fail("NERIVANE_V2_PROTECTED_TREE_CHANGED")
            status = "PREPARED_DISCARDED"
    else:
        _rollback_transaction(root, transaction, journal)
        status = "ROLLED_BACK"
    _remove_transaction(transaction)
    return {"release_id": release_id, "status": status}


def recover_promotion(
    release_id: str,
    *,
    site_root: Path = importer.SITE_ROOT,
) -> dict[str, object]:
    root = _root(site_root)
    with _promotion_lock(root):
        return _recover_locked(root, release_id)


def promote_release(
    release_id: str,
    *,
    site_root: Path = importer.SITE_ROOT,
) -> dict[str, object]:
    root = _root(site_root)
    with _promotion_lock(root):
        release, _, payloads = _release(root, release_id)
        _cleanup_pending(root, release_id)
        _cleanup_target_temporaries(root, release_id)
        transaction = _transaction_path(root, release_id)
        if transaction.exists() or transaction.is_symlink():
            journal = _read_journal(transaction, release_id)
            if journal["phase"] == PHASE_COMMITTED:
                attest_release(release_id, site_root=root)
                return {
                    "release_id": release_id,
                    "state": "ACTIVE",
                    "status": "ALREADY_ACTIVE",
                }
            _recover_locked(root, release_id)

        outputs = _active_outputs(root, release_id, payloads)
        if _matches_outputs(root, outputs):
            return {
                "release_id": release_id,
                "state": "ACTIVE",
                "status": "ALREADY_ACTIVE",
            }
        attest_maintenance(site_root=root)
        transaction, journal = _prepare_transaction(root, release_id, outputs)
        if journal["phase"] != PHASE_PREPARED:
            raise _fail("NERIVANE_V2_PROMOTION_STATE_INVALID")
        _before_commit(transaction)
        _apply_transaction(root, release_id, release, transaction, journal)
        attest_release(release_id, site_root=root)
        return {
            "release_id": release_id,
            "state": "ACTIVE",
            "status": "PROMOTED",
        }


def rollback_release(
    release_id: str,
    *,
    site_root: Path = importer.SITE_ROOT,
) -> dict[str, object]:
    root = _root(site_root)
    with _promotion_lock(root):
        _cleanup_target_temporaries(root, release_id)
        transaction = _transaction_path(root, release_id)
        journal = _read_journal(transaction, release_id)
        if journal["phase"] != PHASE_COMMITTED:
            raise _fail("NERIVANE_V2_PROMOTION_NOT_COMMITTED")
        attest_release(release_id, site_root=root)
        _rollback_transaction(root, transaction, journal)
        attest_maintenance(site_root=root)
        _remove_transaction(transaction)
        return {
            "release_id": release_id,
            "state": "MAINTENANCE",
            "status": "ROLLED_BACK",
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--promote", metavar="RELEASE_ID")
    action.add_argument("--rollback", metavar="RELEASE_ID")
    action.add_argument("--recover", metavar="RELEASE_ID")
    action.add_argument("--attest-release", metavar="RELEASE_ID")
    action.add_argument("--attest-maintenance", action="store_true")
    parser.add_argument("--site-root", type=Path, default=importer.SITE_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.promote:
            result = promote_release(args.promote, site_root=args.site_root)
        elif args.rollback:
            result = rollback_release(args.rollback, site_root=args.site_root)
        elif args.recover:
            result = recover_promotion(args.recover, site_root=args.site_root)
        elif args.attest_release:
            result = attest_release(args.attest_release, site_root=args.site_root)
        else:
            result = attest_maintenance(site_root=args.site_root)
    except NerivanePromotionError as error:
        print(f"NERIVANE_V2_PROMOTION_FAILED: {error.code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
