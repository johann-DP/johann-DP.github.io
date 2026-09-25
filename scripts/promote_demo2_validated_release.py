#!/usr/bin/env python3
"""Promote validated Demo 2 data into the approved public masters atomically.

Only data-bearing regions are copied from an imported validated release.  The
current public HTML remains the visual template.  The complete figure subtree
is exchanged atomically and the previous subtree is retained for recovery.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence

import import_demo2_validated_release as importer
import refresh_demo2_live_data as live_refresh
import validate_demo2_active_figures as active_validator


SITE_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ROOT_RELATIVE = PurePosixPath("assets/figures/demo-2")
TRANSACTION_ROOT_RELATIVE = PurePosixPath(
    "assets/validated-releases/.demo2-promotions"
)
JOURNAL_NAME = "transaction.json"
COUNTERPART_NAME = "counterpart"
LOCK_NAME = ".lock"
PHASE_PREPARED = "PREPARED"
PHASE_COMMITTING = "COMMITTING"
PHASE_COMMITTED = "COMMITTED"
PHASE_ROLLED_BACK = "ROLLED_BACK"
PHASES = {PHASE_PREPARED, PHASE_COMMITTING, PHASE_COMMITTED, PHASE_ROLLED_BACK}
MAX_SENSOR_MASTER_BYTES = 2_000_000
MAX_SENSOR_POINTS = 12_000


class Demo2PromotionError(RuntimeError):
    """Stable fail-closed publication error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> Demo2PromotionError:
    return Demo2PromotionError(code)


PROMOTION_TARGETS: Mapping[str, Mapping[str, tuple[str, str, str]]] = {
    "retaining_wall_sensor_review": {
        "retaining-wall-source-values": (
            "retaining-wall-sensor-raw.html",
            "retaining-wall-sensor-source-values.html",
            "sensor",
        ),
    },
    "retaining_wall_sensor_pattern_review": {
        "retaining-wall-extrema-hours": (
            "retaining-wall-extrema-hours.html",
            "retaining-wall-extrema-hours.html",
            "pattern",
        ),
        "retaining-wall-median-day": (
            "retaining-wall-median-day.html",
            "retaining-wall-median-day.html",
            "pattern",
        ),
    },
    "weather_complement_review": {
        "weather-explorer": (
            "complements/meteo_explorateur_toutes_mesures.html",
            "weather/complements/meteo_explorateur_toutes_mesures.html",
            "complement",
        ),
        "weather-quality": (
            "complements/meteo_qualite_acquisition.html",
            "weather/complements/meteo_qualite_acquisition.html",
            "complement",
        ),
    },
    "weather_legacy_temperature_review": {
        "weather-temperature": (
            "weather/legacy/meteo_temperature.html",
            "weather/legacy/meteo_temperature.html",
            "plotly-data",
        ),
    },
    "weather_legacy_minmax_review": {
        "weather-temperature-range": (
            "weather/legacy/meteo_temp_minmax.html",
            "weather/legacy/meteo_temp_minmax.html",
            "plotly-data",
        ),
    },
    "weather_legacy_humidity_review": {
        "weather-humidity": (
            "weather/legacy/meteo_humidity.html",
            "weather/legacy/meteo_humidity.html",
            "plotly-data",
        ),
    },
    "weather_legacy_light_uv_review": {
        "weather-light": (
            "weather/legacy/meteo_light_uv.html",
            "weather/legacy/meteo_light_uv.html",
            "plotly-data",
        ),
    },
    "weather_legacy_precipitation_review": {
        "weather-rainfall": (
            "weather/legacy/meteo_precipitation.html",
            "weather/legacy/meteo_precipitation.html",
            "plotly-data",
        ),
    },
    "weather_legacy_wind_speed_review": {
        "weather-wind-speed": (
            "weather/legacy/meteo_wind_speed.html",
            "weather/legacy/meteo_wind_speed.html",
            "plotly-data",
        ),
    },
    "weather_legacy_pairplots_review": {
        "weather-pairplots": (
            "weather/legacy/meteo_pairplots.html",
            "weather/legacy/meteo_pairplots.html",
            "plotly-data",
        ),
    },
}

# Deliberately absent: manual raw pages never replace the validated analytical
# crack/joint masters, and wind direction is explicitly frozen by its owner.

