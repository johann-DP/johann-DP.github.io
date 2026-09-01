from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Thread
import unittest


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

        self.assertEqual(len(observed), 45)
        self.assertEqual(sum(item.category == "figure" for item in observed), 15)
        self.assertEqual(
            sum(item.category == "demo2_integration" for item in observed),
            21,
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

    def test_rejects_a_local_manifest_without_fifteen_unique_masters(self) -> None:
        manifest = self.expected / "assets/figures/demo-2/content-manifest.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["files"].pop()
        manifest.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(
            production.AttestationError,
            "exactement 15 maîtres HTML uniques attendus",
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
        self.assertEqual(len(staged), 19)
        self.assertTrue(
            all(result["release_id"] in item.path.parts for item in staged)
        )


if __name__ == "__main__":
    unittest.main()
