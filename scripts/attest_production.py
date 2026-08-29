#!/usr/bin/env python3
"""Attest that the deployed Demo 2 files match the versioned site tree."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


FIGURE_ROOT = PurePosixPath("assets/figures/demo-2")
FIGURE_MANIFESTS = (
    FIGURE_ROOT / "content-manifest.json",
    FIGURE_ROOT / "weather/content-manifest.json",
)
INTEGRATION_PATHS = (
    PurePosixPath("demonstrations/fissures.html"),
    PurePosixPath("demonstrations.html"),
    PurePosixPath("assets/js/demo-fissures.js"),
    PurePosixPath("assets/css/demo-fissures.css"),
    FIGURE_ROOT / "content-manifest.json",
    FIGURE_ROOT / "weather/content-manifest.json",
    PurePosixPath("sitemap.xml"),
)
EXPECTED_FIGURE_COUNT = 14
CHUNK_SIZE = 1024 * 1024


class AttestationError(RuntimeError):
    """The expected tree or its deployed representation is not attestable."""


@dataclass(frozen=True)
class ExpectedFile:
    path: PurePosixPath
    sha256: str
    size_bytes: int
    category: str


@dataclass(frozen=True)
class ObservedFile:
    sha256: str
    size_bytes: int


def _digest_file(path: Path) -> ObservedFile:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return ObservedFile(digest.hexdigest(), size)


def _repository_path(root: Path, relative: PurePosixPath) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise AttestationError(f"chemin attendu non sûr : {relative}")
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise AttestationError(f"chemin attendu hors dépôt : {relative}") from exc
    return candidate


def _load_manifest(root: Path, relative: PurePosixPath) -> list[ExpectedFile]:
    manifest_path = _repository_path(root, relative)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"manifeste local illisible : {relative} : {exc}") from exc

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise AttestationError(f"manifeste local sans liste de fichiers : {relative}")

    expected: list[ExpectedFile] = []
    manifest_directory = relative.parent
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("role") != "responsive_html_master":
            continue
        entry_path = entry.get("path")
        sha256 = entry.get("sha256")
        size_bytes = entry.get("size_bytes")
        if (
            not isinstance(entry_path, str)
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            raise AttestationError(f"entrée de maître invalide dans {relative}")
        deployed_path = manifest_directory / PurePosixPath(entry_path)
        if deployed_path.suffix.lower() not in {".html", ".htm"}:
            raise AttestationError(f"maître non HTML dans {relative} : {entry_path}")
        local_path = _repository_path(root, deployed_path)
        if not local_path.is_file():
            raise AttestationError(f"maître local absent : {deployed_path}")
        observed = _digest_file(local_path)
        if observed.sha256 != sha256 or observed.size_bytes != size_bytes:
            raise AttestationError(
                f"maître local divergent de {relative} : {deployed_path} "
                f"(sha256={observed.sha256}, taille={observed.size_bytes})"
            )
        expected.append(ExpectedFile(deployed_path, sha256, size_bytes, "figure"))
    return expected


def load_expected_files(root: Path) -> tuple[ExpectedFile, ...]:
    """Load and validate the closed set of 14 figures and 7 integration files."""
    root = root.resolve()
    figures = [
        expected
        for manifest in FIGURE_MANIFESTS
        for expected in _load_manifest(root, manifest)
    ]
    figure_paths = [expected.path for expected in figures]
    if len(figures) != EXPECTED_FIGURE_COUNT or len(set(figure_paths)) != len(figures):
        raise AttestationError(
            f"exactement {EXPECTED_FIGURE_COUNT} maîtres HTML uniques attendus, "
            f"trouvé : {len(figures)} ({len(set(figure_paths))} uniques)"
        )

    integrations: list[ExpectedFile] = []
    for relative in INTEGRATION_PATHS:
        local_path = _repository_path(root, relative)
        if not local_path.is_file():
            raise AttestationError(f"fichier d’intégration local absent : {relative}")
        observed = _digest_file(local_path)
        integrations.append(
            ExpectedFile(relative, observed.sha256, observed.size_bytes, "integration")
        )

    all_paths = [expected.path for expected in (*figures, *integrations)]
    if len(set(all_paths)) != len(all_paths):
        raise AttestationError("chemin dupliqué entre figures et fichiers d’intégration")
    return tuple((*figures, *integrations))


def _download_digest(url: str, timeout_seconds: float) -> ObservedFile:
    request = Request(url, headers={"User-Agent": "datapredict-production-attestation/1"})
    digest = hashlib.sha256()
    size = 0
    with urlopen(request, timeout=timeout_seconds) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise AttestationError(f"HTTP {status} pour {url}")
        while chunk := response.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return ObservedFile(digest.hexdigest(), size)


def _remote_url(base_url: str, path: PurePosixPath) -> str:
    return f"{base_url.rstrip('/')}/{quote(path.as_posix(), safe='/')}"


def attest(
    root: Path,
    base_url: str,
    *,
    attempts: int = 1,
    retry_delay_seconds: float = 0,
    timeout_seconds: float = 45,
) -> tuple[ExpectedFile, ...]:
    """Verify every expected file, retrying each failed observation a bounded amount."""
    if attempts < 1:
        raise AttestationError("attempts doit être supérieur ou égal à 1")
    if retry_delay_seconds < 0 or timeout_seconds <= 0:
        raise AttestationError("les délais doivent être positifs")

    expected_files = load_expected_files(root)
    for expected in expected_files:
        url = _remote_url(base_url, expected.path)
        last_error = "échec non précisé"
        for attempt in range(1, attempts + 1):
            try:
                observed = _download_digest(url, timeout_seconds)
                if (
                    observed.sha256 == expected.sha256
                    and observed.size_bytes == expected.size_bytes
                ):
                    print(
                        f"OK {expected.category} {expected.path} "
                        f"sha256={observed.sha256} taille={observed.size_bytes}"
                    )
                    break
                last_error = (
                    f"contenu divergent : sha256 attendu={expected.sha256}, "
                    f"observé={observed.sha256}; taille attendue={expected.size_bytes}, "
                    f"observée={observed.size_bytes}"
                )
            except (AttestationError, HTTPError, URLError, OSError) as exc:
                last_error = f"téléchargement impossible : {exc}"

            if attempt < attempts:
                time.sleep(retry_delay_seconds)
        else:
            raise AttestationError(
                f"{expected.path} non attesté après {attempts} tentative(s) : {last_error}"
            )
    return expected_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="racine du dépôt contenant les attentes versionnées",
    )
    parser.add_argument(
        "--base-url",
        default="https://www.datapredict.org",
        help="origine HTTPS à attester",
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        expected = attest(
            args.root,
            args.base_url,
            attempts=args.attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except AttestationError as exc:
        print(f"ATTESTATION_FAILED: {exc}", file=sys.stderr)
        return 1

    figure_count = sum(item.category == "figure" for item in expected)
    integration_count = sum(item.category == "integration" for item in expected)
    total_size = sum(item.size_bytes for item in expected)
    print(
        "ATTESTATION_OK "
        f"figures={figure_count} integration={integration_count} "
        f"fichiers={len(expected)} octets={total_size} base={args.base_url.rstrip('/')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
