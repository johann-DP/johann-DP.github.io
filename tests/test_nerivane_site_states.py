from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_nerivane_v2_release as importer  # noqa: E402
import promote_nerivane_v2_release as promoter  # noqa: E402
import validate_nerivane_site_state as states  # noqa: E402
from tests.test_import_nerivane_v2_release import (  # noqa: E402
    build_site,
    build_source,
    canonical,
)


class NerivaneClosedSiteStatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.site = self.root / "site"
        self.site.mkdir()
        build_site(self.site)
        self.baseline = states.capture_baseline(self.site)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        source = build_source(self.sources)
        self.release_id = importer.import_release(source, site_root=self.site)[
            "release_id"
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def promote(self) -> None:
        result = promoter.promote_release(self.release_id, site_root=self.site)
        self.assertIn(result["status"], {"PROMOTED", "ALREADY_ACTIVE"})

    def validate(self) -> dict[str, object]:
        return states.validate_site_state(
            site_root=self.site,
            baseline=self.baseline,
        )

    def test_accepts_the_exact_current_v1_maintenance_state(self) -> None:
        result = self.validate()

        self.assertEqual(result["state"], states.MAINTENANCE_STATE)
        self.assertIsNone(result["release_id"])

    def test_accepts_the_exact_content_addressed_v2_active_state(self) -> None:
        self.promote()

        result = self.validate()

        self.assertEqual(result["state"], states.ACTIVE_STATE)
        self.assertEqual(result["release_id"], self.release_id)

    def test_rejects_a_hybrid_maintenance_and_active_page(self) -> None:
        self.promote()
        page = self.site / states.PAGE_RELATIVE
        payload = page.read_bytes().replace(
            b"<body ",
            b'<body data-maintenance="true" ',
            1,
        )
        page.write_bytes(payload)

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_SITE_STATE_HYBRID",
        ):
            self.validate()

    def test_rejects_an_unrecognized_third_state(self) -> None:
        page = self.site / states.PAGE_RELATIVE
        page.write_bytes(
            page.read_bytes().replace(b'data-maintenance="true"', b'data-state="preview"')
        )

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_SITE_STATE_UNRECOGNIZED",
        ):
            self.validate()

    def test_rejects_maintenance_content_changed_behind_valid_markers(self) -> None:
        data = self.site / states.DATA_RELATIVE
        data.write_bytes(data.read_bytes() + b" changed")

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_MAINTENANCE_BASELINE_CHANGED",
        ):
            self.validate()

    def test_rejects_divergent_active_release_ids(self) -> None:
        self.promote()
        page = self.site / states.PAGE_RELATIVE
        page.write_bytes(page.read_bytes().replace(self.release_id.encode(), b"b" * 64))

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_ACTIVE_RELEASE_ID_DIVERGED",
        ):
            self.validate()

    def test_rejects_active_page_without_initial_verification_state(self) -> None:
        self.promote()
        page = self.site / states.PAGE_RELATIVE
        page.write_bytes(
            page.read_bytes().replace(
                b'data-status="verification"',
                b'data-status="valide"',
                1,
            )
        )

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_ACTIVE_MARKERS_INVALID",
        ):
            self.validate()

    def test_rejects_each_missing_exact_active_seo_marker(self) -> None:
        self.promote()
        page = self.site / states.PAGE_RELATIVE
        original = page.read_text(encoding="utf-8")
        for marker in states.ACTIVE_SEO_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(original.count(marker), 1)
                page.write_text(original.replace(marker, "", 1), encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                        states.NerivaneSiteStateError,
                        "NERIVANE_ACTIVE_MARKERS_INVALID",
                    ):
                        self.validate()
                finally:
                    page.write_text(original, encoding="utf-8")

    def test_rejects_active_script_without_fail_closed_header_transition(self) -> None:
        self.promote()
        script = self.site / states.SCRIPT_RELATIVE
        script.write_bytes(
            script.read_bytes().replace(
                b"Indisponible / non authentifi\xc3\xa9",
                b"Replay disponible sans preuve",
                1,
            )
        )

        with patch.object(
            states.promoter,
            "attest_release",
            return_value={"state": "ACTIVE", "release_id": self.release_id},
        ):
            with self.assertRaisesRegex(
                states.NerivaneSiteStateError,
                "NERIVANE_ACTIVE_FAIL_CLOSED_HEADER_INVALID",
            ):
                self.validate()

    def test_rejects_missing_http_json_or_resource_evidence_guards(self) -> None:
        self.promote()
        script = self.site / states.SCRIPT_RELATIVE
        original = script.read_bytes()
        mutations = (
            b'if (!response.ok) throw new Error("Registre public indisponible");',
            b"return response.json();",
            b'["park-resources", "evidence/resource-windows/manifest.json"],',
        )
        for marker in mutations:
            with self.subTest(marker=marker):
                self.assertEqual(original.count(marker), 1)
                script.write_bytes(original.replace(marker, b"", 1))
                try:
                    with patch.object(
                        states.promoter,
                        "attest_release",
                        return_value={"state": "ACTIVE", "release_id": self.release_id},
                    ):
                        with self.assertRaisesRegex(
                            states.NerivaneSiteStateError,
                            "NERIVANE_ACTIVE_FAIL_CLOSED_HEADER_INVALID",
                        ):
                            self.validate()
                finally:
                    script.write_bytes(original)

    def test_rejects_unknown_or_missing_fields_in_the_complete_v2_schema(self) -> None:
        self.promote()
        data_path = self.site / states.DATA_RELATIVE
        original = json.loads(data_path.read_bytes())
        release_root = (
            self.site
            / "assets/validated-releases/nerivane-v2"
            / self.release_id
        )
        for mutate in (
            lambda value: value.update({"unexpected": True}),
            lambda value: value.pop("publication_boundary"),
        ):
            with self.subTest(mutation=mutate):
                value = json.loads(json.dumps(original))
                mutate(value)
                with self.assertRaisesRegex(
                    states.NerivaneSiteStateError,
                    "NERIVANE_ACTIVE_DATA_SCHEMA_INVALID",
                ):
                    states.validate_active_data(
                        canonical(value),
                        release_id=self.release_id,
                        release_root=release_root,
                        expected_source_commit="a" * 40,
                    )

    def test_rejects_forgery_in_every_nested_active_data_section(self) -> None:
        self.promote()
        data_path = self.site / states.DATA_RELATIVE
        original = json.loads(data_path.read_bytes())
        release_root = self.site / "assets/validated-releases/nerivane-v2" / self.release_id
        mutations = (
            ("metrics", lambda value: value["metrics"][0].update({"scope": ""}), "NERIVANE_ACTIVE_DATA_METRICS_INVALID"),
            ("steps", lambda value: value["steps"][4].update({"status": "FORGED"}), "NERIVANE_ACTIVE_DATA_STEPS_INVALID"),
            ("evidence", lambda value: value["evidence"][1].update({"label": "preuve auto-déclarée"}), "NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID"),
            ("boundaries", lambda value: value["boundaries"][0].update({"text": "certifié sans limite"}), "NERIVANE_ACTIVE_DATA_BOUNDARIES_INVALID"),
            ("publication", lambda value: value["publication_boundary"].update({"ai_model_deployment_status": "DEPLOYED"}), "NERIVANE_ACTIVE_DATA_PUBLICATION_INVALID"),
        )
        for label, mutate, code in mutations:
            with self.subTest(section=label):
                value = deepcopy(original)
                mutate(value)
                with self.assertRaisesRegex(states.NerivaneSiteStateError, code):
                    states.validate_active_data(
                        canonical(value), release_id=self.release_id,
                        release_root=release_root, expected_source_commit="a" * 40,
                    )

    def test_rejects_semantically_forged_self_declared_evidence(self) -> None:
        self.promote()
        active = json.loads((self.site / states.DATA_RELATIVE).read_bytes())
        release_root = self.site / "assets/validated-releases/nerivane-v2" / self.release_id
        cases = (
            ("replay-v2", "replay-manifest.json", lambda value: value.update({"status": "FORGED"}), "NERIVANE_ACTIVE_REPLAY_EVIDENCE_INVALID"),
            ("full-h1", "evidence/full-h1-final-public.json", lambda value: value["execution"].update({"triplet_count": 1_319}), "NERIVANE_ACTIVE_H1_EVIDENCE_INVALID"),
            ("park-resources", "evidence/resource-windows/manifest.json", lambda value: value["summary"].update({"active_process_windows": 4}), "NERIVANE_ACTIVE_RESOURCE_EVIDENCE_INVALID"),
            ("sample-controls", "evidence/bigquery-h1-sample-public.json", lambda value: value["materialization"].update({"table_count": 16}), "NERIVANE_ACTIVE_SAMPLE_EVIDENCE_INVALID"),
            ("ai-fail-closed", "evidence/ai-local-fail-closed.json", lambda value: value["model"].update({"deployment_status": "DEPLOYED"}), "NERIVANE_ACTIVE_AI_EVIDENCE_INVALID"),
            ("ai-fail-closed", "evidence/ai-local-fail-closed.json", lambda value: value["publication_gate"].update({"status": "UNBLOCKED"}), "NERIVANE_ACTIVE_AI_EVIDENCE_INVALID"),
            ("ai-fail-closed", "evidence/ai-local-fail-closed.json", lambda value: value["safety"].update({"kpi_calculated_or_certified_by_ai": True}), "NERIVANE_ACTIVE_AI_EVIDENCE_INVALID"),
        )
        for evidence_id, relative, mutate, code in cases:
            with self.subTest(evidence=evidence_id):
                target = release_root / relative
                original_payload = target.read_bytes()
                original_mode = stat.S_IMODE(target.stat().st_mode)
                value = json.loads(original_payload)
                mutate(value)
                forged_payload = canonical(value)
                target.chmod(0o600)
                target.write_bytes(forged_payload)
                target.chmod(original_mode)
                forged_active = deepcopy(active)
                item = next(item for item in forged_active["evidence"] if item["id"] == evidence_id)
                item["sha256"] = hashlib.sha256(forged_payload).hexdigest()
                try:
                    with self.assertRaisesRegex(states.NerivaneSiteStateError, code):
                        states.validate_active_data(
                            canonical(forged_active), release_id=self.release_id,
                            release_root=release_root, expected_source_commit="a" * 40,
                        )
                finally:
                    target.chmod(0o600)
                    target.write_bytes(original_payload)
                    target.chmod(original_mode)

    def test_rejects_an_evidence_digest_not_bound_to_the_release(self) -> None:
        self.promote()
        data_path = self.site / states.DATA_RELATIVE
        value = json.loads(data_path.read_bytes())
        value["evidence"][2]["sha256"] = "f" * 64
        release_root = (
            self.site
            / "assets/validated-releases/nerivane-v2"
            / self.release_id
        )

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_ACTIVE_DATA_EVIDENCE_INVALID",
        ):
            states.validate_active_data(
                canonical(value),
                release_id=self.release_id,
                release_root=release_root,
                expected_source_commit="a" * 40,
            )

    def test_rejects_fissures_ormevia_or_v1_protected_tree_changes(self) -> None:
        self.promote()
        representatives = (
            "demonstrations/fissures.html",
            "demonstrations/ormevia-batiment.html",
            "assets/css/demo-ormevia.css",
            "assets/data/ormevia-scenarios.json",
            "assets/js/demo-ormevia.js",
            "assets/nerivane-public-v1/index.html",
        )
        for relative in representatives:
            with self.subTest(relative=relative):
                target = self.site / relative
                original = target.read_bytes()
                target.write_bytes(original + b" changed")
                try:
                    with self.assertRaisesRegex(
                        states.NerivaneSiteStateError,
                        "NERIVANE_PROTECTED_TREE_CHANGED",
                    ):
                        self.validate()
                finally:
                    target.write_bytes(original)

    def _assert_modes_rejected(self, *, active: bool) -> None:
        if active:
            self.promote()
        targets = (
            ".",
            *states.PROMOTED_TARGETS,
            "demonstrations",
            "assets",
            "assets/data",
            "assets/js",
            "assets/css",
            "assets/figures",
            "assets/img",
            "assets/validated-releases",
            "contracts",
        )
        for relative in targets:
            with self.subTest(active=active, target=relative):
                target = self.site / relative
                original_mode = stat.S_IMODE(target.stat().st_mode)
                target.chmod(0o600 if target.is_file() else 0o700)
                try:
                    with self.assertRaisesRegex(
                        states.NerivaneSiteStateError,
                        "NERIVANE_SITE_PATH_CONTRACT_INVALID",
                    ):
                        self.validate()
                finally:
                    target.chmod(original_mode)

    def test_rejects_wrong_modes_in_maintenance(self) -> None:
        self._assert_modes_rejected(active=False)

    def test_rejects_wrong_modes_when_active(self) -> None:
        self._assert_modes_rejected(active=True)

    def _assert_symlink_ancestor_rejected(self, *, active: bool) -> None:
        if active:
            self.promote()
        ancestors = (
            *states.PROMOTED_TARGETS,
            "demonstrations",
            "assets",
            "assets/data",
            "assets/js",
            "assets/css",
            "assets/figures",
            "assets/img",
            "assets/validated-releases",
            "contracts",
        )
        for relative in ancestors:
            with self.subTest(active=active, ancestor=relative):
                target = self.site / relative
                was_directory = target.is_dir()
                original = target.with_name(target.name + ".real")
                target.rename(original)
                target.symlink_to(original.name, target_is_directory=was_directory)
                try:
                    with self.assertRaisesRegex(
                        states.NerivaneSiteStateError,
                        "NERIVANE_SITE_PATH_CONTRACT_INVALID",
                    ):
                        self.validate()
                finally:
                    target.unlink()
                    original.rename(target)

    def test_rejects_symlink_ancestors_in_maintenance(self) -> None:
        self._assert_symlink_ancestor_rejected(active=False)

    def test_rejects_symlink_ancestors_when_active(self) -> None:
        self._assert_symlink_ancestor_rejected(active=True)

    def test_rejects_a_symlink_site_root_in_both_states(self) -> None:
        for active in (False, True):
            if active:
                self.promote()
            with self.subTest(active=active):
                original = self.site.with_name(self.site.name + ".real")
                self.site.rename(original)
                self.site.symlink_to(original.name, target_is_directory=True)
                try:
                    with self.assertRaisesRegex(
                        states.NerivaneSiteStateError,
                        "NERIVANE_SITE_ROOT_INVALID",
                    ):
                        self.validate()
                finally:
                    self.site.unlink()
                    original.rename(self.site)

    def test_active_javascript_is_fail_closed_for_four_fetch_outcomes(self) -> None:
        self.promote()
        script = (self.site / states.SCRIPT_RELATIVE).read_text(encoding="utf-8")
        data = json.loads((self.site / states.DATA_RELATIVE).read_bytes())
        harness = r'''
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
class FakeNode {
  constructor() { this.dataset = {}; this.attributes = {}; this.children = []; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  querySelector(selector) { return selector === "[data-state-label]" ? label : null; }
}
const root = new FakeNode();
const page = new FakeNode();
page.dataset.releaseId = input.releaseId;
const header = new FakeNode();
const label = new FakeNode();
header.dataset.status = "verification";
header.attributes["aria-busy"] = "true";
global.document = {
  body: page,
  getElementById: (id) => ({"nerivane-reader": root, "nerivane-public-state": header}[id] || null),
  createElement: () => new FakeNode(),
  createDocumentFragment: () => new FakeNode(),
};
global.fetch = async () => {
  if (input.scenario === "404") return {ok: false, json: async () => input.data};
  if (input.scenario === "invalid-json") return {ok: true, json: async () => { throw new SyntaxError("invalid JSON"); }};
  const data = JSON.parse(JSON.stringify(input.data));
  if (input.scenario === "invalid-schema") data.status = "FORGED";
  return {ok: true, json: async () => data};
};
eval(input.script);
setTimeout(() => process.stdout.write(JSON.stringify({
  status: header.dataset.status,
  label: label.textContent,
  busy: header.attributes["aria-busy"],
  aria: header.attributes["aria-label"],
})), 30);
'''
        expected = {
            "valid": ("valide", "Replay scellé", "Replay authentifié et scellé"),
            "404": ("indisponible", "Indisponible / non authentifié", "Replay public indisponible ou non authentifié"),
            "invalid-json": ("indisponible", "Indisponible / non authentifié", "Replay public indisponible ou non authentifié"),
            "invalid-schema": ("indisponible", "Indisponible / non authentifié", "Replay public indisponible ou non authentifié"),
        }
        for scenario, (status, label, aria) in expected.items():
            with self.subTest(scenario=scenario):
                completed = subprocess.run(
                    ["node", "-e", harness],
                    input=json.dumps({"script": script, "data": data, "releaseId": self.release_id, "scenario": scenario}),
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                observed = json.loads(completed.stdout)
                self.assertEqual(observed, {"status": status, "label": label, "busy": "false", "aria": aria})

    def test_rejects_a_catalogue_change_outside_the_nerivane_fragment(self) -> None:
        self.promote()
        catalogue = self.site / states.CATALOGUE_RELATIVE
        catalogue.write_bytes(
            catalogue.read_bytes().replace(b"fissures", b"fissure-alt", 1)
        )

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_CATALOGUE_OUTSIDE_CHANGED",
        ):
            self.validate()

    def test_demo2_must_remain_in_maintenance_even_with_a_rebased_baseline(self) -> None:
        self.promote()
        fissures = self.site / "demonstrations/fissures.html"
        fissures.write_bytes(
            fissures.read_bytes().replace(
                b'data-maintenance="true"',
                b'data-maintenance="false"',
                1,
            )
        )
        rebased = states.capture_baseline(self.site)

        with self.assertRaisesRegex(
            states.NerivaneSiteStateError,
            "NERIVANE_DEMO2_MAINTENANCE_CHANGED",
        ):
            states.validate_site_state(site_root=self.site, baseline=rebased)


if __name__ == "__main__":
    unittest.main()
