from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_demo2_validated_release as importer  # noqa: E402


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
    ).encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def record(path: str, role: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "role": role,
        "sha256": digest(payload),
        "size_bytes": len(payload),
    }


def write_private_tree(root: Path, payloads: dict[str, bytes], manifest: bytes) -> None:
    root.mkdir(mode=0o700)
    all_payloads = {
        **payloads,
        importer.CONTENT_MANIFEST_PATH: manifest,
        importer.READY_PATH: importer.READY_CONTENT,
    }
    for relative, payload in sorted(all_payloads.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(payload)
    for path in sorted(
        (entry for entry in root.rglob("*") if entry.is_dir()),
        key=lambda entry: len(entry.parts),
        reverse=True,
    ):
        path.chmod(0o500)
    for path in (entry for entry in root.rglob("*") if entry.is_file()):
        path.chmod(0o444 if path.name == importer.READY_PATH else 0o400)
    root.chmod(0o700)


def build_source_bundle(
    parent: Path,
    *,
    release_kind: str = "manual_measurement_review",
    logical_id: str = "crack-recent",
    release_path: str = "recent-cracks-raw.html",
    validation: dict[str, object] | None = None,
    extra_payloads: dict[str, tuple[str, bytes]] | None = None,
    runtime_payload: bytes = b"plotly-runtime",
    approved_at_utc: str = "2026-08-29T12:34:56Z",
    figure_payload: bytes | None = None,
) -> Path:
    figure = figure_payload or (
        b"<!doctype html><html lang='fr'><title>candidate</title></html>"
    )
    if release_kind == "weather_complement_review":
        dependencies = {
            importer.WEATHER_PLOTLY: runtime_payload,
            importer.WEATHER_PLOTLY_LICENSE: b"plotly-license",
        }
    else:
        dependencies = {
            importer.PLOTLY: runtime_payload,
            importer.PLOTLY_LICENSE: b"plotly-license",
        }

    source_release_id = digest(b"source-release")
    source_manifest_sha256 = digest(b"private-source-content-manifest")
    source_gate_sha256 = digest(b"private-review-gate")
    approval = {
        "schema_version": 1,
        "approval_id": "D2-VALIDATION-1",
        "decision": "VALIDÉ",
        "validation_scope": "GRAPHICAL_PUBLICATION_ONLY",
        "scientific_interpretation": "NOT_CLAIMED",
        "approved_by": "Demo 2 owner",
        "approved_at_utc": approved_at_utc,
        "source": {
            "release_kind": release_kind,
            "release_id": source_release_id,
            "content_manifest_sha256": source_manifest_sha256,
            "review_gate_sha256": source_gate_sha256,
        },
        "selected_figures": [
            {
                "logical_figure_id": logical_id,
                "release_path": release_path,
                "sha256": digest(figure),
                "size_bytes": len(figure),
            }
        ],
        "publication": {
            "preserve_current_validated_masters": True,
            "automatic_site_publication_permitted": False,
            "expected_current_manifest_sha256": digest(b"current-manifest"),
        },
    }
    approval_payload = canonical(approval)
    source_approval_sha256 = digest(b"source-approval-record.yaml")
    attestation_payload = canonical(
        {
            "approval_id": approval["approval_id"],
            "approval_sha256": source_approval_sha256,
            "candidate_status_before_approval": "EXÉCUTÉ_NON_VALIDÉ",
            "content_manifest_sha256": source_manifest_sha256,
            "release_id": source_release_id,
            "release_kind": release_kind,
            "review_gate_sha256": source_gate_sha256,
            "scientific_interpretation": "NOT_CLAIMED",
            "validation_scope": "GRAPHICAL_PUBLICATION_ONLY",
        }
    )
    published = {release_path: figure, **dependencies}
    identity_files = [
        record(
            path,
            "approved_figure" if path == release_path else "runtime_dependency",
            payload,
        )
        for path, payload in sorted(published.items())
    ]
    identity = {
        "approval_sha256": source_approval_sha256,
        "canonical_approval_sha256": digest(approval_payload),
        "files": identity_files,
        "protocol_version": 2,
        "source_content_manifest_sha256": source_manifest_sha256,
        "source_release_id": source_release_id,
    }
    promotion_id = digest(canonical(identity))
    payloads = {
        **published,
        importer.APPROVAL_PATH: approval_payload,
        importer.ATTESTATION_PATH: attestation_payload,
    }
    roles = {
        **{
            path: "approved_figure" if path == release_path else "runtime_dependency"
            for path in published
        },
        importer.APPROVAL_PATH: "human_validation_approval",
        importer.ATTESTATION_PATH: "source_release_attestation",
    }
    if extra_payloads:
        for path, (role, payload) in extra_payloads.items():
            payloads[path] = payload
            roles[path] = role
    manifest = canonical(
        {
            "files": [
                record(path, roles[path], payloads[path]) for path in sorted(payloads)
            ],
            "manifest_version": 1,
            "promotion_id": promotion_id,
            "source": identity,
            "validation": validation or dict(importer.VALIDATION),
        }
    )
    root = parent / promotion_id
    write_private_tree(root, payloads, manifest)
    return root


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def use_git_checkout_modes(root: Path) -> None:
    for path in sorted(
        (entry for entry in root.rglob("*") if entry.is_dir()),
        key=lambda entry: len(entry.parts),
        reverse=True,
    ):
        path.chmod(0o755)
    for path in (entry for entry in root.rglob("*") if entry.is_file()):
        path.chmod(0o644)
    root.chmod(0o755)


class SiteReleaseImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir(mode=0o700)
        self.site = self.root / "site"
        self.site.mkdir()
        protected = {
            "assets/figures/demo-2/current.html": b"validated-current-figure",
            "assets/js/demo-fissures.js": b"active references",
            "demonstrations/fissures.html": b"active page",
        }
        for relative, payload in protected.items():
            path = self.site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.protected_before = tree_hashes(self.site)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_imports_exact_public_inventory_without_changing_active_files(self) -> None:
        source = build_source_bundle(self.sources)

        result = importer.import_validated_release(source, site_root=self.site)

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["state"], "IMPORTED_INACTIVE")
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (result["promotion_id"],),
        )
        destination = (
            self.site / "assets/validated-releases/demo-2" / result["promotion_id"]
        )
        observed = {
            path.relative_to(destination).as_posix() for path in destination.rglob("*")
        }
        self.assertEqual(
            observed,
            {
                ".READY",
                "content-manifest.json",
                "recent-cracks-raw.html",
                "source-release-attestation.json",
                "validation-approval.json",
                "weather",
                "weather/assets",
                "weather/assets/plotly-2.35.2.min.js",
                "weather/assets/plotly-2.35.2.min.js.LICENSE.txt",
            },
        )
        self.assertFalse(importer.FORBIDDEN_METADATA & observed)
        for path in destination.rglob("*"):
            expected_mode = 0o755 if path.is_dir() else 0o644
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected_mode)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)
        self.assertEqual(
            {
                key: value
                for key, value in tree_hashes(self.site).items()
                if key in self.protected_before
            },
            self.protected_before,
        )

    def test_identical_reimport_is_idempotent(self) -> None:
        source = build_source_bundle(self.sources)
        first = importer.import_validated_release(source, site_root=self.site)

        second = importer.import_validated_release(source, site_root=self.site)

        self.assertEqual(first["promotion_id"], second["promotion_id"])
        self.assertEqual(second["status"], "ALREADY_PRESENT")

    def test_accepts_complete_git_checkout_mode_profile(self) -> None:
        source = build_source_bundle(self.sources)
        use_git_checkout_modes(source)

        result = importer.import_validated_release(source, site_root=self.site)

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(
            importer.verify_imported_releases(site_root=self.site),
            (result["promotion_id"],),
        )

    def test_rejects_mixed_atomic_and_git_checkout_modes(self) -> None:
        source = build_source_bundle(self.sources)
        source.chmod(0o755)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_TREE_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_existing_divergent_destination_is_rejected_without_overwrite(self) -> None:
        source = build_source_bundle(self.sources)
        result = importer.import_validated_release(source, site_root=self.site)
        destination = (
            self.site / "assets/validated-releases/demo-2" / result["promotion_id"]
        )
        target = destination / "recent-cracks-raw.html"
        target.write_bytes(b"divergent-existing-content")
        divergent = target.read_bytes()

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_DESTINATION_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

        self.assertEqual(target.read_bytes(), divergent)

    def test_rejects_extra_private_metadata_even_when_manifested(self) -> None:
        source = build_source_bundle(
            self.sources,
            extra_payloads={
                importer.SOURCE_GATE_PATH: ("source_review_gate", b"private gate")
            },
        )

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_INVENTORY_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_unmanifested_extra_file(self) -> None:
        source = build_source_bundle(self.sources)
        extra = source / "unexpected.txt"
        extra.write_bytes(b"unexpected")
        extra.chmod(0o400)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_INVENTORY_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_file_hash_divergence(self) -> None:
        source = build_source_bundle(self.sources)
        target = source / "recent-cracks-raw.html"
        target.chmod(0o600)
        target.write_bytes(b"changed")
        target.chmod(0o400)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_FILE_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_rewritten_canonical_approval_even_when_remanifested(self) -> None:
        source = build_source_bundle(self.sources)
        approval_path = source / importer.APPROVAL_PATH
        manifest_path = source / importer.CONTENT_MANIFEST_PATH

        approval = json.loads(approval_path.read_bytes())
        approval["approved_by"] = "Rewritten owner"
        rewritten = canonical(approval)
        approval_path.chmod(0o600)
        approval_path.write_bytes(rewritten)
        approval_path.chmod(0o400)

        manifest = json.loads(manifest_path.read_bytes())
        for item in manifest["files"]:
            if item["path"] == importer.APPROVAL_PATH:
                item["sha256"] = digest(rewritten)
                item["size_bytes"] = len(rewritten)
        manifest_path.chmod(0o600)
        manifest_path.write_bytes(canonical(manifest))
        manifest_path.chmod(0o400)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_IDENTITY_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_empty_runtime_even_when_hash_and_size_match(self) -> None:
        source = build_source_bundle(self.sources, runtime_payload=b"")

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_INVENTORY_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_wrong_source_mode(self) -> None:
        source = build_source_bundle(self.sources)
        (source / "recent-cracks-raw.html").chmod(0o444)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_TREE_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_symlink_in_destination_ancestry(self) -> None:
        source = build_source_bundle(self.sources)
        outside = self.root / "outside-destination"
        outside.mkdir()
        (self.site / "assets/validated-releases").symlink_to(outside)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_DESTINATION_ROOT_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_symlink_and_hardlink_sources(self) -> None:
        source = build_source_bundle(self.sources)
        figure = source / "recent-cracks-raw.html"
        figure.unlink()
        figure.symlink_to(self.site / "assets/js/demo-fissures.js")
        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_TREE_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

        hardlink_parent = self.root / "hardlink-sources"
        hardlink_parent.mkdir(mode=0o700)
        source = build_source_bundle(hardlink_parent)
        os.link(source / "recent-cracks-raw.html", self.root / "outside-hardlink")
        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_TREE_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_wrong_promotion_id_and_unapproved_logical_id(self) -> None:
        source = build_source_bundle(self.sources)
        wrong_name = source.parent / ("f" * 64)
        source.rename(wrong_name)
        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_MANIFEST_INVALID|SITE_RELEASE_IDENTITY_INVALID",
        ):
            importer.import_validated_release(wrong_name, site_root=self.site)

        invalid_parent = self.root / "invalid-source"
        invalid_parent.mkdir(mode=0o700)
        invalid = build_source_bundle(invalid_parent, logical_id="not-approved")
        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_APPROVAL_INVALID",
        ):
            importer.import_validated_release(invalid, site_root=self.site)

    def test_rejects_validation_that_permits_automatic_publication(self) -> None:
        invalid_validation = dict(importer.VALIDATION)
        invalid_validation["automatic_site_publication_permitted"] = True
        source = build_source_bundle(self.sources, validation=invalid_validation)

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_MANIFEST_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_impossible_approval_date(self) -> None:
        source = build_source_bundle(
            self.sources,
            approved_at_utc="2026-02-30T12:34:56Z",
        )

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_APPROVAL_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_html_with_private_or_network_reference(self) -> None:
        source = build_source_bundle(
            self.sources,
            figure_payload=(
                b"<!doctype html><html lang='fr'><title>x</title>"
                b"<script src='https://example.test/x.js'></script></html>"
            ),
        )

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_HTML_INVALID",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_rejects_missing_ready_marker(self) -> None:
        source = build_source_bundle(self.sources)
        (source / importer.READY_PATH).unlink()

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_INVENTORY_DIVERGED",
        ):
            importer.import_validated_release(source, site_root=self.site)

    def test_verify_existing_rejects_a_stray_collection_entry(self) -> None:
        source = build_source_bundle(self.sources)
        importer.import_validated_release(source, site_root=self.site)
        stray = self.site / "assets/validated-releases/demo-2/not-a-release"
        stray.write_text("stray", encoding="utf-8")

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_PUBLIC_COLLECTION_INVALID",
        ):
            importer.verify_imported_releases(site_root=self.site)

    def test_verify_existing_rejects_symlink_inside_public_bundle(self) -> None:
        source = build_source_bundle(self.sources)
        result = importer.import_validated_release(source, site_root=self.site)
        destination = (
            self.site / "assets/validated-releases/demo-2" / result["promotion_id"]
        )
        target = destination / "recent-cracks-raw.html"
        target.unlink()
        target.symlink_to(self.site / "assets/js/demo-fissures.js")

        with self.assertRaisesRegex(
            importer.SiteReleaseImportError,
            "SITE_RELEASE_TREE_INVALID",
        ):
            importer.verify_imported_releases(site_root=self.site)

    def test_failure_before_ready_removes_only_new_incomplete_destination(self) -> None:
        destination = self.site / "new-release"
        payloads = {"figure.html": b"figure", "asset.js": b"asset"}
        original = importer._write_exclusive
        calls = 0

        def fail_second(path: Path, payload: bytes, mode: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected pre-ready failure")
            original(path, payload, mode)

        with patch.object(importer, "_write_exclusive", side_effect=fail_second):
            with self.assertRaisesRegex(
                importer.SiteReleaseImportError,
                "SITE_RELEASE_DESTINATION_CREATE_FAILED",
            ):
                importer._create_destination(destination, b"manifest", payloads)

        self.assertFalse(destination.exists())

    def test_failure_after_ready_preserves_visible_destination(self) -> None:
        destination = self.site / "post-ready-release"
        payloads = {"figure.html": b"figure"}
        original = importer._fsync_directory

        def fail_parent_sync(path: Path) -> None:
            if (
                path == destination.parent
                and (destination / importer.READY_PATH).exists()
            ):
                raise OSError("injected post-ready failure")
            original(path)

        with patch.object(importer, "_fsync_directory", side_effect=fail_parent_sync):
            with self.assertRaisesRegex(
                importer.SiteReleaseImportError,
                "SITE_RELEASE_DESTINATION_CREATE_FAILED",
            ):
                importer._create_destination(destination, b"manifest", payloads)

        self.assertTrue(destination.is_dir())
        self.assertEqual(
            (destination / importer.READY_PATH).read_bytes(),
            importer.READY_CONTENT,
        )

    def test_failure_reported_by_ready_rename_after_visibility_preserves_output(
        self,
    ) -> None:
        destination = self.site / "rename-visible-release"
        payloads = {"figure.html": b"figure"}
        original = importer._rename_noreplace

        def rename_then_fail(source: Path, target: Path) -> None:
            original(source, target)
            raise OSError("injected failure after READY rename")

        with patch.object(importer, "_rename_noreplace", side_effect=rename_then_fail):
            with self.assertRaisesRegex(
                importer.SiteReleaseImportError,
                "SITE_RELEASE_DESTINATION_CREATE_FAILED",
            ):
                importer._create_destination(destination, b"manifest", payloads)

        self.assertTrue(destination.is_dir())
        self.assertEqual(
            (destination / importer.READY_PATH).read_bytes(),
            importer.READY_CONTENT,
        )
        self.assertFalse((destination / importer.READY_PENDING_PATH).exists())


if __name__ == "__main__":
    unittest.main()
