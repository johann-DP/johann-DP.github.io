import hashlib
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
BUNDLE = ROOT / "assets" / "nerivane-public-v1"
SITEMAP = ROOT / "sitemap.xml"
WORKER = ROOT / "analytics-counter" / "src" / "worker.js"
WORKFLOW = ROOT / ".github" / "workflows" / "site-ci.yml"
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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        catalogue = CATALOGUE.read_text(encoding="utf-8")
        for preserved_demo in (
            "demonstrations/ormevia-batiment.html",
            "demonstrations/fissures.html",
        ):
            self.assertIn(preserved_demo, catalogue)

    def test_storyboard_has_exactly_seven_ordered_steps(self):
        data = load_data()
        self.assertEqual(data["formatVersion"], "0.2.0")
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
                    self.assertEqual(proof["sha256"], sha256(proof_target))

    def test_corpus_exposes_28_fingerprinted_documents_and_detailed_references(self):
        corpus = load_data()["corpus"]
        self.assertEqual(corpus["status"], "MESURÉ")
        self.assertEqual(
            corpus["counts"],
            {
                "documents": 28,
                "people": 26,
                "roles": 18,
                "assignments": 37,
                "sites": 10,
                "sourceSystems": 4,
            },
        )
        self.assertEqual(
            [document["id"] for document in corpus["documents"]],
            [f"DOC-{index:03d}" for index in range(1, 29)],
        )
        self.assertEqual(
            len({document["href"] for document in corpus["documents"]}),
            28,
        )
        for resource in (
            corpus["manifest"],
            corpus["references"],
            corpus["package"],
            *corpus["documents"],
        ):
            with self.subTest(resource=resource.get("id") or resource["label"]):
                target = (PAGE.parent / urlsplit(resource["href"]).path).resolve()
                self.assertTrue(target.is_file(), resource["href"])
                self.assertRegex(resource["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(resource["sha256"], sha256(target))

        manifest = json.loads((BUNDLE / "corpus-manifest.json").read_text(encoding="utf-8"))
        references = json.loads((BUNDLE / "reference-registry.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["document_count"], 28)
        self.assertTrue(manifest["fictional"])
        self.assertEqual(len(references["people"]), 26)
        self.assertEqual(len(references["roles"]), 18)
        self.assertEqual(len(references["assignments"]), 37)
        self.assertEqual(len(references["sites"]), 10)
        self.assertEqual(len(references["source_systems"]), 4)

    def test_copied_public_bundle_is_complete_and_immutable(self):
        checksum_file = BUNDLE / "SHA256SUMS"
        entries = []
        for line in checksum_file.read_text(encoding="ascii").splitlines():
            digest, relative = line.split("  ", 1)
            entries.append((digest, relative))
        self.assertEqual(len(entries), 128)
        for expected, relative in entries:
            with self.subTest(path=relative):
                target = BUNDLE / relative
                self.assertTrue(target.is_file(), relative)
                self.assertEqual(sha256(target), expected)

        replay = json.loads((BUNDLE / "replay-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(replay["status"], "BLOCKED_CANDIDATE_AI_NOT_EXECUTED")
        self.assertEqual(replay["counts"]["documents"], 28)
        self.assertEqual(replay["counts"]["steps"], 7)

    def test_stable_claims_link_to_their_piece_specific_proofs(self):
        claims = {claim["id"]: claim for claim in all_claims(load_data())}
        expected_suffixes = {
            "definitions-corpus": "steps/01.html",
            "kpi-candidate": "documents/DOC-026.html",
            "pilot-v1": "evidence/gcp/sample-apply/20260826T070016Z/manifest.json",
            "ai-gate": "documents/DOC-027.html",
        }
        for claim_id, suffix in expected_suffixes.items():
            with self.subTest(claim=claim_id):
                proof = claims[claim_id]["proof"]
                self.assertTrue(proof["href"].endswith(suffix))
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

    def test_site_publication_plumbing_includes_nerivane(self):
        canonical = "https://www.datapredict.org/demonstrations/nerivane-distribution.html"
        self.assertIn(canonical, SITEMAP.read_text(encoding="utf-8"))
        self.assertIn(
            '"/demonstrations/nerivane-distribution.html": "Démo Nérivane"',
            WORKER.read_text(encoding="utf-8"),
        )
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            '"demonstrations/nerivane-distribution.html"',
            '"assets/css/demo-nerivane.css"',
            '"assets/data/nerivane-governance-replay.json"',
            '"assets/js/demo-nerivane.js"',
            '"assets/nerivane-public-v1/replay-manifest.json"',
            "python3 -m unittest -q tests.test_nerivane_public_replay",
            "node --check assets/js/demo-nerivane.js",
        ):
            self.assertIn(marker, workflow)

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
        public_files = (
            PAGE,
            DATA,
            SCRIPT,
            STYLE,
            *(path for path in sorted(BUNDLE.rglob("*")) if path.is_file()),
        )
        for path in public_files:
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertIsNone(pattern.search(content), f"private token in {path}: {pattern.pattern}")


if __name__ == "__main__":
    unittest.main()
