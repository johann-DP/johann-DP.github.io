"""Regression checks for the public analysis pages, without private inputs."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/analyses/demo-2/m12/assets"
PAGES = ROOT / "assets/analyses/demo-2/m12/pages"


class M12InteractionContractTests(unittest.TestCase):
    def test_responsive_and_thermal_controls(self) -> None:
        result = subprocess.run(
            [
                "node",
                str(ROOT / "tests/test_m12_responsive.cjs"),
                str(ASSETS / "m12.js"),
                str(ASSETS / "m12.css"),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 8", result.stdout)
        self.assertIn("# fail 0", result.stdout)

    def test_historical_series_use_color_and_shape(self) -> None:
        source = (ASSETS / "m12.js").read_text(encoding="utf-8")
        for style in (
            'color: COLORS.deep, size: mobile ? 9 : 8, symbol: "circle"',
            'color: COLORS.aqua, size: mobile ? 10 : 9, symbol: "diamond"',
            'color: COLORS.orange, size: mobile ? 11 : 10, symbol: "x", '
            'line: { color: COLORS.orange, width: 1.2 }',
        ):
            self.assertIn(style, source)

    def test_public_copy_has_no_owner_handoff_language(self) -> None:
        for path in PAGES.glob("*.html"):
            source = path.read_text(encoding="utf-8")
            for phrase in (
                "elle n’est pas dupliquée ici",
                "ici viendra la comparaison",
                "n’est pas encore observable",
                "prévisualisation privée",
                "Provenance : sorties structurées",
            ):
                self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