PREPARED_OUTPUT_STRATEGIES: Mapping[str, str] = {
    "fissure-recente-meme-format.html": "manual",
    "joint-dilatation-rendu-site.html": "manual",
    "retaining-wall-sensor-source-values.html": "sensor",
    "retaining-wall-sensor-processed-v2.html": "processed",
    "weather/complements/meteo_explorateur_toutes_mesures.html": "complement",
    "weather/complements/meteo_qualite_acquisition.html": "complement",
    "weather/legacy/meteo_humidity.html": "plotly-data",
    "weather/legacy/meteo_light_uv.html": "plotly-data",
    "weather/legacy/meteo_pairplots.html": "plotly-data",
    "weather/legacy/meteo_precipitation.html": "plotly-data",
    "weather/legacy/meteo_temp_minmax.html": "plotly-data",
    "weather/legacy/meteo_temperature.html": "plotly-data",
    "weather/legacy/meteo_wind_speed.html": "plotly-data",
}

# The two pattern figures are refreshed only from a coherent, explicitly
# validated pattern release.  Wind direction is frozen by an explicit owner
# decision.  Neither class is accepted by the live prepared-output interface.
PREPARED_OUTPUT_FROZEN = frozenset(
    {
        "retaining-wall-extrema-hours.html",
        "retaining-wall-median-day.html",
        "weather/legacy/meteo_wind_dir.html",
    }
)
SOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
HTML_PARAGRAPH = re.compile(r"<p\b[^>]*>.*?</p>", re.IGNORECASE | re.DOTALL)
SENSOR_CANDIDATE_MARKER = re.compile(r"candidat\s+automatis", re.IGNORECASE)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise _fail("DEMO2_PROMOTION_STATE_INVALID") from None
    return f"{rendered}\n".encode("utf-8")


def _site_root(path: Path) -> Path:
    try:
        return importer._site_root(path)
    except importer.SiteReleaseImportError as error:
        raise _fail("DEMO2_PROMOTION_SITE_ROOT_INVALID") from error


