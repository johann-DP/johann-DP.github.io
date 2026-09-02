from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_nerivane_site_state as nerivane_states  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demonstrations" / "fissures.html"
CATALOGUE = ROOT / "demonstrations.html"

VALIDATED_FIGURE_LINKS = (
    "../assets/figures/demo-2/building-geometry.html",
    "../assets/figures/demo-2/retaining-wall-sensor-source-values.html",
    "../assets/figures/demo-2/weather/complements/meteo_explorateur_toutes_mesures.html",
    "../assets/figures/demo-2/weather/complements/meteo_qualite_acquisition.html",
    "../assets/figures/demo-2/01-historical-crack-analysis-compacted-v2.html",
    "../assets/figures/demo-2/fissure-recente-meme-format.html",
    "../assets/figures/demo-2/joint-dilatation-rendu-site.html",
    "../assets/figures/demo-2/retaining-wall-median-day.html",
    "../assets/figures/demo-2/retaining-wall-extrema-hours.html",
    "../assets/figures/demo-2/weather/legacy/meteo_temperature.html",
    "../assets/figures/demo-2/weather/legacy/meteo_temp_minmax.html",
    "../assets/figures/demo-2/weather/legacy/meteo_humidity.html",
    "../assets/figures/demo-2/weather/legacy/meteo_light_uv.html",
    "../assets/figures/demo-2/weather/legacy/meteo_precipitation.html",
    "../assets/figures/demo-2/weather/legacy/meteo_wind_speed.html",
    "../assets/figures/demo-2/weather/legacy/meteo_wind_dir.html",
    "../assets/figures/demo-2/weather/legacy/meteo_pairplots.html",
)

UNVALIDATED_SENSOR_CANDIDATES = (
    "retaining-wall-mean-day.html",
)


class FigureInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.previews: list[dict[str, str]] = []
        self.external_figure_links: list[str] = []
        self.figure_card_count = 0
        self.iframe_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "img" and attributes.get("data-figure-id"):
            self.previews.append({key: value or "" for key, value in attributes.items()})
        elif tag == "article" and "fissures-demo__figure-card" in (
            attributes.get("class") or ""
        ).split():
            self.figure_card_count += 1
        elif (
            tag == "a"
            and attributes.get("target") == "_blank"
            and (attributes.get("href") or "").startswith("../assets/figures/demo-2/")
        ):
            self.external_figure_links.append(attributes.get("href") or "")
        elif tag == "iframe":
            self.iframe_count += 1


class Demo2PublicationStateTests(unittest.TestCase):
    def test_demo2_remains_in_maintenance_without_altering_demo3(self) -> None:
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

        self.assertIn('<body class="fissures-demo" data-maintenance="true">', page)
        self.assertIn("Démonstration 2 · En maintenance", page)
        self.assertIn("Les restitutions déjà publiées restent consultables", page)
        self.assertNotIn("<div hidden>", page)
        self.assertIn("<span class=\"demonstrations-page__card-status\">En maintenance</span>", demo2_card)
        self.assertIn("Consulter la version en maintenance", demo2_card)
        self.assertNotIn("<span class=\"demonstrations-page__card-status\">Disponible</span>", demo2_card)
        self.assertIn("Dix-sept restitutions consultables à la demande", demo2_card)
        self.assertNotIn("Quinze restitutions consultables à la demande", demo2_card)

        nerivane = nerivane_states.validate_site_state(site_root=ROOT)
        nerivane_page = (
            ROOT / "demonstrations" / "nerivane-distribution.html"
        ).read_text(encoding="utf-8")
        if nerivane["state"] == nerivane_states.MAINTENANCE_STATE:
            self.assertIn('data-maintenance="true"', nerivane_page)
            self.assertIn("Disponible · maintenance", catalogue)
            self.assertIn("Consulter la version de maintenance", catalogue)
        else:
            self.assertEqual(nerivane["state"], nerivane_states.ACTIVE_STATE)
            self.assertIn(
                f'data-release-id="{nerivane["release_id"]}"',
                nerivane_page,
            )
            self.assertNotIn("maintenance", nerivane_page.lower())
            self.assertIn(
                f'data-release="assets/validated-releases/nerivane-v2/{nerivane["release_id"]}"',
                catalogue,
            )

    def test_seventeen_static_lazy_previews_replace_the_interactive_viewer(self) -> None:
        parser = FigureInventory()
        page = PAGE.read_text(encoding="utf-8")
        parser.feed(page)
        parser.close()

        identifiers = [preview["data-figure-id"] for preview in parser.previews]
        self.assertEqual(len(identifiers), 17)
        self.assertEqual(len(set(identifiers)), 17)
        self.assertEqual(parser.figure_card_count, 17)
        self.assertEqual(tuple(parser.external_figure_links), VALIDATED_FIGURE_LINKS)
        self.assertEqual(parser.iframe_count, 0)
        self.assertNotIn("Lecteur de restitution", page)
        self.assertNotIn("Afficher dans la page", page)
        self.assertNotIn("demo-fissures.js", page)

        for preview in parser.previews:
            identifier = preview["data-figure-id"]
            self.assertEqual(
                preview["src"],
                f"../assets/img/demo-2-thumbnails/{identifier}.webp",
            )
            self.assertEqual(preview["loading"], "lazy")
            self.assertEqual(preview["decoding"], "async")
            self.assertEqual(preview["width"], "800")
            self.assertEqual(preview["height"], "500")
            self.assertTrue(preview["alt"].strip())

        for href in VALIDATED_FIGURE_LINKS:
            with self.subTest(href=href):
                self.assertTrue((PAGE.parent / href).resolve().is_file())

        self.assertIn("building-geometry", identifiers)
        for candidate in UNVALIDATED_SENSOR_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertNotIn(candidate, page)

        script = (ROOT / "assets" / "js" / "demo-fissures.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("iframe", script.lower())
        self.assertNotIn("querySelector", script)
        self.assertNotIn("addEventListener", script)

        stylesheet = (ROOT / "assets" / "css" / "demo-fissures.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("aspect-ratio: 8 / 5", stylesheet)
        self.assertIn("object-fit: contain", stylesheet)
        self.assertNotIn("fissures-demo__viewer", stylesheet)


if __name__ == "__main__":
    unittest.main()
