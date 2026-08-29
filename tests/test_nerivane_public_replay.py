import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demonstrations" / "nerivane-distribution.html"
DATA = ROOT / "assets" / "data" / "nerivane-governance-replay.json"
SCRIPT = ROOT / "assets" / "js" / "demo-nerivane.js"
STYLE = ROOT / "assets" / "css" / "demo-nerivane.css"
CATALOGUE = ROOT / "demonstrations.html"
ALLOWED_STATUSES = {"MESURÉ", "PLANIFIÉ", "BLOQUÉ", "EXÉCUTÉ_NON_VALIDÉ"}


class MarkupInventory(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.references = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag in {"a", "link"} and values.get("href"):
            self.references.append(values["href"])
        if tag in {"img", "script"} and values.get("src"):
            self.references.append(values["src"])


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def all_claims(data):
    return [
        *data["introduction"]["summaryClaims"],
        *(claim for step in data["steps"] for claim in step["claims"]),
    ]


class NerivanePublicReplayTests(unittest.TestCase):
    def test_static_assets_and_catalogue_entry_exist(self):
        for path in (PAGE, DATA, SCRIPT, STYLE, CATALOGUE):
            self.assertTrue(path.is_file(), path)

        parser = MarkupInventory()
        parser.feed(PAGE.read_text(encoding="utf-8"))
        parser.close()
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "duplicate HTML id")

        for reference in parser.references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith("#"):
                continue
            target = (PAGE.parent / parsed.path).resolve()
            self.assertTrue(target.is_file(), f"missing page asset: {reference}")

        self.assertIn(
            "demonstrations/nerivane-distribution.html",
            CATALOGUE.read_text(encoding="utf-8"),
        )

    def test_storyboard_has_exactly_seven_ordered_steps(self):
        data = load_data()
        self.assertEqual(data["formatVersion"], "0.1.0")
        self.assertEqual(len(data["steps"]), 7)
        self.assertEqual([step["order"] for step in data["steps"]], list(range(1, 8)))
        self.assertEqual(
            [step["id"] for step in data["steps"]],
            [
                "impasse-metier",
                "h1-reel",
                "topologie",
                "ressources",
                "reprise",
                "lignage",
                "ia-decision",
            ],
        )

    def test_every_claim_has_status_scope_proof_fingerprint_and_limit(self):
        data = load_data()
        claims = all_claims(data)
        self.assertEqual(len(claims), 19)
        self.assertEqual(len({claim["id"] for claim in claims}), len(claims))

        for claim in claims:
            with self.subTest(claim=claim["id"]):
                self.assertIn(claim["status"], ALLOWED_STATUSES)
                for field in ("label", "value", "scope", "limitation"):
                    self.assertIsInstance(claim.get(field), str)
                    self.assertTrue(claim[field].strip())
                proof = claim.get("proof", {})
                for field in ("label", "href", "sha256"):
                    self.assertIsInstance(proof.get(field), str)
                    self.assertTrue(proof[field].strip())
                proof_target = (PAGE.parent / urlsplit(proof["href"]).path).resolve()
                self.assertTrue(proof_target.is_file(), proof["href"])
                if claim["status"] == "MESURÉ":
                    self.assertRegex(proof["sha256"], r"^[0-9a-f]{64}$")

    def test_visual_references_resolve_to_declared_claims(self):
        data = load_data()
        ids = {claim["id"] for claim in all_claims(data)}
        references = []

        for step in data["steps"]:
            visual = step["visual"]
            references.extend(
                value for value in (visual.get("targetClaimId"), visual.get("finalClaimId")) if value
            )
            for collection in ("sources", "nodes", "events"):
                references.extend(
                    item["claimId"] for item in visual.get(collection, []) if item.get("claimId")
                )
            references.extend(
                visual[key]["claimId"]
                for key in ("input", "model", "controls")
                if visual.get(key)
            )
        references.extend(gate["claimId"] for gate in data["conclusion"]["gates"])
        self.assertTrue(references)
        self.assertEqual(set(references) - ids, set())

    def test_projection_is_never_presented_as_realized(self):
        data = load_data()
        claims = {claim["id"]: claim for claim in all_claims(data)}
        projection = claims["h1-projection"]
        final = claims["h1-final"]

        self.assertEqual(projection["status"], "PLANIFIÉ")
        self.assertEqual(
            projection["value"],
            "1 320 triplets · 3 960 fichiers · 2 004 364 194 lignes · 1 919 118 297 934 octets",
        )
        self.assertIn("Projection uniquement", projection["limitation"])
        self.assertEqual(final["status"], "BLOQUÉ")
        self.assertIn("En attente", final["value"])

        h1_visual = next(step for step in data["steps"] if step["id"] == "h1-reel")["visual"]
        self.assertTrue(all(metric["value"] == "—" for metric in h1_visual["final"]))

        projection_literal = "1 919 118 297 934"
        for path in (PAGE, SCRIPT, STYLE):
            self.assertNotIn(projection_literal, path.read_text(encoding="utf-8"), path)

    def test_bigquery_v2_and_ai_v16_remain_closed(self):
        claims = {claim["id"]: claim for claim in all_claims(load_data())}
        self.assertEqual(claims["v2-lineage"]["status"], "BLOQUÉ")
        self.assertIn("Non créé", claims["v2-lineage"]["value"])
        self.assertIn("validation explicite", claims["v2-lineage"]["limitation"])
        self.assertEqual(claims["ai-v16"]["status"], "BLOQUÉ")
        self.assertIn("Aucun résultat V16", claims["ai-v16"]["limitation"])
        self.assertEqual(claims["ai-v15"]["status"], "EXÉCUTÉ_NON_VALIDÉ")

    def test_topology_and_resource_roles_are_explicit(self):
        data = load_data()
        topology = next(step for step in data["steps"] if step["id"] == "topologie")["visual"]
        nodes = {node["name"]: node for node in topology["nodes"]}
        self.assertEqual(set(nodes), {"r9", "i7", "r7", "i9"})
        self.assertIn("7 rôles", nodes["r9"]["storage"])
        self.assertIn("attestation", nodes["i7"]["detail"])
        self.assertIn("limité", nodes["r7"]["detail"])
        self.assertIn("aucun stockage massif", nodes["i9"]["detail"])

        resources = next(step for step in data["steps"] if step["id"] == "ressources")["visual"]
        resource_nodes = {node["name"]: node for node in resources["nodes"]}
        self.assertIn("CPU/RAM/GPU", resource_nodes["i9"]["role"])
        self.assertIn("GPU non utilisé par H1", resource_nodes["r9"]["gpu"])

    def test_public_bundle_contains_no_private_paths_or_addresses(self):
        forbidden = [
            re.compile(r"/(?:home|media|run)/"),
            re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
            re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        ]
        for path in (PAGE, DATA, SCRIPT, STYLE):
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertIsNone(pattern.search(content), f"private token in {path}: {pattern.pattern}")


if __name__ == "__main__":
    unittest.main()
