#!/usr/bin/env python3
"""Fail-closed, data-only refresh for the validated Demo 2 masters.

This module deliberately does not know how measurements are calculated.  It
accepts approved ``.READY`` HTML payloads (or already-refreshed manual bytes),
proves that their presentation is unchanged, and returns a complete staging
mapping.  Callers may write that mapping only after this function succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Mapping


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
FROZEN = frozenset(("retaining-wall-extrema-hours.html", "retaining-wall-median-day.html"))
_SCRIPT_PAYLOAD = re.compile(br'(<script id="payload" type="application/json">)(.*?)(</script>)', re.S)
_RAW_PAYLOAD = re.compile(br'(<script id="d2-cap-payload"[^>]*>)(.*?)(</script>)', re.S)
_FIGURE_METADATA = re.compile(br'const\s+FIGURE_METADATA\s*=\s*\{.*?\};', re.S)
_PARAGRAPH = re.compile(br"<p\b[^>]*>.*?</p>", re.I | re.S)
_STRONG = re.compile(br'(<strong(?:\s+[^>]*)?>)(.*?)(</strong>)', re.S)
_MEASURE_COUNT = re.compile(br"\b[0-9]+(?=\s+mesures\b)")


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


def _verified_ready_inventory(root: Path) -> dict[str, bytes]:
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
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RefreshError("REFRESH_READY_MANIFEST_INVALID") from error
    records = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(records, list):
        raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
    release_id = manifest.get("release_id")
    if release_id is not None and release_id != root.name:
        raise RefreshError("REFRESH_READY_MANIFEST_INVALID")
    payloads: dict[str, bytes] = {}
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
        if (
            type(record["size_bytes"]) is not int
            or record["size_bytes"] != len(content)
            or not isinstance(record["sha256"], str)
            or HASH.fullmatch(record["sha256"]) is None
            or hashlib.sha256(content).hexdigest() != record["sha256"]
        ):
            raise RefreshError("REFRESH_READY_MANIFEST_DIVERGED")
        expected.add(relative)
        if path.suffix.lower() in {".html", ".htm"}:
            payloads[relative] = content
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed != expected:
        raise RefreshError("REFRESH_READY_INVENTORY_DIVERGED")
    return payloads


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


def ready_payloads(roots: Iterable[Path]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for root in roots:
        for relative, payload in _verified_ready_inventory(Path(root)).items():
            if relative in found:
                raise RefreshError("REFRESH_READY_CANDIDATE_AMBIGUOUS")
            found[relative] = payload
    return found


def build_staging(active_root: Path, ready_roots: Iterable[Path], *, manual: Mapping[str, bytes] | None = None) -> dict[PurePosixPath, bytes]:
    """Return every approved replacement, or fail before returning any mapping."""
    active_root = Path(active_root)
    candidates = ready_payloads(ready_roots)
    staged: dict[PurePosixPath, bytes] = {}
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
