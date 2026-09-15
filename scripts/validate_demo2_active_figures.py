#!/usr/bin/env python3
"""Validate the rotating, public Demo 2 figure inventory.

The manifests are allowed to rotate when data changes.  Their schema, paths,
roles, file inventory and internal hashes are not.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Iterable, Mapping


SITE_ROOT = Path(__file__).resolve().parents[1]
FIGURE_ROOT_RELATIVE = PurePosixPath("assets/figures/demo-2")
ENTRY_KEYS = {"path", "role", "sha256", "size_bytes"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)

ROOT_ENTRIES: Mapping[str, str] = {
    "01-historical-crack-analysis-compacted-v2.html": "responsive_html_master",
    "01-historical-crack-analysis-compacted-v2.png": "desktop_validation_reference",
    "building-geometry.html": "responsive_html_master",
    "diagrams/structural-monitoring-layout.svg": "responsive_vector_asset",
    "fissure-recente-meme-format.html": "responsive_html_master",
    "joint-dilatation-rendu-site.html": "responsive_html_master",
    "retaining-wall-extrema-hours.html": "responsive_html_master",
    "retaining-wall-median-day.html": "responsive_html_master",
    "retaining-wall-sensor-source-values.html": "responsive_html_master",
}

WEATHER_ENTRIES: Mapping[str, str] = {
    "assets/plotly-2.35.2.min.js": "third_party_runtime",
    "assets/plotly-2.35.2.min.js.LICENSE.txt": "third_party_license",
    "complements/meteo_explorateur_toutes_mesures.html": "responsive_html_master",
    "complements/meteo_qualite_acquisition.html": "responsive_html_master",
    "index.html": "validated_weather_catalog",
    "legacy/meteo_humidity.html": "responsive_html_master",
    "legacy/meteo_light_uv.html": "responsive_html_master",
    "legacy/meteo_pairplots.html": "responsive_html_master",
    "legacy/meteo_precipitation.html": "responsive_html_master",
    "legacy/meteo_temp_minmax.html": "responsive_html_master",
    "legacy/meteo_temperature.html": "responsive_html_master",
    "legacy/meteo_wind_dir.html": "responsive_html_master",
    "legacy/meteo_wind_speed.html": "responsive_html_master",
}

ROOT_MANIFEST_RELATIVE = "content-manifest.json"
WEATHER_MANIFEST_RELATIVE = "weather/content-manifest.json"
WEATHER_VALIDATION = {
    "scientific_interpretation": "not_claimed",
    "state": "VALIDÉ",
    "validated_html_masters": 10,
}

HTML_MASTER_PATHS = frozenset(
    path for path, role in ROOT_ENTRIES.items() if role == "responsive_html_master"
) | frozenset(
    f"weather/{path}"
    for path, role in WEATHER_ENTRIES.items()
    if role == "responsive_html_master"
)

FORBIDDEN_VISIBLE_MARKERS = (
    "validation requise",
    "candidat de revue",
    "candidat automatisé",
    "candidate brute",
    "exécuté_non_validé",
    "revue humaine requise",
    "agrégation legacy",
    "calculs legacy",
    "hors cluster",
    "two_views_only",
    "rotate_90_ccw",
    "revue de la géométrie",
)


class Demo2FigureValidationError(RuntimeError):
    """Stable validation failure containing all detected errors."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def visible_text(payload: bytes) -> str:
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Demo2FigureValidationError(("HTML Demo 2 non UTF-8",)) from error
    parser = _VisibleText()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as error:
        raise Demo2FigureValidationError(("HTML Demo 2 non analysable",)) from error
    return " ".join(parser.parts)


def forbidden_visible_markers(payload: bytes) -> tuple[str, ...]:
    text = visible_text(payload).casefold()
    return tuple(marker for marker in FORBIDDEN_VISIBLE_MARKERS if marker in text)


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None
    return value


def _read_regular(path: Path, errors: list[str], label: str) -> bytes | None:
    try:
        metadata = path.lstat()
    except OSError:
        errors.append(f"fichier Demo 2 absent : {label}")
        return None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        errors.append(f"fichier Demo 2 non régulier : {label}")
        return None
    try:
        return path.read_bytes()
    except OSError:
        errors.append(f"fichier Demo 2 illisible : {label}")
        return None


