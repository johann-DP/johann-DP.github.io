from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import attest_production as production  # noqa: E402
import import_nerivane_v2_release as nerivane_v2  # noqa: E402
from tests.test_import_nerivane_v2_release import build_source  # noqa: E402


FIGURES = (
    "building-geometry.html",
    "01-historical-crack-analysis-compacted-v2.html",
    "fissure-recente-meme-format.html",
    "joint-dilatation-rendu-site.html",
    "retaining-wall-sensor-source-values.html",
    "retaining-wall-sensor-processed-v2.html",
    "retaining-wall-extrema-hours.html",
    "retaining-wall-median-day.html",
    "weather/legacy/meteo_temperature.html",
    "weather/legacy/meteo_temp_minmax.html",
    "weather/legacy/meteo_humidity.html",
    "weather/legacy/meteo_light_uv.html",
    "weather/legacy/meteo_precipitation.html",
    "weather/legacy/meteo_wind_speed.html",
    "weather/legacy/meteo_wind_dir.html",
    "weather/legacy/meteo_pairplots.html",
    "weather/complements/meteo_explorateur_toutes_mesures.html",
    "weather/complements/meteo_qualite_acquisition.html",
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve(directory: Path):
    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(directory), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.name,
        "role": "responsive_html_master",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def build_tree(root: Path) -> None:
    figure_root = root / "assets/figures/demo-2"
    manifests: dict[Path, list[dict[str, object]]] = {
        figure_root / "content-manifest.json": [],
        figure_root / "weather/content-manifest.json": [],
    }
    for index, relative in enumerate(FIGURES):
        path = figure_root / relative
        payload = f"<!doctype html><title>figure {index}</title>".encode()
        entry = write(path, payload)
        if relative.startswith("weather/"):
            manifest_path = figure_root / "weather/content-manifest.json"
            entry["path"] = Path(relative).relative_to("weather").as_posix()
        else:
            manifest_path = figure_root / "content-manifest.json"
            entry["path"] = relative
        manifests[manifest_path].append(entry)

    for manifest_path, entries in manifests.items():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"files": entries}), encoding="utf-8")

    for relative in production.INTEGRATION_PATHS:
        path = root / Path(*relative.parts)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"integration:{relative}".encode())

    for relative in production.NERIVANE_INTEGRATION_PATHS:
        path = root / Path(*relative.parts)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"nerivane-integration:{relative}".encode())

    bundle = root / Path(*production.NERIVANE_BUNDLE_ROOT.parts)
    payloads = {
        "index.html": b"<!doctype html><title>Nerivane</title>",
        "replay-manifest.json": b'{"status":"maintenance"}\n',
        "steps/01.html": b"<!doctype html><title>Step 1</title>",
    }
    for relative, payload in payloads.items():
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (bundle / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(payload).hexdigest()}  {relative}\n"
            for relative, payload in sorted(payloads.items())
        ),
        encoding="ascii",
    )


class ProductionAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary.name)
        self.expected = temporary_root / "expected"
        self.remote = temporary_root / "remote"
        build_tree(self.expected)
        shutil.copytree(self.expected, self.remote)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_attests_demo2_and_the_complete_active_nerivane_tree(self) -> None:
        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            observed = production.attest(self.expected, base_url, timeout_seconds=2)

        self.assertEqual(len(observed), 68)
        self.assertEqual(sum(item.category == "figure" for item in observed), 18)
        self.assertEqual(
            sum(item.category == "demo2_integration" for item in observed),
            41,
        )
        self.assertEqual(
            sum(item.category == "nerivane_integration" for item in observed),
            5,
        )
        self.assertEqual(
            sum(item.category == "nerivane_bundle" for item in observed),
            4,
        )

    def test_rejects_remote_content_divergence_explicitly(self) -> None:
        relative = Path("assets/figures/demo-2/fissure-recente-meme-format.html")
        (self.remote / relative).write_bytes(b"divergent")

        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(
                production.AttestationError,
                r"fissure-recente-meme-format\.html non attesté.*contenu divergent",
            ):
                production.attest(
                    self.expected,
                    base_url,
                    attempts=2,
                    retry_delay_seconds=0,
                    timeout_seconds=2,
                )

    def test_rejects_remote_m12_data_divergence_explicitly(self) -> None:
        relative = Path("assets/analyses/demo-2/m12/data/forecast.json")
        (self.remote / relative).write_bytes(b"divergent")

        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(
                production.AttestationError,
                r"assets/analyses/demo-2/m12/data/forecast\.json non attesté"
                r".*contenu divergent",
            ):
                production.attest(
                    self.expected,
                    base_url,
                    attempts=2,
                    retry_delay_seconds=0,
                    timeout_seconds=2,
                )

    def test_m12_inventory_is_closed_and_explicit(self) -> None:
        expected_subtree = (
            "assets/demo-fissures.css",
            "assets/logo-datapredict.png",
            "assets/m12-live.js",
            "assets/m12.css",
            "assets/m12.js",
            "assets/plotly.min.js",
            "assets/plotly.min.js.LICENSE.txt",
            "assets/site.css",
            "data/factors.json",
            "data/forecast.json",
            "data/pruning.json",
            "pages/factors.html",
            "pages/forecast.html",
            "pages/pruning.html",
        )
        self.assertEqual(
            tuple(
                path.relative_to(production.M12_ROOT).as_posix()
                for path in production.M12_INTEGRATION_PATHS
            ),
            expected_subtree,
        )
        repository_root = Path(__file__).resolve().parents[1]
        m12_root = repository_root / Path(*production.M12_ROOT.parts)
        actual_subtree = tuple(
            sorted(
                path.relative_to(m12_root).as_posix()
                for path in m12_root.rglob("*")
                if path.is_file()
            )
        )
        self.assertEqual(actual_subtree, expected_subtree)
        self.assertEqual(
            production.M12_THUMBNAIL_NAMES,
            (
                "tested-factors.webp",
                "recent-crack-forecasts.webp",
                "pruning-follow-up.webp",
            ),
        )
        self.assertTrue(
            set(production.M12_INTEGRATION_PATHS).issubset(
                production.INTEGRATION_PATHS
            )
        )
        self.assertTrue(
            {
                production.THUMBNAIL_ROOT / name
                for name in production.M12_THUMBNAIL_NAMES
            }.issubset(production.INTEGRATION_PATHS)
        )

    def test_cli_returns_nonzero_for_a_missing_remote_file(self) -> None:
        relative = Path("sitemap.xml")
        (self.remote / relative).unlink()
        stdout = StringIO()
        stderr = StringIO()

        with (
            serve(self.remote) as base_url,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = production.main(
                (
                    "--root",
                    str(self.expected),
                    "--base-url",
                    base_url,
                    "--timeout-seconds",
                    "2",
                )
            )

        self.assertEqual(status, 1)
        self.assertIn("ATTESTATION_FAILED", stderr.getvalue())
        self.assertRegex(stderr.getvalue(), r"sitemap\.xml non attesté.*HTTP Error 404")

    def test_rejects_a_local_manifest_without_eighteen_unique_masters(self) -> None:
        manifest = self.expected / "assets/figures/demo-2/content-manifest.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["files"].pop()
        manifest.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(
            production.AttestationError,
            "exactement 18 maîtres HTML uniques attendus",
        ):
            production.load_expected_files(self.expected)

    def test_rejects_an_unlisted_file_in_the_active_nerivane_subtree(self) -> None:
        stray = self.expected / "assets/nerivane-public-v1/stray.json"
        stray.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(
            production.AttestationError,
            "inventaire local divergent des sommes",
        ):
            production.load_expected_files(self.expected)

    def test_rejects_remote_nerivane_data_divergence(self) -> None:
        relative = Path("assets/data/nerivane-governance-replay.json")
        (self.remote / relative).write_bytes(b"divergent")

        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(
                production.AttestationError,
                r"nerivane-governance-replay\.json non attesté.*contenu divergent",
            ):
                production.attest(self.expected, base_url, timeout_seconds=2)

    def test_attests_every_file_of_a_staged_nerivane_v2_release(self) -> None:
        sources = Path(self.temporary.name) / "sources"
        sources.mkdir()
        source = build_source(sources)
        result = nerivane_v2.import_release(source, site_root=self.expected)
        shutil.rmtree(self.remote)
        shutil.copytree(self.expected, self.remote)

        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            observed = production.attest(self.expected, base_url, timeout_seconds=2)

        staged = [item for item in observed if item.category == "nerivane_v2_staged"]
        self.assertEqual(len(staged), 27)
        self.assertTrue(
            all(result["release_id"] in item.path.parts for item in staged)
        )


class ProductionReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receipt = self.root / "receipt.json"
        self.summary = self.root / "summary.md"
        self.sha = "a" * 40
        self.expected = (
            production.ExpectedFile(
                production.PurePosixPath("figure.html"), "b" * 64, 123, "figure"
            ),
        )
        self.arguments = [
            "--root", str(self.root), "--source-commit", self.sha,
            "--pages-run-id", "1234", "--attestation-run-id", "5678",
            "--receipt", str(self.receipt), "--summary-path", str(self.summary),
        ]

    def test_receipt_and_single_summary_bind_success_to_the_checked_out_commit(self) -> None:
        with (
            patch.object(production.subprocess, "check_output", return_value=self.sha + "\n") as git,
            patch.object(production, "attest", return_value=self.expected),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(production.main(self.arguments), 0)

        git.assert_called_once_with(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True, stderr=subprocess.PIPE
        )
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "production-attestation/1")
        self.assertEqual(receipt["status"], "ATTESTED")
        self.assertEqual(receipt["source_commit"], self.sha)
        self.assertEqual(receipt["pages_run_id"], 1234)
        self.assertEqual(receipt["attestation_run_id"], 5678)
        self.assertEqual(receipt["file_count"], 1)
        self.assertEqual(receipt["byte_count"], 123)
        self.assertRegex(receipt["inventory_sha256"], r"^[a-f0-9]{64}$")
        self.assertTrue(receipt["completed_at"].endswith("+00:00"))
        summary = self.summary.read_text(encoding="utf-8")
        self.assertEqual(summary.count("## Publication vérifiée"), 1)
        self.assertIn(self.sha, summary)
        self.assertIn("pas la validité scientifique", summary)

    def test_checkout_at_a_newer_tip_is_rejected_before_any_network_call(self) -> None:
        with (
            patch.object(production.subprocess, "check_output", return_value="c" * 40 + "\n"),
            patch.object(production, "attest") as attest,
            redirect_stderr(StringIO()) as error,
        ):
            self.assertEqual(production.main(self.arguments), 1)
        self.assertIn("ne correspond pas", error.getvalue())
        attest.assert_not_called()
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.summary.exists())

    def test_failed_remote_attestation_never_emits_a_success_receipt_or_summary(self) -> None:
        with (
            patch.object(production.subprocess, "check_output", return_value=self.sha),
            patch.object(production, "attest", side_effect=production.AttestationError("divergence")),
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(production.main(self.arguments), 1)
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.summary.exists())

    def test_existing_receipt_cannot_be_reused_as_fresh_evidence(self) -> None:
        self.receipt.write_text("previous evidence", encoding="utf-8")
        with patch.object(production, "attest") as attest, redirect_stderr(StringIO()):
            self.assertEqual(production.main(self.arguments), 1)
        attest.assert_not_called()
        self.assertEqual(self.receipt.read_text(encoding="utf-8"), "previous evidence")

    def test_invalid_or_missing_source_commit_is_rejected_before_network(self) -> None:
        for source_commit in (None, "main", "A" * 40, "a" * 39, "a" * 40 + "\n"):
            with self.subTest(source_commit=source_commit):
                arguments = ["--receipt", str(self.receipt)]
                if source_commit is not None:
                    arguments.extend(["--source-commit", source_commit])
                with patch.object(production, "attest") as attest, redirect_stderr(StringIO()):
                    self.assertEqual(production.main(arguments), 1)
                attest.assert_not_called()

    def test_checkout_identity_failure_is_not_reported_as_a_valid_publication(self) -> None:
        with (
            patch.object(
                production.subprocess, "check_output",
                side_effect=subprocess.CalledProcessError(128, "git"),
            ),
            patch.object(production, "attest") as attest,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(production.main(self.arguments), 1)
        attest.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_run_identifiers_are_numeric_or_absent_for_the_daily_audit(self) -> None:
        self.assertIsNone(production._run_identifier("", "Pages"))
        self.assertEqual(production._run_identifier("123", "Pages"), 123)
        for invalid in ("0", "-1", "1\n", "1.5", "１２", "false"):
            with self.subTest(invalid=invalid), self.assertRaises(production.AttestationError):
                production._run_identifier(invalid, "Pages")

    def test_receipt_requires_its_own_github_run_identity(self) -> None:
        arguments = self.arguments.copy()
        arguments[arguments.index("--attestation-run-id") + 1] = ""
        with (
            patch.object(production.subprocess, "check_output", return_value=self.sha),
            patch.object(production, "attest") as attest,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(production.main(arguments), 1)
        attest.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_inventory_digest_is_order_independent_and_changes_with_public_bytes(self) -> None:
        other = production.ExpectedFile(
            production.PurePosixPath("other.html"), "c" * 64, 42, "figure"
        )
        arguments = dict(
            source_commit=self.sha, base_url="https://www.datapredict.org/",
            pages_run_id=None, attestation_run_id=5678,
        )
        first = production.build_receipt((*self.expected, other), **arguments)
        reverse = production.build_receipt((other, *self.expected), **arguments)
        changed = production.build_receipt(self.expected, **arguments)
        self.assertEqual(first["inventory_sha256"], reverse["inventory_sha256"])
        self.assertNotEqual(first["inventory_sha256"], changed["inventory_sha256"])
        self.assertIsNone(first["pages_run_id"])
        self.assertEqual(first["base_url"], "https://www.datapredict.org")


if __name__ == "__main__":
    unittest.main()
