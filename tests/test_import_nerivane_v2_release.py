from __future__ import annotations

import hashlib
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_nerivane_v2_release as importer  # noqa: E402


def block_before_directory_publish(
    source: str,
    site: str,
    ready_connection: Connection,
) -> None:
    def pause_before_publish(source_path: Path, destination_path: Path) -> None:
        ready_connection.send(
            {
                "destination": destination_path.as_posix(),
                "source": source_path.as_posix(),
            }
        )
        ready_connection.close()
        while True:
            signal.pause()

    with patch.object(
        importer,
        "_rename_noreplace",
        side_effect=pause_before_publish,
    ):
        importer.import_release(Path(source), site_root=Path(site))


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def record(path: str, role: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "role": role,
        "sha256": digest(payload),
        "size_bytes": len(payload),
    }


def source_payloads(
    *,
    replay_status: str = "SEALED_PUBLIC_REPLAY",
    replay_contract_id: str = importer.REPLAY_CONTRACT_ID,
    promotion_contract_payload: bytes | None = None,
    private_token: str | None = None,
) -> dict[str, tuple[str, bytes]]:
    release_placeholder = "__NERIVANE_V2_RELEASE_ID__"
    payloads: dict[str, tuple[str, bytes]] = {
        "index.html": (
            "public_html",
            b"<!doctype html><html lang='fr'><title>Nerivane V2</title></html>",
        ),
        "replay-manifest.json": (
            "public_json",
            canonical(
                {
                    "contract_id": replay_contract_id,
                    "counts": {"steps": 7},
                    "fictional": True,
                    "status": replay_status,
                }
            ),
        ),
        "evidence/full-h1-proof.json": (
            "public_evidence",
            canonical({"status": "VALIDÉ", "volume": "1.75 Tio"}),
        ),
        importer.PROMOTION_MANIFEST_PATH: (
            "public_json",
            promotion_contract_payload
            if promotion_contract_payload is not None
            else importer.PROMOTION_CONTRACT_PATH.read_bytes(),
        ),
        "activation/demonstrations/nerivane-distribution.html": (
            "public_html",
            (
                "<!doctype html><html lang=\"fr\"><head>"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<link rel=\"stylesheet\" href=\"../assets/css/site.css\">"
                "<link rel=\"stylesheet\" href=\"../assets/css/demo-nerivane.css\">"
                "<script src=\"../assets/js/demo-nerivane.js\" defer></script>"
                "<script src=\"../assets/js/audience-counter.js\" defer></script>"
                "<title>Nerivane V2</title></head><body><h1>Nerivane V2 active</h1>"
                "<a href=\"../assets/validated-releases/nerivane-v2/"
                f"{release_placeholder}/index.html\">Replay V2</a></body></html>"
            ).encode("utf-8"),
        ),
        "activation/assets/data/nerivane-governance-replay.json": (
            "public_json",
            canonical(
                {
                    "bundle": (
                        "../assets/validated-releases/nerivane-v2/"
                        f"{release_placeholder}/replay-manifest.json"
                    ),
                    "formatVersion": "2.0.0",
                    "status": "SEALED_PUBLIC_REPLAY",
                }
            ),
        ),
        "activation/assets/js/demo-nerivane.js": (
            "public_script",
            b'"use strict"; document.documentElement.dataset.nerivane = "v2";\n',
        ),
        "activation/assets/css/demo-nerivane.css": (
            "public_stylesheet",
            b".nerivane-demo-page { display: block; }\n@media (max-width: 48rem) { .nerivane-demo-page { width: 100%; } }\n",
        ),
        "activation/fragments/demonstrations-nerivane-card.html": (
            "public_html",
            (
                "<li><article class=\"demonstrations-page__card\">"
                "<a class=\"demonstrations-page__card-link\" "
                "href=\"demonstrations/nerivane-distribution.html\" "
                "aria-labelledby=\"nerivane-title\">"
                "<h3 id=\"nerivane-title\">Nérivane Distribution</h3>"
                "<span class=\"demonstrations-page__card-status\">Disponible</span>"
                "<span data-release=\""
                f"assets/validated-releases/nerivane-v2/{release_placeholder}"
                "\">Consulter la démonstration</span></a></article></li>"
            ).encode("utf-8"),
        ),
    }
    for index in range(1, 8):
        body = f"<!doctype html><html lang='fr'><title>Etape {index}</title></html>"
        if private_token and index == 4:
            body += private_token
        payloads[f"steps/{index:02d}.html"] = ("public_html", body.encode("utf-8"))
    checksum = "".join(
        f"{digest(payload)}  {path}\n"
        for path, (_, payload) in sorted(payloads.items())
    ).encode("ascii")
    payloads["SHA256SUMS"] = ("public_checksum", checksum)
    return payloads


