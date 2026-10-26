"""Pure, bounded projection of the authorized 2026 spring-clock revision.

This module changes a derived public view, never observations or archived fits.
The producer first verifies every legacy scientific prefix. The site independently
verifies the corresponding legacy or revised immutable profiles before migration.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DELIVERY_REVISION = "h-paris-spring-2026-03-29-v1"
TRANSLATION_MM = 0.0508
FIRST_REVISED_ORIGIN = 34
SOURCE_CLOCK_REVISION = {
    "version": 1,
    "id": DELIVERY_REVISION,
    "clock_hypothesis": "H_PARIS",
    "timezone": "Europe/Paris",
    "trusted_utc": False,
    "source_values_rewritten": False,
    "source_timestamps_rewritten": False,
    "historical_technical_origins_preserved": True,
    "corrected_transitions": [{
        "date": "2026-03-29",
        "kind": "SPRING_GAP",
        "previous_origin_id": 33,
        "origin_id": 34,
        "source_line": 2069214,
        "source_delta_seconds": 3630.499958,
        "elapsed_seconds_under_clock_hypothesis": 30.499958,
        "removed_graphical_offset_mm": -0.0508,
    }],
}


def _translated(value: Any) -> Any:
    return None if value is None else round(float(value) + TRANSLATION_MM, 12)


def project_dynamic_replacements(value: dict[str, Any]) -> dict[str, Any]:
    """Project once with one identical rounding rule in producer and consumer."""
    result = deepcopy(value)
    metadata = result["metadata"]
    if "source_clock_revision" in metadata:
        raise ValueError("CLOCK_REVISION_ALREADY_PROJECTED")
    for name, origin_index, columns in (
        ("global_hourly", 2, (4, 5, 6)),
        ("global_daily", 2, (7, 8, 9)),
        ("thermal_extended", 4, (6, 7, 10, 22, 24)),
    ):
        for row in result[name]:
            if FIRST_REVISED_ORIGIN <= row[origin_index] <= 36:
                for column in columns:
                    row[column] = _translated(row[column])
    metadata["source_clock_revision"] = deepcopy(SOURCE_CLOCK_REVISION)
    metadata["thermal_extension"]["sg5_identity_max_abs_error_mm"] = max(
        (
            abs(row[24] - (row[22] - row[23]))
            for row in result["thermal_extended"]
            if row[25] == "AVAILABLE"
        ),
        default=0.0,
    )
    return result


def project_full_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Project the full, previously validated legacy public payload exactly once."""
    result = project_dynamic_replacements(value)
    matches = [row for row in result["offsets"] if row[3] == FIRST_REVISED_ORIGIN]
    if len(matches) != 1:
        raise ValueError("CLOCK_REVISION_BOUNDARY_MISSING")
    boundary = matches[0]
    if (
        boundary[1] != "2026-03-29 03:00:00"
        or boundary[2] != 33
        or boundary[4] is not True
        or abs(boundary[9] + TRANSLATION_MM) > 1e-10
        or boundary[17] != 2069214
    ):
        raise ValueError("CLOCK_REVISION_BOUNDARY_DIVERGED")
    for row in result["offsets"]:
        if FIRST_REVISED_ORIGIN <= row[3] <= 36:
            row[10] = _translated(row[10])
    boundary[4] = False
    boundary[5] = "NO_GRAPHICAL_OFFSET_CLOCK_CHANGE"
    boundary[6] = "CHANGEMENT_HEURE_SOUS_H_PARIS;ORIGINE_TECHNIQUE_CONSERVEE"
    boundary[8] = "CLOCK_CHANGE_NOT_ACQUISITION_GAP"
    boundary[9] = 0.0
    boundary[21] = "O_s=O_(s-1);NO_OFFSET_FOR_DOCUMENTED_CLOCK_STEP"
    resumptions = [row for row in result["resumptions"] if row[3] == FIRST_REVISED_ORIGIN]
    if len(resumptions) != 1 or resumptions[0][4] != "REPRISE-L2069214":
        raise ValueError("CLOCK_REVISION_RESUMPTION_DIVERGED")
    # Preserve the literal civil-time delta; the evidence above supplies the
    # hypothesized acquisition interval without inventing a trusted UTC clock.
    resumptions[0][5] = "DOCUMENTED_SPRING_CLOCK_STEP_H_PARIS"
    for row in result["origin_starts"]:
        if row[3] == FIRST_REVISED_ORIGIN:
            row[4] = "ORIGINE-34-IDENTIFIANT-TECHNIQUE-CHANGEMENT-HEURE"
    offsets = result["metadata"]["offsets"]
    offsets["applied_offset_count"] = 35
    offsets["non_applied_boundary_count"] = 1
    offsets["nonzero_translation_count"] = 19
    offsets["uncertain_reanchor_count"] = 35
    offsets["formula"] = "O_s=O_(s-1)+last_hourly_mm_(s-1)-first_hourly_mm_s;CLOCK_STEP_34_OFFSET=0"
    repair = result["metadata"]["graphical_alignment_repair"]
    repair["all_boundaries_graphically_anchored"] = False
    repair["id"] = "GRAPHICAL_ENDPOINT_CHAIN_EXCEPT_DOCUMENTED_CLOCK_STEP"
    return result


def project_review_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    """Annotate the full historical review, not its six-field dynamic update."""
    if "segmentation" not in value or "source_clock_revision" in value:
        raise ValueError("CLOCK_REVISION_FULL_LEGACY_REVIEW_REQUIRED")
    result = deepcopy(value)
    result["source_clock_revision"] = deepcopy(SOURCE_CLOCK_REVISION)
    return result
