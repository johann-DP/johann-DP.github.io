from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demonstrations" / "fissures.html"
CATALOGUE = ROOT / "demonstrations.html"


class FigureInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figure_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "button" and attributes.get("data-figure-id"):
            self.figure_ids.append(attributes["data-figure-id"] or "")


class Demo2PublicationStateTests(unittest.TestCase):
    def test_demo2_is_available_without_altering_demo3_maintenance(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        catalogue = CATALOGUE.read_text(encoding="utf-8")
        demo2_card_match = re.search(
            r'<a class="demonstrations-page__card-link" '
            r'href="demonstrations/fissures\.html".*?</a>',
            catalogue,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(demo2_card_match)
        demo2_card = demo2_card_match.group(0)

        self.assertNotIn("maintenance", page.lower())
        self.assertNotIn("finalisation", page.lower())
        self.assertIn("<span class=\"demonstrations-page__card-status\">Disponible</span>", demo2_card)
        self.assertNotIn("maintenance", demo2_card.lower())
        self.assertNotIn("finalisation", demo2_card.lower())

        self.assertIn('data-maintenance="true"', (ROOT / "demonstrations" / "nerivane-distribution.html").read_text(encoding="utf-8"))
        self.assertIn("Disponible · maintenance", catalogue)
        self.assertIn("Consulter la version de maintenance", catalogue)

    def test_fifteen_validated_figure_controls_are_preserved(self) -> None:
        parser = FigureInventory()
        parser.feed(PAGE.read_text(encoding="utf-8"))
        parser.close()
        self.assertEqual(len(parser.figure_ids), 15)
        self.assertEqual(len(set(parser.figure_ids)), 15)


if __name__ == "__main__":
    unittest.main()
