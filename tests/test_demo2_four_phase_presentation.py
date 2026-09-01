from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demonstrations/fissures.html"

VALIDATED_FIGURE_IDS = (
    "building-geometry",
    "crack-history",
    "crack-recent",
    "expansion-joint",
    "retaining-wall-source-values",
    "retaining-wall-extrema-hours",
    "retaining-wall-median-day",
    "weather-temperature",
    "weather-temperature-range",
    "weather-humidity",
    "weather-light",
    "weather-rainfall",
    "weather-wind-speed",
    "weather-wind-direction",
    "weather-pairplots",
    "weather-explorer",
    "weather-quality",
)

VALIDATED_THUMBNAIL_SHA256 = {
    "building-geometry": "5c2b4377d24aaad2b0f0195bcc8a802c66860cc08dbdb039903bb4366a49b083",
    "crack-history": "2aadd1709b544db71318526b85a390cee2ce796e6ed7831c233294918e09cf06",
    "crack-recent": "b370703d995c585213fc975d437f8f8ae43647b6fa0c03ef9d101e1561a11a32",
    "expansion-joint": "bdfef3ac040a6680d32eadd09d322dcfc2acef0fef74e208eb3488d7184f3427",
    "retaining-wall-source-values": "90a0f0806e315d90e1e00d34dab7800caa930ce3cc221bb3eeb80a15dea1e6a9",
    "retaining-wall-extrema-hours": "0584e421e61bd8bee02568696b8f2d449e6a83a823401b4c9dcd40a407ebea4c",
    "retaining-wall-median-day": "bf635b7b772d80586ca73ac800367272dc8dd9895c6a5e84846e3c3db147134e",
    "weather-explorer": "1a541afca44257ffef4dd90bf048515d88df3e65c863dcbc4a7cfc598afa346a",
    "weather-humidity": "e502c24f30a456df2d8802daedefefd750c4dbb9fdb43a0aae124689ecc4af32",
    "weather-light": "f710bd4d8c5d6c0a42dbcb1de88fd20a6f2f2ef9b6f5b4c3d94520c5581644d9",
    "weather-pairplots": "fffbf88c5f6fa113478f7e1215b9fe65f31aeff08534091a498c136cba7f8d22",
    "weather-quality": "af67c4f84a252a36395855a67e6dacf5c9ae4aef910f2a1d00760dcee2b0fa1a",
    "weather-rainfall": "54d94aaf71396bf23424161f56e54266ba167da3513d00b2d9f690c55e2ffc31",
    "weather-temperature": "f5aeaf087e1db66a961252d63abc8972a9e464fc47136b66f39e30240b4b56c6",
    "weather-temperature-range": "a6ccf57bb063c40d0de76064a2b1c906fe531d49beb16c16c484136f27e4489f",
    "weather-wind-direction": "3120c5bff6a444a0c3b84889eb1d753c51a2d08c1dbd56e14ea11f1671c51b45",
    "weather-wind-speed": "49fe2a710612117374c4bffa4ad56a84256b0a40f6bf7056d95ddb9ffdbab666",
}


class FigureIdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.identifiers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("data-figure-id")
        if tag == "img" and identifier:
            self.identifiers.append(identifier)


class Demo2FourPhasePresentationTests(unittest.TestCase):
    def test_four_phases_are_explicit_without_reordering_validated_catalogue(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        parser = FigureIdParser()
        parser.feed(page)
        parser.close()

        self.assertEqual(tuple(parser.identifiers), VALIDATED_FIGURE_IDS)
        self.assertIn('id="demarche"', page)
        self.assertIn("Mise à jour · Acquisition · Qualité", page)
        self.assertIn("Mesures · Analyses", page)
        self.assertIn("Modélisation explicative", page)
        self.assertIn("Prévision", page)
        self.assertIn("Démarche datapredict", page)
        self.assertIn("ne sollicite ni le Raspberry Pi", page)

    def test_validated_thumbnail_bytes_are_unchanged(self) -> None:
        thumbnail_root = ROOT / "assets/img/demo-2-thumbnails"
        for identifier, expected_sha256 in VALIDATED_THUMBNAIL_SHA256.items():
            with self.subTest(identifier=identifier):
                payload = (thumbnail_root / f"{identifier}.webp").read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)


if __name__ == "__main__":
    unittest.main()