def build_source(
    parent: Path,
    *,
    replay_status: str = "SEALED_PUBLIC_REPLAY",
    replay_contract_id: str = importer.REPLAY_CONTRACT_ID,
    promotion_contract_payload: bytes | None = None,
    private_token: str | None = None,
    gates: dict[str, str] | None = None,
) -> Path:
    payloads = source_payloads(
        replay_status=replay_status,
        replay_contract_id=replay_contract_id,
        promotion_contract_payload=promotion_contract_payload,
        private_token=private_token,
    )
    identity: dict[str, object] = {
        "contract_id": importer.CONTRACT_ID,
        "files": [
            record(path, role, payload)
            for path, (role, payload) in sorted(payloads.items())
        ],
        "gates": gates or dict(importer.GATES),
        "manifest_version": 2,
        "publication": dict(importer.PUBLICATION),
        "source": {
            "commit": "a" * 40,
            "repository": importer.REPOSITORY,
        },
        "state": importer.STATE,
    }
    release_id = digest(canonical(identity))
    manifest = canonical({**identity, "release_id": release_id})
    root = parent / release_id
    root.mkdir(mode=0o700)
    for relative, payload in sorted(
        {
            **{path: payload for path, (_, payload) in payloads.items()},
            importer.MANIFEST_PATH: manifest,
            importer.READY_PATH: importer.READY_CONTENT,
        }.items()
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(payload)
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    for path in (path for path in root.rglob("*") if path.is_file()):
        path.chmod(0o444 if path.name == importer.READY_PATH else 0o400)
    root.chmod(0o700)
    return root


def build_site(root: Path) -> None:
    active = {
        "demonstrations/nerivane-distribution.html": (
            b'<!doctype html><html lang="fr"><head><meta name="viewport" '
            b'content="width=device-width, initial-scale=1"></head><body>'
            b'<span data-maintenance="true">Maintenance</span><h1>Nerivane</h1>'
            b'</body></html>'
        ),
        "assets/data/nerivane-governance-replay.json": b"maintenance data",
        "assets/js/demo-nerivane.js": b"maintenance js",
        "assets/css/demo-nerivane.css": b"maintenance css",
        "demonstrations.html": (
            b'<!doctype html><html lang="fr"><body><ul>\n'
            b'<!-- NERIVANE_CATALOGUE_CARD_START -->\n'
            b'<li><a aria-labelledby="nerivane-title"><h3 id="nerivane-title">'
            b'Nerivane</h3><span>Maintenance</span></a></li>\n'
            b'<!-- NERIVANE_CATALOGUE_CARD_END -->\n'
            b'<li id="fissures">Fissures</li></ul></body></html>'
        ),
        "assets/nerivane-public-v1/SHA256SUMS": b"legacy sums",
        "assets/nerivane-public-v1/index.html": b"legacy replay",
        "demonstrations/fissures.html": b"protected fissures page",
        "assets/css/demo-fissures.css": b"protected fissures css",
        "assets/css/site.css": b"protected responsive site css",
        "assets/js/audience-counter.js": b"protected audience counter",
        "assets/js/demo-fissures.js": b"protected fissures js",
        "assets/figures/demo-2/content-manifest.json": b"protected demo2 figures",
        "assets/img/demo-2-thumbnails/figure.webp": b"protected demo2 thumbnail",
        "assets/validated-releases/demo-2/release/.READY": b"protected demo2 release",
    }
    for relative, payload in active.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


class NerivaneV2ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.site = self.root / "site"
        self.site.mkdir()
        build_site(self.site)
        self.active_before = hashes(self.site)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_imports_exact_closed_release_without_changing_active_maintenance(self) -> None:
        source = build_source(self.sources)

        result = importer.import_release(source, site_root=self.site)

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["state"], "IMPORTED_INACTIVE")
        self.assertEqual(result["published_file_count"], 17)
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (result["release_id"],),
        )
        destination = (
            self.site
            / "assets/validated-releases/nerivane-v2"
            / result["release_id"]
        )
        self.assertTrue((destination / ".READY").is_file())
        self.assertTrue((destination / "steps/07.html").is_file())
        for path in destination.rglob("*"):
            expected_mode = 0o755 if path.is_dir() else 0o644
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected_mode)
        self.assertEqual(
            {key: value for key, value in hashes(self.site).items() if key in self.active_before},
            self.active_before,
        )

    def test_identical_reimport_is_idempotent(self) -> None:
        source = build_source(self.sources)
        first = importer.import_release(source, site_root=self.site)

        second = importer.import_release(source, site_root=self.site)

        self.assertEqual(second["release_id"], first["release_id"])
        self.assertEqual(second["status"], "ALREADY_PRESENT")

    def test_rejects_any_unvalidated_final_gate(self) -> None:
        gates = dict(importer.GATES)
        gates["full_h1"] = "EXÉCUTÉ_NON_VALIDÉ"
        source = build_source(self.sources, gates=gates)

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_MANIFEST_INVALID",
        ):
            importer.import_release(source, site_root=self.site)

        self.assertFalse(
            (self.site / "assets/validated-releases/nerivane-v2").exists()
        )

    def test_rejects_every_status_other_than_the_exact_sealed_state(self) -> None:
        for status in (
            "BLOCKED_CANDIDATE_AI_NOT_EXECUTED",
            "FAILED",
            "SEALED_PUBLIC_REPLAY_V2",
            "",
        ):
            with self.subTest(status=status):
                source = build_source(self.sources, replay_status=status)

                with self.assertRaisesRegex(
                    importer.NerivaneReleaseImportError,
                    "NERIVANE_V2_REPLAY_INVALID",
                ):
                    importer.import_release(source, site_root=self.site)

    def test_rejects_every_replay_contract_other_than_exact_v2(self) -> None:
        for contract_id in (
            "NERIVANE-PUBLIC-REPLAY-V1",
            "NERIVANE-PUBLIC-REPLAY-V2-EXTRA",
            "",
        ):
            with self.subTest(contract_id=contract_id):
                source = build_source(
                    self.sources,
                    replay_contract_id=contract_id,
                )

                with self.assertRaisesRegex(
                    importer.NerivaneReleaseImportError,
                    "NERIVANE_V2_REPLAY_INVALID",
                ):
                    importer.import_release(source, site_root=self.site)

    def test_rejects_any_promotion_contract_other_than_the_versioned_exact_mapping(self) -> None:
        altered = json.loads(importer.PROMOTION_CONTRACT_PATH.read_bytes())
        altered["contract_id"] = "DATAPREDICT-NERIVANE-ACTIVE-SITE-PROMOTION-V2"
        source = build_source(
            self.sources,
            promotion_contract_payload=canonical(altered),
        )

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_PROMOTION_CONTRACT_INVALID",
        ):
            importer.import_release(source, site_root=self.site)

    def test_rejects_private_tokens_in_public_text(self) -> None:
        source = build_source(self.sources, private_token=" /home/jo/private ")

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_PUBLIC_TEXT_NOT_SANITIZED",
        ):
            importer.import_release(source, site_root=self.site)

    def test_rejects_unmanifested_file(self) -> None:
        source = build_source(self.sources)
        source.chmod(0o700)
        extra = source / "stray.txt"
        extra.write_text("stray", encoding="utf-8")
        extra.chmod(0o400)

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_INVENTORY_DIVERGED",
        ):
            importer.import_release(source, site_root=self.site)

    def test_rejects_checksum_divergence(self) -> None:
        source = build_source(self.sources)
        checksum = source / "SHA256SUMS"
        checksum.chmod(0o600)
        payload = checksum.read_text(encoding="ascii").replace("a", "b", 1)
        checksum.write_text(payload, encoding="ascii")
        checksum.chmod(0o400)

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_FILE_DIVERGED",
        ):
            importer.import_release(source, site_root=self.site)

    def test_failure_before_ready_leaves_no_partial_release(self) -> None:
        source = build_source(self.sources)
        original = importer._write_exclusive
        calls = 0

        def fail_after_first(path: Path, payload: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected write failure")
            original(path, payload)

        with patch.object(importer, "_write_exclusive", side_effect=fail_after_first):
            with self.assertRaisesRegex(
                importer.NerivaneReleaseImportError,
                "NERIVANE_V2_DESTINATION_CREATE_FAILED",
            ):
                importer.import_release(source, site_root=self.site)

        destination = self.site / "assets/validated-releases/nerivane-v2" / source.name
        self.assertFalse(destination.exists())

    def test_failure_while_writing_ready_leaves_no_partial_release(self) -> None:
        source = build_source(self.sources)
        original = importer._write_exclusive

        def fail_during_ready(path: Path, payload: bytes) -> None:
            if path.name == importer.READY_PATH:
                original(path, b"")
                raise OSError("injected ready write failure")
            original(path, payload)

        with patch.object(
            importer,
            "_write_exclusive",
            side_effect=fail_during_ready,
        ):
            with self.assertRaisesRegex(
                importer.NerivaneReleaseImportError,
                "NERIVANE_V2_DESTINATION_CREATE_FAILED",
            ):
                importer.import_release(source, site_root=self.site)

        destination = self.site / "assets/validated-releases/nerivane-v2" / source.name
        self.assertFalse(destination.exists())
        self.assertEqual(
            importer.import_release(source, site_root=self.site)["status"],
            "CREATED",
        )

    def test_sigkill_before_directory_publish_does_not_poison_destination(self) -> None:
        source = build_source(self.sources)
        context = multiprocessing.get_context("fork")
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=block_before_directory_publish,
            args=(str(source), str(self.site), child_connection),
        )
        try:
            process.start()
            child_connection.close()
            self.assertTrue(
                parent_connection.poll(10),
                "child importer did not reach atomic directory publication",
            )
            staged = parent_connection.recv()
            self.assertIn(source.name, staged["source"])
            self.assertTrue(staged["destination"].endswith(source.name))
            process.kill()
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, -signal.SIGKILL)
        finally:
            if process.is_alive():
                process.kill()
                process.join(10)
            parent_connection.close()
            child_connection.close()

        destination = self.site / "assets/validated-releases/nerivane-v2" / source.name
        self.assertFalse(destination.exists())
        pending_containers = list(
            (self.site / "assets/validated-releases").glob(
                f".nerivane-v2-{source.name}.pending.*"
            )
        )
        self.assertEqual(len(pending_containers), 1)
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (),
        )
        result = importer.import_release(source, site_root=self.site)
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (source.name,),
        )

    def test_failure_reported_after_directory_publish_preserves_valid_release(self) -> None:
        source = build_source(self.sources)
        original = importer._rename_noreplace

        def publish_then_fail(source_path: Path, destination_path: Path) -> None:
            original(source_path, destination_path)
            raise OSError("injected post-publication failure")

        with patch.object(
            importer,
            "_rename_noreplace",
            side_effect=publish_then_fail,
        ):
            with self.assertRaisesRegex(
                importer.NerivaneReleaseImportError,
                "NERIVANE_V2_DESTINATION_CREATE_FAILED",
            ):
                importer.import_release(source, site_root=self.site)

        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (source.name,),
        )
        self.assertEqual(
            importer.import_release(source, site_root=self.site)["status"],
            "ALREADY_PRESENT",
        )

    def test_import_is_verifiable_under_a_restrictive_umask(self) -> None:
        source = build_source(self.sources)
        previous_umask = os.umask(0o077)
        try:
            result = importer.import_release(source, site_root=self.site)
        finally:
            os.umask(previous_umask)

        collection = self.site / "assets/validated-releases/nerivane-v2"
        self.assertEqual(
            stat.S_IMODE(collection.parent.stat().st_mode),
            0o755,
        )
        self.assertEqual(stat.S_IMODE(collection.stat().st_mode), 0o755)
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (result["release_id"],),
        )

    def test_rejects_a_divergent_existing_destination(self) -> None:
        source = build_source(self.sources)
        result = importer.import_release(source, site_root=self.site)
        destination = (
            self.site
            / "assets/validated-releases/nerivane-v2"
            / result["release_id"]
        )
        target = destination / "steps/03.html"
        target.write_bytes(b"divergent")

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_DESTINATION_DIVERGED",
        ):
            importer.import_release(source, site_root=self.site)


if __name__ == "__main__":
    unittest.main()