def _manifest(
    figure_root: Path,
    relative: str,
    expected_entries: Mapping[str, str],
    errors: list[str],
) -> tuple[set[Path], int]:
    manifest_path = figure_root / relative
    payload = _read_regular(manifest_path, errors, relative)
    if payload is None:
        return {manifest_path.resolve()}, 0
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        errors.append(f"manifeste Demo 2 invalide : {relative}")
        return {manifest_path.resolve()}, 0

    if relative == ROOT_MANIFEST_RELATIVE:
        expected_keys = {"files", "manifest_version"}
        expected_version = 2
    else:
        expected_keys = {"files", "manifest_version", "validation"}
        expected_version = 1
    if not isinstance(value, dict) or set(value) != expected_keys:
        errors.append(f"schéma de manifeste Demo 2 invalide : {relative}")
        return {manifest_path.resolve()}, 0
    if type(value["manifest_version"]) is not int or value["manifest_version"] != expected_version:
        errors.append(f"version de manifeste Demo 2 invalide : {relative}")
    if relative == WEATHER_MANIFEST_RELATIVE and value.get("validation") != WEATHER_VALIDATION:
        errors.append("état de validation du manifeste météo invalide")

    raw_entries = value.get("files")
    if not isinstance(raw_entries, list):
        errors.append(f"liste de fichiers Demo 2 invalide : {relative}")
        return {manifest_path.resolve()}, 0

    base = manifest_path.parent
    observed: dict[str, str] = {}
    expected_files = {manifest_path.resolve()}
    masters = 0
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
            errors.append(f"entrée de manifeste Demo 2 invalide : {relative}")
            continue
        entry_path = _safe_relative(raw.get("path"))
        role = raw.get("role")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if (
            entry_path is None
            or not isinstance(role, str)
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or type(size) is not int
            or size < 0
        ):
            errors.append(f"entrée de manifeste Demo 2 mal typée : {relative}")
            continue
        if entry_path in observed:
            errors.append(f"chemin Demo 2 dupliqué : {entry_path}")
            continue
        observed[entry_path] = role
        candidate = (base / entry_path).resolve()
        try:
            candidate.relative_to(figure_root)
        except ValueError:
            errors.append(f"chemin de figure hors racine : {entry_path}")
            continue
        expected_files.add(candidate)
        file_payload = _read_regular(candidate, errors, candidate.relative_to(figure_root).as_posix())
        if file_payload is not None:
            if len(file_payload) != size:
                errors.append(f"taille de figure divergente : {entry_path}")
            if hashlib.sha256(file_payload).hexdigest() != digest:
                errors.append(f"empreinte de figure divergente : {entry_path}")
        if role == "responsive_html_master":
            masters += 1

    if observed != dict(expected_entries):
        missing = sorted(set(expected_entries) - set(observed))
        extra = sorted(set(observed) - set(expected_entries))
        wrong_roles = sorted(
            path
            for path in set(observed) & set(expected_entries)
            if observed[path] != expected_entries[path]
        )
        errors.append(
            "inventaire logique Demo 2 divergent "
            f"({relative}; absents={missing}; supplémentaires={extra}; rôles={wrong_roles})"
        )
    return expected_files, masters


def _maintenance(site_root: Path, errors: list[str]) -> None:
    page = _read_regular(
        site_root / "demonstrations/fissures.html",
        errors,
        "demonstrations/fissures.html",
    )
    catalogue = _read_regular(site_root / "demonstrations.html", errors, "demonstrations.html")
    if page is not None and (
        b'data-maintenance="true"' not in page
        or "Démonstration 2 · En maintenance".encode() not in page
    ):
        errors.append("la démonstration 2 publique doit rester En maintenance")
    if catalogue is not None:
        try:
            text = catalogue.decode("utf-8")
        except UnicodeDecodeError:
            errors.append("catalogue des démonstrations non UTF-8")
            return
        match = re.search(
            r'<a class="demonstrations-page__card-link" '
            r'href="demonstrations/fissures\.html".*?</a>',
            text,
            flags=re.DOTALL,
        )
        if match is None or "En maintenance" not in match.group(0) or "Consulter la version en maintenance" not in match.group(0):
            errors.append("la carte publique Demo 2 doit rester En maintenance")


