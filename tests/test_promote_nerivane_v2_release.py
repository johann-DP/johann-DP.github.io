from __future__ import annotations

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
import promote_nerivane_v2_release as promoter  # noqa: E402
from tests.test_import_nerivane_v2_release import build_site, build_source  # noqa: E402


def block_before_commit(
    release_id: str,
    site: str,
    ready_connection: Connection,
) -> None:
    def pause(transaction: Path) -> None:
        ready_connection.send({"phase": "PREPARED", "transaction": str(transaction)})
        ready_connection.close()
        while True:
            signal.pause()

    with patch.object(promoter, "_before_commit", side_effect=pause):
        promoter.promote_release(release_id, site_root=Path(site))


def block_after_commit_target(
    release_id: str,
    site: str,
    crash_index: int,
    ready_connection: Connection,
) -> None:
    def pause(index: int, relative: str) -> None:
        if index != crash_index:
            return
        ready_connection.send({"index": index, "target": relative})
        ready_connection.close()
        while True:
            signal.pause()

    with patch.object(promoter, "_after_target_committed", side_effect=pause):
        promoter.promote_release(release_id, site_root=Path(site))


def block_during_rollback(
    release_id: str,
    site: str,
    crash_index: int,
    ready_connection: Connection,
) -> None:
    def pause(index: int, relative: str) -> None:
        if index != crash_index:
            return
        ready_connection.send({"index": index, "target": relative})
        ready_connection.close()
        while True:
            signal.pause()

    with patch.object(promoter, "_after_target_rolled_back", side_effect=pause):
        promoter.rollback_release(release_id, site_root=Path(site))


def block_before_atomic_publish(
    release_id: str,
    site: str,
    ready_connection: Connection,
) -> None:
    def pause(path: Path, temporary: Path) -> None:
        ready_connection.send(
            {"target": path.name, "temporary": temporary.as_posix()}
        )
        ready_connection.close()
        while True:
            signal.pause()

    with patch.object(promoter, "_before_atomic_publish", side_effect=pause):
        promoter.promote_release(release_id, site_root=Path(site))


def target_state(site: Path) -> dict[str, tuple[bytes, int]]:
    return {
        relative: (
            (site / relative).read_bytes(),
            stat.S_IMODE((site / relative).stat().st_mode),
        )
        for relative in promoter._commit_order()
    }


def target_temporaries(site: Path, release_id: str) -> list[Path]:
    observed: list[Path] = []
    for relative in promoter._commit_order():
        target = site / relative
        observed.extend(
            target.parent.glob(f".{target.name}.nerivane-v2-{release_id}.*")
        )
    return observed


def kill_at_ready(
    target: object,
    args: tuple[object, ...],
) -> dict[str, object]:
    context = multiprocessing.get_context("fork")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(*args, child_connection))
    try:
        process.start()
        child_connection.close()
        if not parent_connection.poll(10):
            raise AssertionError("child did not reach the injected crash boundary")
        observed = parent_connection.recv()
        process.kill()
        process.join(10)
        if process.is_alive():
            raise AssertionError("child remained alive after SIGKILL")
        if process.exitcode != -signal.SIGKILL:
            raise AssertionError(f"unexpected child exit code: {process.exitcode}")
        return observed
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)
        parent_connection.close()
        child_connection.close()


