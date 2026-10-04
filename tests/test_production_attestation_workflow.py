"""Regression guards for the GitHub event and exact-deployment identity contract.

These source checks prevent reintroducing the known notification burst. GitHub's
delivery of workflow_run remains an integration check on the next real Pages run.
"""

from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/production-attestation.yml"


class ProductionAttestationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.trigger = self.workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    def test_intermediate_pages_states_no_longer_create_workflow_runs(self) -> None:
        self.assertNotIn("deployment_status", self.workflow)
        self.assertEqual(self.trigger.count("  workflow_run:\n"), 1)
        self.assertIn("    workflows: [pages-build-deployment]\n", self.trigger)
        self.assertIn("    types: [completed]\n", self.trigger)
        self.assertIn("    branches: [main]\n", self.trigger)
        for intermediate in ("waiting", "queued", "in_progress", "requested"):
            self.assertNotIn(intermediate, self.trigger)

    def test_only_successful_same_repository_main_pages_runs_are_attested(self) -> None:
        for guard in (
            "github.event_name != 'workflow_run' ||",
            "github.event.workflow_run.conclusion == 'success' &&",
            "github.event.workflow_run.head_branch == 'main' &&",
            "github.event.workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(guard, self.workflow)

    def test_checkout_and_receipt_use_the_deployed_sha_not_the_newest_main(self) -> None:
        identity = "${{ github.event.workflow_run.head_sha || github.sha }}"
        self.assertIn(f"run-name: Attestation production · {identity}", self.workflow)
        self.assertIn(f"      ATTESTED_COMMIT: {identity}\n", self.workflow)
        self.assertIn(f"          ref: {identity}\n", self.workflow)
        self.assertIn('--source-commit "$ATTESTED_COMMIT"', self.workflow)
        self.assertIn('--pages-run-id "$PAGES_RUN_ID"', self.workflow)
        self.assertIn('--attestation-run-id "$GITHUB_RUN_ID"', self.workflow)

    def test_replayed_old_deployment_uses_current_runner_not_its_historical_script(self) -> None:
        self.assertIn("          ref: ${{ github.sha }}\n", self.workflow)
        self.assertIn("          path: attestation-runner\n", self.workflow)
        self.assertIn("          path: deployed-site\n", self.workflow)
        self.assertIn("working-directory: attestation-runner", self.workflow)
        self.assertIn("python3 attestation-runner/scripts/attest_production.py", self.workflow)
        self.assertIn('--root "$GITHUB_WORKSPACE/deployed-site"', self.workflow)
        self.assertNotIn("python3 deployed-site/scripts/", self.workflow)

    def test_daily_safety_audit_and_manual_recovery_are_kept(self) -> None:
        self.assertIn('  schedule:\n    - cron: "17 05 * * *"\n', self.trigger)
        self.assertIn("  workflow_dispatch:\n", self.trigger)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_one_native_summary_and_success_only_evidence_without_extra_messages(self) -> None:
        self.assertEqual(self.workflow.count('--summary-path "$GITHUB_STEP_SUMMARY"'), 1)
        self.assertEqual(self.workflow.count("uses: actions/upload-artifact@"), 1)
        self.assertIn("name: production-attestation-${{ env.ATTESTED_COMMIT }}", self.workflow)
        self.assertIn("path: ${{ runner.temp }}/production-attestation.json", self.workflow)
        self.assertIn("if-no-files-found: error", self.workflow)
        self.assertIn("overwrite: true", self.workflow)
        self.assertNotIn("if: always()", self.workflow)
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("issues: write", self.workflow)
        self.assertNotIn("pull-requests: write", self.workflow)


if __name__ == "__main__":
    unittest.main()
