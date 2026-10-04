"""Causal scope checks for the two input-bound manual model refits."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refresh_demo2_live_data as refresh  # noqa: E402
import promote_demo2_validated_release as promoter  # noqa: E402


ROOT = Path(__file__).resolve().parents[1] / "assets/figures/demo-2"
RECENT = (ROOT / "fissure-recente-meme-format.html").read_bytes()
JOINT = (ROOT / "joint-dilatation-rendu-site.html").read_bytes()


def assignment(payload: bytes, variable: bytes, change) -> bytes:
    value, start, end = refresh._json_assignment(payload, variable)
    change(value)
    return payload[:start] + json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + payload[end:]


def daily(start: str, end: str) -> list[str]:
    first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    return [(first + timedelta(days=index)).isoformat() for index in range((last - first).days + 1)]


def change_layouts(payload: bytes, change) -> bytes:
    if b"const payload = " in payload:
        def apply(value):
            for layout in value["layouts"].values():
                change(layout)
        return assignment(payload, b"payload", apply)
    layouts, spans = refresh._recent_layout_assignments(payload)
    for layout, (start, end) in reversed(list(zip(layouts, spans))):
        change(layout)
        payload = payload[:start] + json.dumps(layout, ensure_ascii=False, separators=(",", ":")).encode() + payload[end:]
    return payload


def expand_ranges(payload: bytes) -> bytes:
    value, _, _ = refresh._json_assignment(payload, b"payload" if b"const payload = " in payload else b"data")
    data = value["data"] if isinstance(value, dict) else value
    axes = {}
    for trace in data:
        axes.setdefault("yaxis2" if trace.get("yaxis") == "y2" else "yaxis", []).extend(value for value in trace["y"] if value is not None)
    def expand(layout):
        for axis, values in axes.items():
            margin = max(0.002, 0.03 * (max(values) - min(values)))
            low, high = layout[axis]["range"]
            layout[axis]["range"] = [min(low, min(values) - margin), max(high, max(values) + margin)]
    return change_layouts(payload, expand)


def recent_ordinate(day: int, *, slope: float = 0.0001, curvature: float = 0.004) -> float:
    return 31 + (slope * day if curvature < 1e-10 else slope * math.expm1(min(curvature * day, 50)) / curvature)


def joint_ordinate(date: str, *, period: float = 368.2, amplitude: float = 0.725,
                   phase_days: float = 0, slope: float = 0.0001) -> float:
    days = (datetime.fromisoformat(date) - datetime(2026, 1, 9)).total_seconds() / 86400
    return round(90.3 + slope * days + amplitude * math.cos(2 * math.pi * (days - phase_days) / period), 7)


def recent_candidate() -> bytes:
    def refit(data):
        data[0]["x"].append("2026-10-04T00:00:00")
        data[0]["y"].append(31.23)
        data[3]["x"] = daily("2025-12-28", "2026-10-04")
        data[3]["y"] = [recent_ordinate(index) for index in range(len(data[3]["x"]))]
        lookup = dict(zip(data[3]["x"], data[3]["y"]))
        data[13]["y"] = [lookup[date] for date in data[13]["x"]]
    return expand_ranges(assignment(RECENT, b"data", refit).replace(b"137 mesures", b"138 mesures"))


def joint_candidate(template: bytes | None = None, *, append: bool = True) -> bytes:
    def refit(value):
        data = value["data"]
        if append:
            data[0]["x"].append("2026-10-04T00:00:00")
            data[0]["y"].append(90.3)
        data[1]["x"] = daily(data[0]["x"][0], data[0]["x"][-1])
        data[1]["y"] = [joint_ordinate(date) for date in data[1]["x"]]
        last = datetime(2026, 1, 9)
        first = last - timedelta(days=368.2)
        base, peak = 90.3, 91.025
        for layout in value["layouts"].values():
            shapes, annotations = layout["shapes"], layout["annotations"]
            shapes[0].update(x0=first.isoformat(), x1=last.isoformat())
            shapes[1].update(x0=first.isoformat(), x1=first.isoformat())
            shapes[2].update(x0=last.isoformat(), x1=last.isoformat())
            shapes[3].update(x0=last.isoformat(), x1=last.isoformat(), y0=base, y1=peak)
            shapes[4].update(x0=(last - timedelta(days=22)).isoformat(), x1=(last + timedelta(days=22)).isoformat(), y0=base, y1=base)
            shapes[5].update(x0=(last - timedelta(days=10)).isoformat(), x1=(last + timedelta(days=10)).isoformat(), y0=peak, y1=peak)
            annotations[0].update(x=(first + (last - first) / 2).isoformat(), text="P = 368,2 jours")
            annotations[1].update(x=last.isoformat(), y=(base + peak) / 2, text="A = 0,725 mm")
            text = annotations[2]["text"]
            match = refresh._JOINT_SUMMARY.fullmatch(text)
            numbers = ("368,2", "357,0", "380,0", "0,725", "0,601", "0,823")
            for index in range(6, 0, -1):
                text = text[:match.start(index)] + numbers[index - 1] + text[match.end(index):]
            annotations[2]["text"] = text
            annotations[3]["text"] = re.sub(r"\b[0-9]+/500 réplications", "487/500 réplications", annotations[3]["text"])
    candidate = assignment(JOINT if template is None else template, b"payload", refit)
    if append:
        candidate = candidate.replace(b"137 mesures", b"138 mesures")
    candidate = refresh._JOINT_ARIA.sub(rb"\g<1>368,2\g<3>0,725\g<5>", candidate)
    return expand_ranges(candidate)


def marker(payload: bytes, *, joint: bool = False) -> bytes:
    value, _, _ = refresh._json_assignment(payload, b"payload" if joint else b"data")
    source = value["data"][0] if joint else value[0]
    method = "joint-v1" if joint else "recent-v1"
    fingerprint = hashlib.sha256(json.dumps({
        "method": method,
        "dates": [datetime.fromisoformat(date).isoformat(timespec="seconds") for date in source["x"]],
        "values": [float(number) for number in source["y"]],
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return payload.replace(b"</head>", f"<!-- manual-curve-refit:{method}:{fingerprint} --></head>".encode())


def fixture_master(payload: bytes, *, joint: bool = False) -> bytes:
    """Keep the real presentation but freeze test dates, independent of live refreshes.

    No fixture is written to the site. A later published generation may already
    contain the test's appended day, a new fit/marker and expanded plot ranges.
    """
    variable = b"payload" if joint else b"data"
    value, _, _ = refresh._json_assignment(payload, variable)
    data = value["data"] if joint else value
    old_count = len(data[0]["x"])
    payload = refresh._manual_refit_marker(payload, data, "Mesures manuelles" if joint else "Mesures récentes")
    kept_count = 0
    def trim(value):
        nonlocal kept_count
        data = value["data"] if joint else value
        points = [(x, y) for x, y in zip(data[0]["x"], data[0]["y"]) if datetime.fromisoformat(x) <= datetime(2026, 9, 24)]
        data[0]["x"], data[0]["y"] = map(list, zip(*points))
        kept_count = len(points)
        model = data[1 if joint else 3]
        model_points = [(x, y) for x, y in zip(model["x"], model["y"]) if datetime.fromisoformat(x) <= datetime.fromisoformat(points[-1][0])]
        model["x"], model["y"] = map(list, zip(*model_points))
    payload = assignment(payload, variable, trim)
    payload = payload.replace(f"{old_count} mesures".encode(), f"{kept_count} mesures".encode())
    if joint:
        # Numeric parameters are test inputs, not an accidental dependency on
        # whichever periodic fit happens to be published when CI runs.
        payload = joint_candidate(payload, append=False)
    def freeze_ranges(layout):
        layout["yaxis"]["range"] = [89.0, 92.05] if joint else [29.54, 30.84]
        if not joint:
            layout["yaxis2"]["range"] = [30.265, 30.415]
    return change_layouts(payload, freeze_ranges)


RECENT = fixture_master(RECENT)
JOINT = fixture_master(JOINT, joint=True)


class ManualModelRefitTests(unittest.TestCase):
    def test_rejects_shuffled_model_values_even_with_valid_source_marker(self):
        for original, candidate, variable, index, joint in (
            (RECENT, recent_candidate(), b"data", 3, False),
            (JOINT, joint_candidate(), b"payload", 1, True),
        ):
            def shuffle(value):
                trace = (value["data"] if joint else value)[index]
                trace["y"][110], trace["y"][150] = trace["y"][150], trace["y"][110]
            for with_marker in (False, True):
                with self.subTest(joint=joint, marker=with_marker):
                    payload = marker(candidate, joint=joint) if with_marker else candidate
                    corrupted = assignment(payload, variable, shuffle)
                    with self.assertRaisesRegex(refresh.RefreshError, "EXPONENTIAL|PERIODIC"):
                        refresh.refresh_manual(original, corrupted)

    def test_periodic_ordinates_must_match_declared_parameters_and_linear_trend(self):
        for parameters in ({"period": 350}, {"amplitude": 0.7}, {"phase_days": 10}):
            def change(value):
                trace = value["data"][1]
                trace["y"] = [joint_ordinate(date, **parameters) for date in trace["x"]]
            with self.subTest(parameters=parameters):
                with self.assertRaisesRegex(refresh.RefreshError, "PERIODIC_DIVERGED"):
                    refresh.refresh_manual(JOINT, assignment(joint_candidate(), b"payload", change))
        def nonlinear(value):
            trace = value["data"][1]
            trace["y"] = [number + 1e-7 * index * index for index, number in enumerate(trace["y"])]
        with self.assertRaisesRegex(refresh.RefreshError, "PERIODIC_DIVERGED"):
            refresh.refresh_manual(JOINT, assignment(joint_candidate(), b"payload", nonlinear))

    def test_periodic_rounding_and_positive_negative_or_zero_trend_are_supported(self):
        for slope in (-0.002, 0, 0.003):
            def change(value):
                trace = value["data"][1]
                trace["y"] = [joint_ordinate(date, slope=slope) for date in trace["x"]]
            candidate = expand_ranges(assignment(joint_candidate(), b"payload", change))
            with self.subTest(slope=slope):
                self.assertEqual(refresh.refresh_manual(JOINT, candidate), candidate)

    def test_periodic_shape_peaks_must_remain_inside_the_plotted_domain(self):
        def outside(value):
            for layout in value["layouts"].values():
                shapes, annotations = layout["shapes"], layout["annotations"]
                delta = timedelta(days=3 * 368.2)
                vertical_delta = 0.0001 * 3 * 368.2
                for index, shape in enumerate(shapes):
                    for field in ("x0", "x1"):
                        shape[field] = (datetime.fromisoformat(shape[field]) + delta).isoformat()
                    if index >= 3:
                        shape["y0"] += vertical_delta
                        shape["y1"] += vertical_delta
                for index in (0, 1):
                    annotations[index]["x"] = (datetime.fromisoformat(annotations[index]["x"]) + delta).isoformat()
                annotations[1]["y"] += vertical_delta
        with self.assertRaisesRegex(refresh.RefreshError, "PERIODIC_DOMAIN_INVALID"):
            refresh.refresh_manual(JOINT, assignment(joint_candidate(), b"payload", outside))

    def test_exponential_constant_linear_near_linear_and_curved_limits(self):
        for slope, curvature in ((0, 0.05), (0.0001, 0), (0.0001, 1e-12),
                                 (0.0001, 1e-9), (0.0001, 0.004), (1e-8, 0.05), (0.05, 0)):
            with self.subTest(slope=slope, curvature=curvature):
                refresh._validate_recent_model([recent_ordinate(day, slope=slope, curvature=curvature) for day in range(281)])
        for slope, curvature in ((-0.0001, 0.004), (0.051, 0), (0.0001, -0.001), (0.0001, 0.051)):
            with self.subTest(slope=slope, curvature=curvature):
                values = [31 + (slope * day if curvature == 0 else slope * math.expm1(min(curvature * day, 50)) / curvature) for day in range(281)]
                with self.assertRaisesRegex(refresh.RefreshError, "EXPONENTIAL"):
                    refresh._validate_recent_model(values)

    def test_exponential_local_precision_does_not_hide_early_corruption_with_clipping(self):
        values = [recent_ordinate(day, slope=0.05, curvature=0.05) for day in range(1201)]
        refresh._validate_recent_model(values)
        self.assertGreater(values[-1], 1e21)
        self.assertEqual(values[1000], values[-1])
        for mode in ("swap", "perturb"):
            corrupted = list(values)
            if mode == "swap":
                corrupted[1], corrupted[2] = corrupted[2], corrupted[1]
            else:
                corrupted[1] += 1e-5
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(refresh.RefreshError, "EXPONENTIAL_DIVERGED"):
                    refresh._validate_recent_model(corrupted)

    def test_exponential_every_point_is_checked_even_for_smooth_increasing_corruption(self):
        def change(data):
            trace = data[3]
            final = len(trace["y"]) - 1
            trace["y"] = [value + 0.001 * (index / final) * (1 - index / final) for index, value in enumerate(trace["y"])]
            lookup = dict(zip(trace["x"], trace["y"]))
            data[13]["y"] = [lookup[date] for date in data[13]["x"]]
            self.assertTrue(all(right > left for left, right in zip(trace["y"], trace["y"][1:])))
        with self.assertRaisesRegex(refresh.RefreshError, "EXPONENTIAL_DIVERGED"):
            refresh.refresh_manual(RECENT, assignment(recent_candidate(), b"data", change))

    def test_fixture_ignores_later_published_points_markers_parameters_and_ranges(self):
        for joint in (False, True):
            for later_days in (0, 7, 14):
                live = joint_candidate() if joint else recent_candidate()
                def later(value):
                    data = value["data"] if joint else value
                    final_date = datetime.fromisoformat(data[0]["x"][-1]) + timedelta(days=later_days)
                    data[0]["x"][-1] = final_date.isoformat()
                    model = data[1 if joint else 3]
                    last_date = datetime.fromisoformat(model["x"][-1])
                    model["x"].extend((last_date + timedelta(days=index + 1)).isoformat() for index in range(later_days))
                    model["y"] = ([joint_ordinate(date) for date in model["x"]] if joint else
                                  [recent_ordinate(index) for index in range(len(model["x"]))])
                live = marker(assignment(live, b"payload" if joint else b"data", later), joint=joint)
                with self.subTest(joint=joint, later_days=later_days):
                    baseline = fixture_master(live, joint=joint)
                    value, _, _ = refresh._json_assignment(baseline, b"payload" if joint else b"data")
                    data = value["data"] if joint else value
                    self.assertLessEqual(datetime.fromisoformat(data[0]["x"][-1]), datetime(2026, 9, 24))
                    self.assertNotIn(b"manual-curve-refit:", baseline)
                    self.assertEqual(refresh.refresh_manual(baseline, live), live)

    def test_recent_refit_preserves_fixed_zoom_dates_and_other_traces(self):
        candidate = recent_candidate()
        self.assertEqual(refresh.refresh_manual(RECENT, candidate), candidate)
        old, _, _ = refresh._json_assignment(RECENT, b"data")
        new, _, _ = refresh._json_assignment(candidate, b"data")
        self.assertEqual(old[13]["x"], new[13]["x"])
        self.assertNotEqual(old[13]["y"], new[13]["y"])
        self.assertTrue(all(old[index] == new[index] for index in range(14) if index not in (0, 3, 13)))

    def test_periodic_refit_updates_only_parameters_and_physical_geometry(self):
        candidate = joint_candidate()
        self.assertEqual(refresh.refresh_manual(JOINT, candidate), candidate)
        self.assertEqual(refresh.manual_data_only_skeleton(JOINT), refresh.manual_data_only_skeleton(candidate))

    def test_input_bound_marker_is_optional_and_idempotent_for_each_model(self):
        for active, candidate, joint in ((RECENT, recent_candidate(), False), (JOINT, joint_candidate(), True)):
            with self.subTest(joint=joint):
                marked = marker(candidate, joint=joint)
                self.assertEqual(refresh.refresh_manual(active, marked), marked)
                self.assertEqual(refresh.refresh_manual(marked, marked), marked)

    def test_marker_refuses_wrong_hash_model_duplicate_location_and_source_change(self):
        marked = marker(recent_candidate())
        start = marked.index(b"<!-- manual-curve-refit:")
        end = marked.index(b"-->", start) + 3
        comment = marked[start:end]
        mutations = (
            marked[:start] + comment.replace(b"recent-v1", b"joint-v1") + marked[end:],
            marked[:start] + b"<!-- manual-curve-refit:recent-v1:" + b"0" * 64 + b" -->" + marked[end:],
            marked[:start] + comment + comment + marked[end:],
            marked[:start] + comment + b"\n" + marked[end:],
            assignment(marked, b"data", lambda data: data[0]["y"].__setitem__(-1, 31.22)),
        )
        for mutation in mutations:
            with self.subTest(payload=hashlib.sha256(mutation).hexdigest()[:8]):
                with self.assertRaisesRegex(refresh.RefreshError, "MARKER"):
                    refresh.refresh_manual(RECENT, mutation)

    def test_rejects_model_only_partial_refresh_or_extrapolation(self):
        for active, variable, candidate, model_index in ((RECENT, b"data", recent_candidate(), 3), (JOINT, b"payload", joint_candidate(), 1)):
            for mode in ("stale", "future"):
                def change(value):
                    trace = (value["data"] if variable == b"payload" else value)[model_index]
                    if mode == "stale":
                        trace["x"].pop()
                        trace["y"].pop()
                    else:
                        trace["x"].append("2026-10-05T00:00:00")
                        trace["y"].append(trace["y"][-1])
                with self.subTest(variable=variable, mode=mode):
                    with self.assertRaisesRegex(refresh.RefreshError, "STALE|DOMAIN"):
                        refresh.refresh_manual(active, assignment(candidate, variable, change))

    def test_rejects_nonfinite_bool_missing_unordered_and_timezone_model_points(self):
        mutations = (
            lambda trace: trace["y"].__setitem__(0, float("nan")),
            lambda trace: trace["y"].__setitem__(0, float("inf")),
            lambda trace: trace["y"].__setitem__(0, True),
            lambda trace: trace["y"].__setitem__(0, None),
            lambda trace: trace["y"].pop(),
            lambda trace: trace["x"].__setitem__(1, trace["x"][0]),
            lambda trace: trace["x"].__setitem__(0, "2025-12-28T00:00:00+00:00"),
            lambda trace: trace["x"].__setitem__(0, "2025-12-32"),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(case=index):
                candidate = assignment(recent_candidate(), b"data", lambda data: mutation(data[3]))
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(RECENT, candidate)

    def test_rejects_zoom_x_or_y_divergence(self):
        for field in ("x", "y"):
            def change(data):
                data[13][field][0] = "2025-12-27T00:00:00" if field == "x" else 123.0
            with self.subTest(field=field):
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(RECENT, assignment(recent_candidate(), b"data", change))

    def test_rejects_other_traces_model_names_colors_widths_and_hovertext(self):
        mutations = (
            lambda data: data[1]["y"].__setitem__(0, 123),
            lambda data: data[4]["x"].__setitem__(0, "2026-03-29T00:00:00"),
            lambda data: data[3].__setitem__("name", "Autre modèle"),
            lambda data: data[3]["line"].__setitem__("color", "red"),
            lambda data: data[3]["line"].__setitem__("width", 99),
            lambda data: data[3].__setitem__("hovertemplate", "Changed prose"),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(case=index):
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(RECENT, assignment(recent_candidate(), b"data", mutation))

    def test_rejects_periodic_style_editorial_method_and_bootstrap_total_changes(self):
        mutations = (
            lambda layout: layout["shapes"][0]["line"].__setitem__("width", 5),
            lambda layout: layout["shapes"][0].__setitem__("y0", 91.89),
            lambda layout: layout["annotations"][0].__setitem__("y", 91.93),
            lambda layout: layout["annotations"][1].__setitem__("xshift", 30),
            lambda layout: layout["annotations"][2].__setitem__("x", 0.2),
            lambda layout: layout["annotations"][3].__setitem__("text", layout["annotations"][3]["text"].replace("covariance OU", "autre méthode")),
            lambda layout: layout["annotations"][3].__setitem__("text", layout["annotations"][3]["text"].replace("487/500", "487/600")),
            lambda layout: layout["annotations"][4].__setitem__("text", "Conclusion modifiée"),
            lambda layout: layout["shapes"][4].__setitem__("x1", "2026-11-01T00:00:00"),
        )
        for index, mutation in enumerate(mutations):
            def change(value):
                for layout in value["layouts"].values():
                    mutation(layout)
            with self.subTest(case=index):
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(JOINT, assignment(joint_candidate(), b"payload", change))

    def test_rejects_inconsistent_labels_intervals_bootstrap_and_responsive_modes(self):
        mutations = (
            lambda layout: layout["annotations"][0].__setitem__("text", "P = 369,0 jours"),
            lambda layout: layout["annotations"][1].__setitem__("text", "A = 0,726 mm"),
            lambda layout: layout["annotations"][2].__setitem__("text", layout["annotations"][2]["text"].replace("357,0–380,0", "390,0–380,0")),
            lambda layout: layout["annotations"][3].__setitem__("text", layout["annotations"][3]["text"].replace("487/500", "0/500")),
            lambda layout: layout["annotations"][3].__setitem__("text", layout["annotations"][3]["text"].replace("487/500", "501/500")),
            lambda layout: layout["annotations"][3].__setitem__("text", layout["annotations"][3]["text"].replace("487/500", "486/500")),
            lambda layout: layout["shapes"][3].__setitem__("y1", 92),
            lambda layout: layout["shapes"][0].__setitem__("x1", "2026-10-05T00:00:00"),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(case=index):
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(JOINT, assignment(joint_candidate(), b"payload", lambda value: mutation(value["layouts"]["mobile"])))
        with self.assertRaisesRegex(refresh.RefreshError, "ARIA"):
            refresh.refresh_manual(JOINT, joint_candidate().replace(b"de 368,2 jours", b"de 369,0 jours"))

    def test_rejects_html_style_script_and_new_free_form_assignment(self):
        for addition in (b"<script>alert('secret')</script>", b"<style>body{color:red}</style>", b"<p>New conclusion</p>", b"<script>const newModel = [];</script>"):
            with self.subTest(addition=addition):
                with self.assertRaisesRegex(refresh.RefreshError, "SKELETON_DIVERGED"):
                    refresh.refresh_manual(RECENT, recent_candidate().replace(b"</head>", addition + b"</head>"))

    def test_minimal_vertical_expansion_is_idempotent_and_includes_every_trace(self):
        for original, candidate in ((RECENT, recent_candidate()), (JOINT, joint_candidate())):
            with self.subTest(joint=original == JOINT):
                self.assertEqual(refresh.refresh_manual(original, candidate), candidate)
                self.assertEqual(refresh.refresh_manual(candidate, candidate), candidate)
        candidate = recent_candidate()
        layouts, _ = refresh._recent_layout_assignments(candidate)
        self.assertGreater(layouts[0]["yaxis"]["range"][1], 31.23)
        self.assertGreater(layouts[0]["yaxis2"]["range"][1], 31)

    def test_rejects_missing_margin_clipping_shrinkage_and_arbitrary_expansion(self):
        for original, candidate in ((RECENT, recent_candidate()), (JOINT, joint_candidate())):
            for axis in (("yaxis", "yaxis2") if original == RECENT else ("yaxis",)):
                with self.subTest(joint=original == JOINT, axis=axis):
                    clipped = change_layouts(candidate, lambda layout: layout[axis].__setitem__("range", [30.1, 30.2]))
                    with self.assertRaisesRegex(refresh.RefreshError, "AXIS_CLIPPED"):
                        refresh.refresh_manual(original, clipped)
                    wider = change_layouts(candidate, lambda layout: layout[axis].__setitem__("range", [layout[axis]["range"][0] - 1, layout[axis]["range"][1] + 1]))
                    with self.assertRaisesRegex(refresh.RefreshError, "NOT_MINIMAL_EXPANSION"):
                        refresh.refresh_manual(original, wider)
                    # Both ranges contain all data: shrinking is nevertheless forbidden.
                    with self.assertRaisesRegex(refresh.RefreshError, "NOT_MINIMAL_EXPANSION"):
                        refresh.refresh_manual(wider, candidate)
        def remove_margin(layout):
            layout["yaxis"]["range"][1] = 31.23
        with self.assertRaisesRegex(refresh.RefreshError, "AXIS_CLIPPED"):
            refresh.refresh_manual(RECENT, change_layouts(recent_candidate(), remove_margin))

    def test_rejects_vertical_responsive_divergence_nonfinite_and_other_axis_fields(self):
        candidate = joint_candidate()
        for changed in (
            assignment(candidate, b"payload", lambda value: value["layouts"]["mobile"]["yaxis"]["range"].__setitem__(1, 100)),
            change_layouts(candidate, lambda layout: layout["yaxis"]["range"].__setitem__(1, float("inf"))),
            change_layouts(candidate, lambda layout: layout["yaxis"].__setitem__("autorange", True)),
            change_layouts(candidate, lambda layout: layout["yaxis"].__setitem__("tickformat", ".8f")),
        ):
            with self.subTest(payload=hashlib.sha256(changed).hexdigest()[:8]):
                with self.assertRaises(refresh.RefreshError):
                    refresh.refresh_manual(JOINT, changed)

    def test_prepared_promotion_rejects_shrinkage_even_when_skeletons_match(self):
        candidate = recent_candidate()
        wider = change_layouts(candidate, lambda layout: layout["yaxis"]["range"].__setitem__(1, 32))
        self.assertEqual(refresh.manual_data_only_skeleton(wider), refresh.manual_data_only_skeleton(candidate))
        with self.assertRaisesRegex(promoter.Demo2PromotionError, "VISUAL_TEMPLATE_DIVERGED"):
            promoter._merge_prepared_output(wider, candidate, "manual")
        self.assertEqual(promoter._merge_prepared_output(RECENT, candidate, "manual"), candidate)


if __name__ == "__main__":
    unittest.main()