def validate_active_figure_tree(
    *, site_root: Path = SITE_ROOT, require_maintenance: bool = True
) -> dict[str, object]:
    root = Path(os.path.abspath(site_root)).resolve(strict=True)
    figure_root = (root / FIGURE_ROOT_RELATIVE).resolve(strict=True)
    errors: list[str] = []
    expected_files: set[Path] = set()
    root_files, root_masters = _manifest(
        figure_root, ROOT_MANIFEST_RELATIVE, ROOT_ENTRIES, errors
    )
    weather_files, weather_masters = _manifest(
        figure_root, WEATHER_MANIFEST_RELATIVE, WEATHER_ENTRIES, errors
    )
    expected_files |= root_files | weather_files

    observed_files: set[Path] = set()
    for candidate in figure_root.rglob("*"):
        try:
            metadata = candidate.lstat()
        except OSError:
            errors.append(f"entrée Demo 2 illisible : {candidate.relative_to(figure_root)}")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            errors.append(f"lien symbolique Demo 2 interdit : {candidate.relative_to(figure_root)}")
        elif stat.S_ISREG(metadata.st_mode):
            observed_files.add(candidate.resolve())
        elif not stat.S_ISDIR(metadata.st_mode):
            errors.append(f"entrée spéciale Demo 2 interdite : {candidate.relative_to(figure_root)}")
    if observed_files != expected_files:
        missing = sorted(str(path.relative_to(figure_root)) for path in expected_files - observed_files)
        extra = sorted(str(path.relative_to(figure_root)) for path in observed_files - expected_files)
        errors.append(f"sous-arbre Demo 2 divergent (absents={missing}; supplémentaires={extra})")

    master_count = root_masters + weather_masters
    if master_count != 17:
        errors.append(f"17 maîtres HTML attendus, trouvé : {master_count}")

    for relative in sorted(HTML_MASTER_PATHS):
        payload = _read_regular(figure_root / relative, errors, relative)
        if payload is None:
            continue
        try:
            markers = forbidden_visible_markers(payload)
        except Demo2FigureValidationError as error:
            errors.extend(error.errors)
            continue
        if markers:
            errors.append(f"terme interne visible dans {relative} : {', '.join(markers)}")

    sensor = _read_regular(
        figure_root / "retaining-wall-sensor-source-values.html",
        errors,
        "retaining-wall-sensor-source-values.html",
    )
    if sensor is not None:
        required_sensor_markers = (
            "temps source naïf — fuseau à confirmer",
            "valeur source — unité à confirmer",
            "Aucune correction, conversion, interpolation, jointure, causalité ni diagnostic",
            'src="weather/assets/plotly-2.35.2.min.js"',
        )
        try:
            sensor_text = sensor.decode("utf-8")
        except UnicodeDecodeError:
            errors.append("figure brute D2-CAP non UTF-8")
        else:
            for marker in required_sensor_markers:
                if marker not in sensor_text:
                    errors.append(f"figure brute D2-CAP : mention obligatoire absente : {marker}")
            if re.search(r'(?:src|href)=["\']https?://', sensor_text, re.IGNORECASE):
                errors.append("figure brute D2-CAP : dépendance réseau interdite")

    if require_maintenance:
        _maintenance(root, errors)
    if errors:
        raise Demo2FigureValidationError(errors)
    return {
        "figure_file_count": len(observed_files),
        "html_master_count": master_count,
        "state": "VALIDÉ",
        "status": "VERIFIED",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, default=SITE_ROOT)
    parser.add_argument("--without-maintenance-check", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_active_figure_tree(
            site_root=args.site_root,
            require_maintenance=not args.without_maintenance_check,
        )
    except (Demo2FigureValidationError, OSError) as error:
        messages = getattr(error, "errors", (str(error),))
        print("\n".join(f"DEMO2_ACTIVE_FIGURES_INVALID: {item}" for item in messages), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