class NerivaneV2PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.site = self.root / "site"
        self.site.mkdir()
        build_site(self.site)
        source = build_source(self.sources)
        self.release_id = importer.import_release(source, site_root=self.site)[
            "release_id"
        ]
        self.targets_before = target_state(self.site)
        self.protected_before = promoter._protected_snapshot(self.site)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_baseline_exact(self) -> None:
        self.assertEqual(target_state(self.site), self.targets_before)
        self.assertEqual(
            promoter._protected_snapshot(self.site),
            self.protected_before,
        )
        self.assertEqual(
            promoter.attest_maintenance(site_root=self.site)["state"],
            "MAINTENANCE",
        )

    def test_fixture_attestation_before_and_after_promotion(self) -> None:
        before = promoter.attest_maintenance(site_root=self.site)

        result = promoter.promote_release(self.release_id, site_root=self.site)
        after = promoter.attest_release(self.release_id, site_root=self.site)

        self.assertEqual(before["state"], "MAINTENANCE")
        self.assertEqual(result["status"], "PROMOTED")
        self.assertEqual(after["state"], "ACTIVE")
        self.assertEqual(after["target_count"], 5)
        page = (self.site / "demonstrations/nerivane-distribution.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("maintenance", page.lower())
        self.assertIn(self.release_id, page)
        catalogue = (
            self.site / "demonstrations.html"
        ).read_text(encoding="utf-8")
        self.assertFalse(any(
            line.rstrip() != line
            for line in catalogue.splitlines()
        ))
        self.assertEqual(
            promoter._protected_snapshot(self.site),
            self.protected_before,
        )

    def test_promotion_is_idempotent_for_the_same_release(self) -> None:
        promoter.promote_release(self.release_id, site_root=self.site)
        active = target_state(self.site)

        second = promoter.promote_release(self.release_id, site_root=self.site)

        self.assertEqual(second["status"], "ALREADY_ACTIVE")
        self.assertEqual(target_state(self.site), active)
        self.assertEqual(
            promoter._protected_snapshot(self.site),
            self.protected_before,
        )

    def test_explicit_rollback_restores_every_target_byte_and_mode(self) -> None:
        promoter.promote_release(self.release_id, site_root=self.site)

        result = promoter.rollback_release(self.release_id, site_root=self.site)

        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assert_baseline_exact()
        self.assertFalse(
            promoter._transaction_path(self.site, self.release_id).exists()
        )

    def test_rejects_wrong_or_unimported_release_id_without_active_changes(self) -> None:
        for release_id, code in (
            ("not-a-release", "NERIVANE_V2_PROMOTION_RELEASE_ID_INVALID"),
            ("b" * 64, "NERIVANE_V2_PROMOTION_RELEASE_INVALID"),
        ):
            with self.subTest(release_id=release_id):
                with self.assertRaisesRegex(promoter.NerivanePromotionError, code):
                    promoter.promote_release(release_id, site_root=self.site)
                self.assert_baseline_exact()

    def test_revalidates_imported_manifest_and_sha_before_promotion(self) -> None:
        release = (
            self.site
            / "assets/validated-releases/nerivane-v2"
            / self.release_id
        )
        target = release / "steps/03.html"
        target.write_bytes(b"tampered after inactive import")

        with self.assertRaisesRegex(
            promoter.NerivanePromotionError,
            "NERIVANE_V2_PROMOTION_RELEASE_INVALID",
        ):
            promoter.promote_release(self.release_id, site_root=self.site)

        self.assert_baseline_exact()

    def test_sigkill_between_durable_preparation_and_commit_is_discarded(self) -> None:
        observed = kill_at_ready(
            block_before_commit,
            (self.release_id, str(self.site)),
        )

        self.assertEqual(observed["phase"], "PREPARED")
        self.assert_baseline_exact()
        recovery = promoter.recover_promotion(
            self.release_id,
            site_root=self.site,
        )
        self.assertEqual(recovery["status"], "PREPARED_DISCARDED")
        self.assert_baseline_exact()

    def test_sigkill_after_each_commit_step_recovers_exact_baseline(self) -> None:
        for crash_index, expected_target in enumerate(promoter._commit_order()):
            with self.subTest(crash_index=crash_index, target=expected_target):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    sources = root / "sources"
                    sources.mkdir()
                    site = root / "site"
                    site.mkdir()
                    build_site(site)
                    source = build_source(sources)
                    release_id = importer.import_release(source, site_root=site)[
                        "release_id"
                    ]
                    before = target_state(site)
                    protected = promoter._protected_snapshot(site)

                    observed = kill_at_ready(
                        block_after_commit_target,
                        (release_id, str(site), crash_index),
                    )

                    self.assertEqual(observed["index"], crash_index)
                    self.assertEqual(observed["target"], expected_target)
                    journal = promoter._read_journal(
                        promoter._transaction_path(site, release_id),
                        release_id,
                    )
                    self.assertEqual(journal["phase"], promoter.PHASE_COMMITTING)
                    recovery = promoter.recover_promotion(
                        release_id,
                        site_root=site,
                    )
                    self.assertEqual(recovery["status"], "ROLLED_BACK")
                    self.assertEqual(target_state(site), before)
                    self.assertEqual(promoter._protected_snapshot(site), protected)
                    self.assertEqual(
                        promoter.attest_maintenance(site_root=site)["state"],
                        "MAINTENANCE",
                    )
                    self.assertEqual(target_temporaries(site, release_id), [])

    def test_sigkill_before_atomic_file_publish_cleans_durable_temporary(self) -> None:
        observed = kill_at_ready(
            block_before_atomic_publish,
            (self.release_id, str(self.site)),
        )

        temporary = Path(str(observed["temporary"]))
        self.assertTrue(temporary.is_file())
        self.assertEqual(len(target_temporaries(self.site, self.release_id)), 1)
        recovery = promoter.recover_promotion(
            self.release_id,
            site_root=self.site,
        )
        self.assertEqual(recovery["status"], "ROLLED_BACK")
        self.assertEqual(target_temporaries(self.site, self.release_id), [])
        self.assert_baseline_exact()

    def test_concurrent_promotion_fails_closed_while_transaction_lock_is_held(self) -> None:
        context = multiprocessing.get_context("fork")
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=block_before_commit,
            args=(self.release_id, str(self.site), child_connection),
        )
        try:
            process.start()
            child_connection.close()
            self.assertTrue(parent_connection.poll(10))
            parent_connection.recv()
            with self.assertRaisesRegex(
                promoter.NerivanePromotionError,
                "NERIVANE_V2_PROMOTION_BUSY",
            ):
                promoter.promote_release(self.release_id, site_root=self.site)
        finally:
            if process.is_alive():
                process.kill()
                process.join(10)
            parent_connection.close()
            child_connection.close()

        self.assertEqual(
            promoter.recover_promotion(
                self.release_id,
                site_root=self.site,
            )["status"],
            "PREPARED_DISCARDED",
        )
        self.assert_baseline_exact()

    def test_sigkill_during_rollback_is_recovered_idempotently(self) -> None:
        promoter.promote_release(self.release_id, site_root=self.site)

        observed = kill_at_ready(
            block_during_rollback,
            (self.release_id, str(self.site), 2),
        )

        self.assertEqual(observed["index"], 2)
        journal = promoter._read_journal(
            promoter._transaction_path(self.site, self.release_id),
            self.release_id,
        )
        self.assertEqual(journal["phase"], promoter.PHASE_ROLLING_BACK)
        recovery = promoter.recover_promotion(
            self.release_id,
            site_root=self.site,
        )
        self.assertEqual(recovery["status"], "ROLLED_BACK")
        self.assert_baseline_exact()

    def test_contract_never_maps_protected_v1_fissures_or_demo2_paths(self) -> None:
        targets = {entry["target"] for entry in promoter._mappings()}
        protected = set(promoter._protected_paths())

        self.assertEqual(
            targets,
            {
                "assets/css/demo-nerivane.css",
                "assets/data/nerivane-governance-replay.json",
                "assets/js/demo-nerivane.js",
                "demonstrations.html",
                "demonstrations/nerivane-distribution.html",
            },
        )
        self.assertIn("assets/nerivane-public-v1", protected)
        self.assertIn("demonstrations/fissures.html", protected)
        self.assertIn("assets/figures/demo-2", protected)
        promoter.promote_release(self.release_id, site_root=self.site)
        self.assertEqual(promoter._protected_snapshot(self.site), self.protected_before)


if __name__ == "__main__":
    unittest.main()
