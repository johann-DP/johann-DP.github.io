from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_nerivane_v2_release as importer  # noqa: E402


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
    private_token: str | None = None,
) -> dict[str, tuple[str, bytes]]:
    payloads: dict[str, tuple[str, bytes]] = {
        "index.html": (
            "public_html",
            b"<!doctype html><html lang='fr'><title>Nerivane V2</title></html>",
        ),
        "replay-manifest.json": (
            "public_json",
            canonical(
                {
                    "contract_id": "NERIVANE-PUBLIC-REPLAY-V2",
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
    private_token: str | None = None,
    gates: dict[str, str] | None = None,
) -> Path:
    payloads = source_payloads(
        replay_status=replay_status,
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
        "demonstrations/nerivane-distribution.html": b"maintenance page",
        "assets/data/nerivane-governance-replay.json": b"maintenance data",
        "assets/js/demo-nerivane.js": b"maintenance js",
        "assets/css/demo-nerivane.css": b"maintenance css",
        "demonstrations.html": b"maintenance catalogue",
        "assets/nerivane-public-v1/SHA256SUMS": b"legacy sums",
        "assets/nerivane-public-v1/index.html": b"legacy replay",
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
        self.assertEqual(result["published_file_count"], 11)
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

    def test_rejects_candidate_or_blocked_replay(self) -> None:
        source = build_source(
            self.sources,
            replay_status="BLOCKED_CANDIDATE_AI_NOT_EXECUTED",
        )

        with self.assertRaisesRegex(
            importer.NerivaneReleaseImportError,
            "NERIVANE_V2_REPLAY_INVALID",
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
