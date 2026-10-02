from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demonstrations/fissures.html"
M12 = ROOT / "assets/analyses/demo-2/m12"
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_demo2_stage3_data as stage3  # noqa: E402


class HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "h1":
            self.h1 += 1


class Demo2M12PublicationTests(unittest.TestCase):
    def test_stage_one_and_two_are_byte_identical_to_the_approved_base(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        expected = {
            1: "1568b8db95c818324db0a4349664b741f93e0a28946d7557c58ea6e536eeab35",
            2: "585f39bdf0d49864eada3f6ed5d7114b3335be20fd52aea0ce5698f85cd6fca3",
        }
        for step, digest in expected.items():
            block = re.search(fr'<section id="etape-{step}".*?</section>', page, re.DOTALL)
            self.assertIsNotNone(block)
            self.assertEqual(hashlib.sha256(block.group(0).encode()).hexdigest(), digest)

    def test_three_m12_pages_and_public_data_are_local_and_bounded(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        slugs = ("factors", "forecast", "pruning")
        for slug in slugs:
            self.assertIn(f"../assets/analyses/demo-2/m12/pages/{slug}.html", page)
            html_path = M12 / "pages" / f"{slug}.html"
            data_path = M12 / "data" / f"{slug}.json"
            self.assertTrue(html_path.is_file())
            self.assertTrue(data_path.is_file())
            html = html_path.read_text(encoding="utf-8")
            self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
            parser = HeadingParser()
            parser.feed(html)
            parser.close()
            self.assertEqual(parser.h1, 1)
            data = json.loads(data_path.read_text(encoding="utf-8"))
            serialized = json.dumps(data, ensure_ascii=False)
            for forbidden in ("/media/", "target_id", "observation_id", "source_parent_ids"):
                self.assertNotIn(forbidden, serialized)

    def test_public_scientific_counts_and_no_ninety_day_projection(self) -> None:
        factors = json.loads((M12 / "data/factors.json").read_text(encoding="utf-8"))
        forecast = json.loads((M12 / "data/forecast.json").read_text(encoding="utf-8"))
        pruning = json.loads((M12 / "data/pruning.json").read_text(encoding="utf-8"))
        self.assertEqual(len(factors["contrasts"]), 19)
        stage3.validate_stage3_data(ROOT)
        self.assertGreaterEqual(len(forecast["measurements"]), 137)
        self.assertTrue(1 <= len(forecast["simulation"]["targets"]) <= 3)
        if forecast["simulation"]["issued_at"] is not None:
            self.assertEqual(forecast["simulation"]["method_id"], stage3.METHOD)
        for panel in forecast["historical_comparison"]["panels"]:
            self.assertGreater(len(panel["rows"]), 0)
        self.assertGreater(len(pruning["comparator_series"]), 0)
        self.assertFalse((M12 / "pages/evolution.html").exists())


if __name__ == "__main__":
    unittest.main()
