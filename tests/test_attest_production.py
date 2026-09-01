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

    def test_attests_exactly_fifteen_figures_and_seven_integration_files(self) -> None:
        with serve(self.remote) as base_url, redirect_stdout(StringIO()):
            observed = production.attest(self.expected, base_url, timeout_seconds=2)

        self.assertEqual(len(observed), 22)
        self.assertEqual(sum(item.category == "figure" for item in observed), 15)
        self.assertEqual(sum(item.category == "integration" for item in observed), 7)

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


if __name__ == "__main__":
    unittest.main()