def _read_regular(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except OSError:
        raise _fail("DEMO2_PROMOTION_TARGET_INVALID") from None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise _fail("DEMO2_PROMOTION_TARGET_INVALID")
    try:
        return path.read_bytes()
    except OSError:
        raise _fail("DEMO2_PROMOTION_TARGET_INVALID") from None


def _release(site_root: Path, release_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    if importer.HASH_PATTERN.fullmatch(release_id) is None:
        raise _fail("DEMO2_PROMOTION_RELEASE_ID_INVALID")
    root = site_root.joinpath(*importer.DESTINATION_RELATIVE.parts, release_id)
    try:
        _, payloads = importer._public_bundle(root)
        approval, _ = importer._parse_approval(payloads[importer.APPROVAL_PATH])
    except (importer.SiteReleaseImportError, KeyError) as error:
        raise _fail("DEMO2_PROMOTION_RELEASE_INVALID") from error
    return approval, dict(payloads)


def _runtime_paths(release_kind: str) -> tuple[str, str]:
    if release_kind == "weather_complement_review":
        return importer.WEATHER_PLOTLY, importer.WEATHER_PLOTLY_LICENSE
    return importer.PLOTLY, importer.PLOTLY_LICENSE


def _verify_runtime(active_root: Path, release_kind: str, payloads: Mapping[str, bytes]) -> None:
    runtime, license_path = _runtime_paths(release_kind)
    for source in (runtime, license_path):
        try:
            candidate = payloads[source]
        except KeyError:
            raise _fail("DEMO2_PROMOTION_RUNTIME_INVALID") from None
        active = _read_regular(active_root / "weather/assets" / PurePosixPath(source).name)
        if candidate != active:
            raise _fail("DEMO2_PROMOTION_RUNTIME_DIVERGED")


def _script_body_span(text: str, identifier: str) -> tuple[int, int]:
    pattern = re.compile(
        rf'<script\b(?=[^>]*\bid=["\']{re.escape(identifier)}["\'])[^>]*>',
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    close = text.lower().find("</script>", matches[0].end())
    if close < 0:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    return matches[0].end(), close


def _assignment_span(text: str, name: str) -> tuple[int, int]:
    prefix = f"const {name} = "
    start = text.find(prefix)
    if start < 0 or text.find(prefix, start + 1) >= 0:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    value_start = start + len(prefix)
    end = text.find(";", value_start)
    if end < 0:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    return value_start, end


def _section_span(text: str, css_class: str) -> tuple[int, int]:
    pattern = re.compile(
        rf'<section\b(?=[^>]*\bclass=["\'][^"\']*\b{re.escape(css_class)}\b[^"\']*["\'])[^>]*>.*?</section>',
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    return matches[0].start(), matches[0].end()


def _fact_spans(text: str) -> tuple[tuple[int, int], ...]:
    pattern = re.compile(
        r'<div\b(?=[^>]*\bclass=["\'][^"\']*\bfact\b[^"\']*["\'])[^>]*>.*?</div>',
        re.IGNORECASE | re.DOTALL,
    )
    spans = tuple((match.start(), match.end()) for match in pattern.finditer(text))
    if not spans:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    return spans


def _replace_spans(text: str, replacements: Iterable[tuple[int, int, str]]) -> str:
    ordered = sorted(replacements, key=lambda item: item[0])
    if any(start < 0 or end < start for start, end, _ in ordered):
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    output: list[str] = []
    cursor = 0
    for start, end, value in ordered:
        output.extend((text[cursor:start], value))
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _javascript_arguments(text: str) -> tuple[tuple[int, int], ...]:
    marker = "Plotly.newPlot("
    starts = [match.start() for match in re.finditer(re.escape(marker), text)]
    if len(starts) != 1:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    cursor = starts[0] + len(marker)
    argument_start = cursor
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    arguments: list[tuple[int, int]] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    while cursor < len(text):
        character = text[cursor]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in {"'", '"', "`"}:
            quote = character
        elif character in pairs:
            stack.append(pairs[character])
        elif character in {")",
            "]",
            "}",
        }:
            if character == ")" and not stack:
                arguments.append((argument_start, cursor))
                break
            if not stack or stack.pop() != character:
                raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
        elif character == "," and not stack:
            arguments.append((argument_start, cursor))
            argument_start = cursor + 1
        cursor += 1
    if len(arguments) < 3:
        raise _fail("DEMO2_PROMOTION_TEMPLATE_INVALID")
    return tuple(arguments)


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("DEMO2_PROMOTION_HTML_INVALID") from None


def _reject_internal_text(*fragments: str) -> None:
    text = " ".join(fragments).casefold()
    if any(marker in text for marker in active_validator.FORBIDDEN_VISIBLE_MARKERS):
        raise _fail("DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN")


def _merge_plotly_data(current: str, candidate: str) -> str:
    current_arguments = _javascript_arguments(current)
    candidate_arguments = _javascript_arguments(candidate)
    current_data = current_arguments[1]
    candidate_data = candidate_arguments[1]
    candidate_fragment = candidate[candidate_data[0] : candidate_data[1]]
    _reject_internal_text(candidate_fragment)
    current_skeleton = _replace_spans(current, [(*current_data, "__DEMO2_DATA__")])
    candidate_skeleton = _replace_spans(candidate, [(*candidate_data, "__DEMO2_DATA__")])
    if current_skeleton != candidate_skeleton:
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    return _replace_spans(current, [(*current_data, candidate_fragment)])


def _merge_pattern(current: str, candidate: str) -> str:
    current_payload = _script_body_span(current, "pattern-payload")
    candidate_payload = _script_body_span(candidate, "pattern-payload")
    current_cards = _section_span(current, "cards")
    candidate_cards = _section_span(candidate, "cards")
    try:
        json.loads(candidate[candidate_payload[0] : candidate_payload[1]])
    except json.JSONDecodeError:
        raise _fail("DEMO2_PROMOTION_DATA_INVALID") from None
    _reject_internal_text(
        candidate[candidate_payload[0] : candidate_payload[1]],
        candidate[candidate_cards[0] : candidate_cards[1]],
    )
    current_skeleton = _replace_spans(
        current,
        [(*current_payload, "__DEMO2_DATA__"), (*current_cards, "__DEMO2_CARDS__")],
    )
    candidate_skeleton = _replace_spans(
        candidate,
        [(*candidate_payload, "__DEMO2_DATA__"), (*candidate_cards, "__DEMO2_CARDS__")],
    )
    if current_skeleton != candidate_skeleton:
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    return _replace_spans(
        current,
        [
            (*current_payload, candidate[candidate_payload[0] : candidate_payload[1]]),
            (*current_cards, candidate[candidate_cards[0] : candidate_cards[1]]),
        ],
    )


def _merge_complement(current: str, candidate: str) -> str:
    current_payload = _script_body_span(current, "payload")
    candidate_payload = _script_body_span(candidate, "payload")
    try:
        json.loads(candidate[candidate_payload[0] : candidate_payload[1]])
    except json.JSONDecodeError:
        raise _fail("DEMO2_PROMOTION_DATA_INVALID") from None
    _reject_internal_text(candidate[candidate_payload[0] : candidate_payload[1]])
    current_facts = _fact_spans(current)
    candidate_facts = _fact_spans(candidate)
    if len(current_facts) != len(candidate_facts):
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    current_skeleton = _replace_spans(
        current,
        [(*current_payload, "__DEMO2_DATA__")]
        + [(*span, f"__DEMO2_FACT_{index}__") for index, span in enumerate(current_facts)],
    )
    candidate_skeleton = _replace_spans(
        candidate,
        [(*candidate_payload, "__DEMO2_DATA__")]
        + [(*span, f"__DEMO2_FACT_{index}__") for index, span in enumerate(candidate_facts)],
    )
    if current_skeleton != candidate_skeleton:
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    replacements = [
        (*current_payload, candidate[candidate_payload[0] : candidate_payload[1]])
    ]
    replacements.extend(
        (*current_span, candidate[candidate_span[0] : candidate_span[1]])
        for current_span, candidate_span in zip(current_facts, candidate_facts)
    )
    return _replace_spans(current, replacements)


def _merge_sensor(
    current: str,
    candidate: str,
    *,
    strip_candidate_marker: bool,
) -> str:
    if len(candidate.encode("utf-8")) > MAX_SENSOR_MASTER_BYTES:
        raise _fail("DEMO2_PROMOTION_SENSOR_TOO_LARGE")
    if strip_candidate_marker:
        candidate_paragraphs = [
            match
            for match in HTML_PARAGRAPH.finditer(candidate)
            if SENSOR_CANDIDATE_MARKER.search(match.group(0))
        ]
        if len(candidate_paragraphs) != 1:
            raise _fail("DEMO2_PROMOTION_SENSOR_CANDIDATE_MARKER_INVALID")
        paragraph = candidate_paragraphs[0]
        candidate = candidate[: paragraph.start()] + candidate[paragraph.end() :]
    current_payload = _script_body_span(current, "d2-cap-payload")
    candidate_payload = _script_body_span(candidate, "d2-cap-payload")
    current_metadata = _assignment_span(current, "FIGURE_METADATA")
    candidate_metadata = _assignment_span(candidate, "FIGURE_METADATA")
    try:
        metadata = json.loads(candidate[candidate_metadata[0] : candidate_metadata[1]])
    except json.JSONDecodeError:
        raise _fail("DEMO2_PROMOTION_DATA_INVALID") from None
    _reject_internal_text(
        candidate[candidate_payload[0] : candidate_payload[1]],
        candidate[candidate_metadata[0] : candidate_metadata[1]],
    )
    rendering = metadata.get("rendering") if isinstance(metadata, dict) else None
    transformations = rendering.get("transformations") if isinstance(rendering, dict) else None
    count = rendering.get("coordinate_count") if isinstance(rendering, dict) else None
    if (
        type(count) is not int
        or count < 1
        or count > MAX_SENSOR_POINTS
        or not isinstance(transformations, dict)
        or transformations.get("downsampling_applied") is not True
    ):
        raise _fail("DEMO2_PROMOTION_SENSOR_SAMPLING_INVALID")
    current_skeleton = _replace_spans(
        current,
        [(*current_payload, "__DEMO2_DATA__"), (*current_metadata, "__DEMO2_METADATA__")],
    )
    candidate_skeleton = _replace_spans(
        candidate,
        [(*candidate_payload, "__DEMO2_DATA__"), (*candidate_metadata, "__DEMO2_METADATA__")],
    )
    if current_skeleton != candidate_skeleton:
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    return _replace_spans(
        current,
        [
            (*current_payload, candidate[candidate_payload[0] : candidate_payload[1]]),
            (*current_metadata, candidate[candidate_metadata[0] : candidate_metadata[1]]),
        ],
    )


def merge_data_only(current: bytes, candidate: bytes, strategy: str) -> bytes:
    current_text = _decode(current)
    candidate_text = _decode(candidate)
    if not candidate_text.lower().startswith("<!doctype html>"):
        raise _fail("DEMO2_PROMOTION_HTML_INVALID")
    if strategy == "plotly-data":
        merged = _merge_plotly_data(current_text, candidate_text)
    elif strategy == "pattern":
        merged = _merge_pattern(current_text, candidate_text)
    elif strategy == "complement":
        merged = _merge_complement(current_text, candidate_text)
    elif strategy == "sensor":
        merged = _merge_sensor(
            current_text,
            candidate_text,
            strip_candidate_marker=True,
        )
    elif strategy == "processed":
        try:
            merged = live_refresh.validate_processed_transition(
                current, candidate
            ).decode("utf-8")
        except (live_refresh.RefreshError, UnicodeDecodeError) as error:
            raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED") from error
    else:
        raise _fail("DEMO2_PROMOTION_MAPPING_INVALID")
    payload = merged.encode("utf-8")
    try:
        markers = active_validator.forbidden_visible_markers(payload)
    except active_validator.Demo2FigureValidationError as error:
        raise _fail("DEMO2_PROMOTION_HTML_INVALID") from error
    if markers:
        raise _fail("DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN")
    return payload


def _merge_prepared_output(current: bytes, prepared: bytes, strategy: str) -> bytes:
    """Re-prove a prepared live output against the current visual master."""
    if type(prepared) is not bytes or not prepared:
        raise _fail("DEMO2_PROMOTION_PREPARED_PAYLOAD_INVALID")
    if not prepared.lower().startswith(b"<!doctype html>"):
        raise _fail("DEMO2_PROMOTION_HTML_INVALID")
    if strategy == "manual":
        _reject_internal_text(_decode(prepared))
        try:
            if (
                live_refresh.manual_data_only_skeleton(current)
                != live_refresh.manual_data_only_skeleton(prepared)
            ):
                raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
        except live_refresh.RefreshError as error:
            raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED") from error
        try:
            markers = active_validator.forbidden_visible_markers(prepared)
        except active_validator.Demo2FigureValidationError as error:
            raise _fail("DEMO2_PROMOTION_HTML_INVALID") from error
        if markers:
            raise _fail("DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN")
        return prepared
    if strategy == "sensor":
        current_text = _decode(current)
        prepared_text = _decode(prepared)
        if not prepared_text.lower().startswith("<!doctype html>"):
            raise _fail("DEMO2_PROMOTION_HTML_INVALID")
        merged = _merge_sensor(
            current_text,
            prepared_text,
            strip_candidate_marker=False,
        ).encode("utf-8")
        try:
            markers = active_validator.forbidden_visible_markers(merged)
        except active_validator.Demo2FigureValidationError as error:
            raise _fail("DEMO2_PROMOTION_HTML_INVALID") from error
        if markers:
            raise _fail("DEMO2_PROMOTION_INTERNAL_TEXT_FORBIDDEN")
    else:
        merged = merge_data_only(current, prepared, strategy)
    if merged != prepared:
        raise _fail("DEMO2_PROMOTION_VISUAL_TEMPLATE_DIVERGED")
    return merged


def _prepared_target(value: PurePosixPath | str) -> str:
    if not isinstance(value, (str, PurePosixPath)):
        raise _fail("DEMO2_PROMOTION_PREPARED_TARGET_INVALID")
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    relative = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or relative.is_absolute()
        or relative.as_posix() != raw
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _fail("DEMO2_PROMOTION_PREPARED_TARGET_INVALID")
    prefix = ACTIVE_ROOT_RELATIVE.parts
    if relative.parts[: len(prefix)] == prefix:
        relative = PurePosixPath(*relative.parts[len(prefix) :])
    target = relative.as_posix()
    if target in PREPARED_OUTPUT_FROZEN:
        raise _fail("DEMO2_PROMOTION_TARGET_FROZEN")
    if target not in PREPARED_OUTPUT_STRATEGIES:
        raise _fail("DEMO2_PROMOTION_PREPARED_TARGET_FORBIDDEN")
    return target


def _source_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise _fail("DEMO2_PROMOTION_SOURCE_SET_INVALID")
    identifiers = tuple(values)
    if (
        not identifiers
        or len(set(identifiers)) != len(identifiers)
        or any(
            not isinstance(identifier, str)
            or SOURCE_ID_PATTERN.fullmatch(identifier) is None
            for identifier in identifiers
        )
    ):
        raise _fail("DEMO2_PROMOTION_SOURCE_SET_INVALID")
    return identifiers


def _collect_prepared_outputs(
    active_root: Path,
    outputs: Mapping[PurePosixPath | str, bytes],
) -> dict[str, bytes]:
    if not isinstance(outputs, Mapping) or not outputs:
        raise _fail("DEMO2_PROMOTION_PREPARED_SET_INVALID")
    prepared: dict[str, bytes] = {}
    for raw_target, payload in outputs.items():
        target = _prepared_target(raw_target)
        if target in prepared:
            raise _fail("DEMO2_PROMOTION_PREPARED_TARGET_AMBIGUOUS")
        prepared[target] = _merge_prepared_output(
            _read_regular(active_root / target),
            payload,
            PREPARED_OUTPUT_STRATEGIES[target],
        )
    return prepared


def _manifest_entry_path(target: str) -> tuple[str, str]:
    if target.startswith("weather/"):
        return active_validator.WEATHER_MANIFEST_RELATIVE, target.removeprefix("weather/")
    return active_validator.ROOT_MANIFEST_RELATIVE, target


def _update_manifests(active_root: Path, outputs: Mapping[str, bytes]) -> None:
    grouped: dict[str, dict[str, bytes]] = {}
    for target, payload in outputs.items():
        manifest, entry = _manifest_entry_path(target)
        grouped.setdefault(manifest, {})[entry] = payload
    for manifest_relative, replacements in grouped.items():
        path = active_root / manifest_relative
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise _fail("DEMO2_PROMOTION_MANIFEST_INVALID") from None
        records = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(records, list):
            raise _fail("DEMO2_PROMOTION_MANIFEST_INVALID")
        observed: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or set(record) != active_validator.ENTRY_KEYS:
                raise _fail("DEMO2_PROMOTION_MANIFEST_INVALID")
            relative = record.get("path")
            if relative in replacements:
                payload = replacements[relative]
                record["sha256"] = _sha256(payload)
                record["size_bytes"] = len(payload)
                observed.add(relative)
        if observed != set(replacements):
            raise _fail("DEMO2_PROMOTION_MANIFEST_INVALID")
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _tree_digest(root: Path) -> str:
    records: list[dict[str, object]] = []
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError:
        raise _fail("DEMO2_PROMOTION_TREE_INVALID") from None
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            metadata = path.lstat()
        except OSError:
            raise _fail("DEMO2_PROMOTION_TREE_INVALID") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise _fail("DEMO2_PROMOTION_TREE_INVALID")
        if stat.S_ISREG(metadata.st_mode):
            payload = path.read_bytes()
            records.append({"path": relative, "sha256": _sha256(payload), "size_bytes": len(payload)})
        elif not stat.S_ISDIR(metadata.st_mode):
            raise _fail("DEMO2_PROMOTION_TREE_INVALID")
    return _sha256(_canonical_json(records))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_journal(transaction: Path, journal: Mapping[str, object]) -> None:
    temporary = transaction / f".{JOURNAL_NAME}.pending"
    payload = _canonical_json(dict(journal))
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short write")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, transaction / JOURNAL_NAME)
    _fsync_directory(transaction)


def _set_phase(transaction: Path, journal: dict[str, Any], phase: str) -> None:
    if phase not in PHASES:
        raise _fail("DEMO2_PROMOTION_STATE_INVALID")
    journal["phase"] = phase
    _write_journal(transaction, journal)


def _rename_exchange(left: Path, right: Path) -> None:
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise _fail("DEMO2_PROMOTION_ATOMIC_EXCHANGE_UNAVAILABLE") from None
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    if function(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        number = ctypes.get_errno()
        if number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise _fail("DEMO2_PROMOTION_ATOMIC_EXCHANGE_UNAVAILABLE")
        raise OSError(number, os.strerror(number))


@contextmanager
def _lock(transaction_root: Path):
    transaction_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        transaction_root / LOCK_NAME,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_tree(site_root: Path, active_root: Path) -> None:
    if active_root != site_root.joinpath(*ACTIVE_ROOT_RELATIVE.parts):
        raise _fail("DEMO2_PROMOTION_TREE_INVALID")
    try:
        active_validator.validate_active_figure_tree(site_root=site_root)
    except (active_validator.Demo2FigureValidationError, OSError) as error:
        raise _fail("DEMO2_PROMOTION_ACTIVE_TREE_INVALID") from error


def _collect_outputs(
    site_root: Path,
    active_root: Path,
    release_ids: Iterable[str],
) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}
    identifiers = tuple(release_ids)
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise _fail("DEMO2_PROMOTION_RELEASE_SET_INVALID")
    for release_id in identifiers:
        approval, payloads = _release(site_root, release_id)
        release_kind = approval["source"]["release_kind"]
        mappings = PROMOTION_TARGETS.get(release_kind)
        if mappings is None:
            raise _fail("DEMO2_PROMOTION_RELEASE_KIND_FORBIDDEN")
        _verify_runtime(active_root, release_kind, payloads)
        for selected in approval["selected_figures"]:
            logical_id = selected["logical_figure_id"]
            mapping = mappings.get(logical_id)
            if mapping is None:
                raise _fail("DEMO2_PROMOTION_FIGURE_FORBIDDEN")
            source, target, strategy = mapping
            if source != selected["release_path"] or target in outputs:
                raise _fail("DEMO2_PROMOTION_MAPPING_INVALID")
            outputs[target] = merge_data_only(
                _read_regular(active_root / target),
                payloads[source],
                strategy,
            )
    return outputs


def _after_exchange() -> None:
    """Test hook executed after the new subtree becomes visible."""


def _promote_outputs_locked(
    root: Path,
    active_root: Path,
    transaction_root: Path,
    outputs: Mapping[str, bytes],
    source_ids: Sequence[str],
) -> dict[str, object]:
    """Activate already proved outputs while the caller holds the site lock."""
    old_digest = _tree_digest(active_root)
    changed = {
        target: payload
        for target, payload in outputs.items()
        if _read_regular(active_root / target) != payload
    }
    if not changed:
        return {
            "active_tree_sha256": old_digest,
            "source_ids": list(source_ids),
            "status": "ALREADY_ACTIVE",
            "updated_master_count": 0,
        }

    identity = {
        "old_tree_sha256": old_digest,
        "output_sha256": {
            target: _sha256(payload) for target, payload in sorted(changed.items())
        },
        "source_ids": list(source_ids),
        "targets": sorted(changed),
    }
    transaction_id = _sha256(_canonical_json(identity))
    transaction = transaction_root / transaction_id
    counterpart = transaction / COUNTERPART_NAME
    try:
        transaction.mkdir(mode=0o700)
    except FileExistsError:
        raise _fail("DEMO2_PROMOTION_TRANSACTION_EXISTS") from None
    try:
        shutil.copytree(active_root, counterpart, copy_function=shutil.copy2)
        for target, payload in changed.items():
            destination = counterpart / target
            destination.write_bytes(payload)
            os.chmod(destination, 0o644, follow_symlinks=False)
        _update_manifests(counterpart, changed)

        # Validate the complete replacement while the public tree is still untouched.
        shadow_root = transaction / "shadow-site"
        shadow_root.mkdir(mode=0o700)
        (shadow_root / "assets/figures").mkdir(parents=True)
        os.rename(counterpart, shadow_root / "assets/figures/demo-2")
        for relative in ("demonstrations.html", "demonstrations/fissures.html"):
            source = root / relative
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
        try:
            active_validator.validate_active_figure_tree(site_root=shadow_root)
        except (active_validator.Demo2FigureValidationError, OSError) as error:
            raise _fail("DEMO2_PROMOTION_REPLACEMENT_INVALID") from error
        os.rename(shadow_root / "assets/figures/demo-2", counterpart)
        shutil.rmtree(shadow_root)

        new_digest = _tree_digest(counterpart)
        journal: dict[str, Any] = {
            "counterpart": COUNTERPART_NAME,
            "new_tree_sha256": new_digest,
            "old_tree_sha256": old_digest,
            "phase": PHASE_PREPARED,
            "source_ids": list(source_ids),
            "targets": sorted(changed),
            "transaction_id": transaction_id,
            "version": 2,
        }
        _write_journal(transaction, journal)
        _set_phase(transaction, journal, PHASE_COMMITTING)
        exchanged = False
        try:
            _rename_exchange(active_root, counterpart)
            exchanged = True
            _fsync_directory(active_root.parent)
            _fsync_directory(transaction)
            _after_exchange()
            _validate_tree(root, active_root)
            if (
                _tree_digest(active_root) != new_digest
                or _tree_digest(counterpart) != old_digest
            ):
                raise _fail("DEMO2_PROMOTION_POST_COMMIT_DIVERGED")
            _set_phase(transaction, journal, PHASE_COMMITTED)
        except Exception as error:
            if exchanged:
                try:
                    _rename_exchange(active_root, counterpart)
                    _fsync_directory(active_root.parent)
                    _fsync_directory(transaction)
                except Exception as rollback_error:
                    raise _fail("DEMO2_PROMOTION_ROLLBACK_FAILED") from rollback_error
            if _tree_digest(active_root) != old_digest:
                raise _fail("DEMO2_PROMOTION_ROLLBACK_DIVERGED") from error
            _set_phase(transaction, journal, PHASE_ROLLED_BACK)
            raise _fail("DEMO2_PROMOTION_FAILED_ROLLED_BACK") from error
    except Exception:
        # PREPARED failures never touched the public tree.
        if _tree_digest(active_root) != old_digest:
            raise
        raise
    return {
        "active_tree_sha256": new_digest,
        "previous_tree_sha256": old_digest,
        "source_ids": list(source_ids),
        "status": "PROMOTED",
        "transaction_id": transaction_id,
        "updated_master_count": len(changed),
    }


def promote_validated_releases(
    release_ids: Iterable[str], *, site_root: Path = SITE_ROOT
) -> dict[str, object]:
    root = _site_root(site_root)
    active_root = root.joinpath(*ACTIVE_ROOT_RELATIVE.parts)
    transaction_root = root.joinpath(*TRANSACTION_ROOT_RELATIVE.parts)
    identifiers = tuple(release_ids)
    with _lock(transaction_root):
        _validate_tree(root, active_root)
        outputs = _collect_outputs(root, active_root, identifiers)
        result = _promote_outputs_locked(
            root,
            active_root,
            transaction_root,
            outputs,
            identifiers,
        )
    result["release_ids"] = list(identifiers)
    return result


def promote_prepared_outputs(
    outputs: Mapping[PurePosixPath | str, bytes],
    source_ids: Sequence[str],
    *,
    site_root: Path = SITE_ROOT,
) -> dict[str, object]:
    """Atomically publish refresh outputs after independently re-proving them.

    Keys may be relative to the Demo 2 figure root or use the site-relative
    ``assets/figures/demo-2/`` prefix emitted by ``build_staging``.
    """
    identifiers = _source_ids(source_ids)
    root = _site_root(site_root)
    active_root = root.joinpath(*ACTIVE_ROOT_RELATIVE.parts)
    transaction_root = root.joinpath(*TRANSACTION_ROOT_RELATIVE.parts)
    with _lock(transaction_root):
        _validate_tree(root, active_root)
        prepared = _collect_prepared_outputs(active_root, outputs)
        return _promote_outputs_locked(
            root,
            active_root,
            transaction_root,
            prepared,
            identifiers,
        )


def _journal(transaction: Path) -> dict[str, Any]:
    try:
        value = json.loads((transaction / JOURNAL_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _fail("DEMO2_PROMOTION_STATE_INVALID") from None
    required = {
        "counterpart",
        "new_tree_sha256",
        "old_tree_sha256",
        "phase",
        "source_ids",
        "targets",
        "transaction_id",
        "version",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("version") != 2
        or value.get("phase") not in PHASES
        or value.get("counterpart") != COUNTERPART_NAME
        or value.get("transaction_id") != transaction.name
        or importer.HASH_PATTERN.fullmatch(str(value.get("old_tree_sha256"))) is None
        or importer.HASH_PATTERN.fullmatch(str(value.get("new_tree_sha256"))) is None
        or not isinstance(value.get("source_ids"), list)
        or not value["source_ids"]
        or any(
            not isinstance(identifier, str)
            or SOURCE_ID_PATTERN.fullmatch(identifier) is None
            for identifier in value["source_ids"]
        )
        or not isinstance(value.get("targets"), list)
        or not value["targets"]
        or any(
            not isinstance(target, str)
            or target not in active_validator.HTML_MASTER_PATHS
            for target in value["targets"]
        )
    ):
        raise _fail("DEMO2_PROMOTION_STATE_INVALID")
    return value


def recover_transaction(
    transaction_id: str, *, site_root: Path = SITE_ROOT
) -> dict[str, object]:
    if importer.HASH_PATTERN.fullmatch(transaction_id) is None:
        raise _fail("DEMO2_PROMOTION_TRANSACTION_ID_INVALID")
    root = _site_root(site_root)
    active_root = root.joinpath(*ACTIVE_ROOT_RELATIVE.parts)
    transaction_root = root.joinpath(*TRANSACTION_ROOT_RELATIVE.parts)
    with _lock(transaction_root):
        transaction = transaction_root / transaction_id
        journal = _journal(transaction)
        counterpart = transaction / COUNTERPART_NAME
        active_digest = _tree_digest(active_root)
        counterpart_digest = _tree_digest(counterpart)
        old_digest = journal["old_tree_sha256"]
        new_digest = journal["new_tree_sha256"]
        phase = journal["phase"]
        if phase == PHASE_COMMITTED:
            if active_digest != new_digest or counterpart_digest != old_digest:
                raise _fail("DEMO2_PROMOTION_RECOVERY_DIVERGED")
            _validate_tree(root, active_root)
            status = "COMMITTED"
        elif phase == PHASE_ROLLED_BACK:
            if active_digest != old_digest or counterpart_digest != new_digest:
                raise _fail("DEMO2_PROMOTION_RECOVERY_DIVERGED")
            _validate_tree(root, active_root)
            status = "ROLLED_BACK"
        elif active_digest == old_digest and counterpart_digest == new_digest:
            _set_phase(transaction, journal, PHASE_ROLLED_BACK)
            _validate_tree(root, active_root)
            status = "ROLLED_BACK"
        elif active_digest == new_digest and counterpart_digest == old_digest:
            _rename_exchange(active_root, counterpart)
            _fsync_directory(active_root.parent)
            _fsync_directory(transaction)
            if _tree_digest(active_root) != old_digest:
                raise _fail("DEMO2_PROMOTION_RECOVERY_DIVERGED")
            _set_phase(transaction, journal, PHASE_ROLLED_BACK)
            _validate_tree(root, active_root)
            status = "ROLLED_BACK"
        else:
            raise _fail("DEMO2_PROMOTION_RECOVERY_DIVERGED")
        return {"status": status, "transaction_id": transaction_id}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--release-id", action="append", dest="release_ids")
    action.add_argument("--recover", metavar="TRANSACTION_ID")
    action.add_argument("--verify-active", action="store_true")
    parser.add_argument("--site-root", type=Path, default=SITE_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.recover:
            result = recover_transaction(args.recover, site_root=args.site_root)
        elif args.verify_active:
            result = active_validator.validate_active_figure_tree(site_root=args.site_root)
        else:
            result = promote_validated_releases(args.release_ids, site_root=args.site_root)
    except (Demo2PromotionError, active_validator.Demo2FigureValidationError, OSError) as error:
        code = getattr(error, "code", "DEMO2_PROMOTION_FAILED")
        print(f"DEMO2_PROMOTION_FAILED: {code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
