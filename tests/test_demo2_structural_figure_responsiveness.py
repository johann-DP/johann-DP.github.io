from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIGURES = (
    ROOT / "assets/figures/demo-2/fissure-recente-meme-format.html",
    ROOT / "assets/figures/demo-2/joint-dilatation-rendu-site.html",
)


class StructuralFigureResponsivenessTests(unittest.TestCase):
    def test_validated_structural_figures_use_at_least_ninety_percent_of_desktop_width(self) -> None:
        wrapper_width = re.compile(
            r"\.d2-production-wrap\s*\{[^}]*"
            r"width:\s*calc\(100% - clamp\((\d+)px,\s*(\d+)vw,\s*(\d+)px\)\);",
            flags=re.DOTALL,
        )

        for figure in FIGURES:
            with self.subTest(figure=figure.name):
                html = figure.read_text(encoding="utf-8")
                match = wrapper_width.search(html)
                self.assertIsNotNone(match)
                minimum, preferred_vw, maximum = map(int, match.groups())

                self.assertRegex(html, r"html, body\s*\{\s*margin:\s*0;")
                self.assertNotIn("width: min(1280px", html)
                for viewport in (1280, 2560):
                    gutter = max(minimum, min(viewport * preferred_vw / 100, maximum))
                    useful_width_ratio = (viewport - gutter) / viewport
                    self.assertGreaterEqual(useful_width_ratio, 0.9)

    def test_plot_height_follows_width_during_initial_render_and_live_resize(self) -> None:
        for figure in FIGURES:
            with self.subTest(figure=figure.name):
                html = figure.read_text(encoding="utf-8")
                self.assertRegex(
                    html,
                    r'mode === "desktop"\s*\?\s*Math\.round\(width \* 0\.6\)',
                )
                self.assertRegex(
                    html,
                    r"Plotly\.relayout\(plot,\s*\{[^}]*"
                    r"width(?::\s*width)?[^}]*height:\s*layout\.height",
                )


if __name__ == "__main__":
    unittest.main()
