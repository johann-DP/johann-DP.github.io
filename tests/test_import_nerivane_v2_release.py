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


def h1_evidence() -> dict[str, object]:
    node_rows = (501_091_050, 501_091_049, 501_091_048, 501_091_047)
    layers = {
        "RAW": ("RAW_PRIMARY", "HDD"),
        "BRONZE": ("BRONZE_PRIMARY", "NVME"),
        "SILVER": ("SILVER_PRIMARY", "NVME"),
    }
    return {
        "schema_version": 1,
        "contract_id": "NERIVANE-FULL-H1-FINAL-PUBLIC-EVIDENCE-V1",
        "status": "PASS_FULL_H1_1320_DURABLE_TRIPLETS",
        "proof_scope": "ANCHORED_FINAL_PROOF_1320_RECEIPTS_AND_THREE_ATTESTED_DATA_TIERS",
        "period": {"start_month": "2021-01", "end_month": "2021-06", "month_count": 6},
        "source_bindings": {
            "full_h1_proof_sha256": "1" * 64,
            "receipt_anchor_set_sha256": "2" * 64,
            "deployed_runtime_sha256": "3" * 64,
            "storage_topology_contract_sha256": "4" * 64,
        },
        "execution": {
            "node_count": 4, "triplet_count": 1_320, "task_count": 3_960,
            "rows_per_layer": 668_121_398, "physical_rows": 2_004_364_194,
            "file_count": 3_960,
            "by_node": {
                f"node-{letter}": {
                    "triplet_count": 330, "task_count": 990, "rows": rows,
                    "encoded_bytes": 450_000_000_000,
                    "allocated_bytes": 457_500_000_000, "file_count": 990,
                }
                for letter, rows in zip("abcd", node_rows, strict=True)
            },
        },
        "durable_storage": {
            "data_tier_count": 3,
            "distinct_physical_devices_attested": 3,
            "layers": {
                layer: {
                    "storage_role": role, "media_class": media,
                    "rows": 668_121_398, "encoded_bytes": 600_000_000_000,
                    "allocated_bytes": 610_000_000_000, "file_count": 1_320,
                }
                for layer, (role, media) in layers.items()
            },
            "total": {
                "rows": 2_004_364_194, "encoded_bytes": 1_800_000_000_000,
                "allocated_bytes": 1_830_000_000_000, "file_count": 3_960,
            },
        },
        "thresholds": {
            "decimal_1_5_tb_bytes": 1_500_000_000_000,
            "binary_1_5_tib_bytes": 3 * (1024**4) // 2,
            "encoded_exceeds_decimal_1_5_tb": True,
            "encoded_exceeds_binary_1_5_tib": True,
            "allocated_exceeds_decimal_1_5_tb": True,
            "allocated_exceeds_binary_1_5_tib": True,
        },
        "safety": {
            "source_deleted_or_modified": False, "automatic_deletion": False,
            "gcp_accessed_or_modified": False, "kpi_claimed_or_certified": False,
            "gpu_used_by_h1_pipeline": False,
        },
        "limitations": [
            "NO_KPI_CERTIFICATION_CLAIM", "NO_GCP_V2_LOAD_CLAIM",
            "NO_ARCHIVE_REDUNDANCY_OR_RESTORE_CLAIM",
            "NO_PERFORMANCE_OR_CONCURRENCY_BENCHMARK_CLAIM",
        ],
        "sanitization": {
            "status": "PASS", "node_identity": "PSEUDONYMIZED",
            "removed_categories": [
                "FILESYSTEM_PATHS", "HOSTNAMES", "IP_ADDRESSES", "DEVICE_SERIALS",
                "FILESYSTEM_UUIDS", "USER_IDENTITIES", "RECEIPT_LEVEL_DETAILS",
            ],
        },
    }


def ai_evidence() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "NERIVANE-AI-PUBLIC-POST-RUN-OVERLAY-V17R3",
        "artifact_kind": "SANITIZED_POST_RUN_QUALIFICATION_OVERLAY",
        "status": "REJECTED_BY_QUALIFICATION",
        "fail_closed": True,
        "fictional_scenario": True,
        "contract": {
            "path": "contracts/ai_public_post_run_overlay_v17r3.schema.json",
            "sha256": "a16ab56e4ce98e3ead0475e70f75638a5fc76a96d673c9ca81ebbd07f7e0d83f",
        },
        "execution": {
            "candidate_capture": {
                "path": "candidate-veto-replay.json",
                "replay_kind": "SANITIZED_CAPTURE_NO_LIVE_INFERENCE",
                "sha256": "194f8967c8e56e0cfc8ca31b349c407ee0ca81bd728dd48ebca1063bade174ef",
            },
            "live_inference_in_public_replay": False,
            "policy_id": "NERIVANE-AI-LOCAL-EXECUTION-V17R3",
            "policy_sha256": "e031248cb06c01194b0f12872d04b666ce82a1239efb25cc7394f2f8f58b48a4",
            "surface": "LOCAL_BLACKWELL", "validated": True,
        },
        "candidate_veto": {
            "effective_finding_count": 1, "effective_verdict": "BLOCK",
            "findings": [{
                "applied_rule_ids": ["MAT6-SEVERITY-KPI-POPULATION-001"],
                "arbitration_question": "Quelle définition gouvernée doit être rendue opposable avant publication ?",
                "arbitration_question_template_id": "MAT6-QUESTION-KPI-DEFINITION",
                "claim": "Une incohérence de définition du KPI requiert un arbitrage gouverné.",
                "claim_template_id": "MAT6-CLAIM-KPI-DEFINITION",
                "effective_category": "KPI_DEFINITION", "effective_severity": "CRITICAL",
                "effective_verdict": "BLOCK",
                "evidence_ids": ["X-TFX9WKE4XMCWXQHMK10NJD4VEV", "X-937B9QNCR6CKR179WAD2CAQ02X"],
                "finding_id": "F-001", "materiality_basis": "CONFLICTING_KPI_POPULATION_OR_CUTOFF",
            }],
            "kpi_certification_performed": False, "kpi_computation_performed": False,
            "publication_status": "BLOCKED", "status": "EXECUTED_CANDIDATE_VETO",
        },
        "qualification": {
            "eligible": False,
            "evidence": {
                "path": "qualification-failure.json",
                "sha256": "9e1ec028f83109ff226021cf9ba70c185b1dede1818bc6236166a9b2b2bde4de",
            },
            "failure_codes": [
                "ANOMALY_RECALL_FAILURE", "CATEGORY_EXACT_FAILURE", "SEVERITY_EXACT_FAILURE",
                "VERDICT_EXACT_FAILURE", "CITATIONS_EXACT_FAILURE", "EXACT_CLASSIFICATION_FAILURE",
            ],
            "metrics": {
                "anomalies_expected": 12, "anomalies_recalled": 4,
                "cases_authenticated": 24, "cases_expected": 24,
                "exact_classification_cases": 16, "executions_authenticated": 120,
                "executions_expected": 120, "false_publication_vetoes_on_controls": 0,
                "raw_block_safety_violations": 0, "resolved_controls_clean": 12,
                "resolved_controls_expected": 12, "stable_cases": 24,
            },
            "report_id": "AI-EVAL-V17R3-4E253A6E62D5A6652B14",
            "route": "BLIND_HOLDOUT", "status": "REJECTED_BY_QUALIFICATION",
        },
        "model": {
            "deployment_status": "NOT_DEPLOYED",
            "qualification_status": "REJECTED_BY_QUALIFICATION",
            "repository_id": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
            "revision": "5a5a776300a41aaa681dd7ff0106608ef2bc90db",
        },
        "publication_decision": {
            "decision": "BLOCK_PUBLICATION",
            "external_evidence_sha256": "9e1ec028f83109ff226021cf9ba70c185b1dede1818bc6236166a9b2b2bde4de",
        },
        "publication_gate": {
            "human_authority": {
                "may_arbitrate_business_conflicts": True, "may_deploy_this_model": False,
                "may_mark_this_model_pass": False,
                "may_unblock_publication_while_this_model_is_selected": False,
                "must_compile_business_arbitration_as_deterministic_control": True,
            },
            "reason": "SELECTED_MODEL_REJECTED_BY_QUALIFICATION", "status": "BLOCKED",
        },
        "safety": {
            "candidate_capture_is_sanitized": True,
            "kpi_calculated_or_certified_by_ai": False,
            "private_case_identity_included": False, "private_paths_included": False,
            "private_truth_included": False, "raw_model_output_included": False,
        },
    }


def sample_evidence() -> dict[str, object]:
    return {
        "schema_version": 2,
        "contract_id": "NERIVANE-BIGQUERY-H1-SAMPLE-PUBLIC-EVIDENCE-V2",
        "status": "VALIDÉ_LOCAL_H1_SAMPLE_AND_36_CONTROLS",
        "fictional_scenario": True, "sample_id": "NERIVANE-2021-H1-GCP-V2",
        "period": {"start_month": "2021-01", "end_month": "2021-06", "month_count": 6},
        "source_bindings": {
            "full_h1_proof_sha256": "1" * 64,
            "receipt_anchor_set_sha256": "2" * 64,
            "selection_plan_sha256": "5" * 64,
            "materialization_proof_sha256": "6" * 64,
            "deterministic_controls_proof_sha256": "7" * 64,
        },
        "materialization": {
            "execution_surface": "LOCAL_ONLY_NO_GCP_ACCESS", "table_count": 17,
            "physical_rows": 210_724, "rows_are_non_round": True,
            "source_scope": "FULL_H1_RECEIPT_BOUND_LOCAL_MATERIALIZATION",
            "pilot_25m_inputs_used": False,
        },
        "deterministic_controls": {
            "executed": 36, "passed": 36, "failed": 0,
            "measurement_sha256": "8" * 64, "certified_months": 6,
            "values_are_integer_cents": True,
            "certification_status": "DETERMINISTICALLY_RECONCILED_PUBLICATION_BLOCKED_PENDING_AI_HUMAN",
        },
        "cloud_boundary": {
            "bigquery_project_mutated": False, "gcp_accessed_or_modified": False,
            "gcp_load_claimed": False,
            "meaning": "L'échantillon au schéma BigQuery a été matérialisé et contrôlé localement; ce paquet ne prétend ni chargement ni mutation GCP.",
        },
        "publication_boundary": {
            "kpi_deterministically_certified": True,
            "business_publication_automatically_unblocked": False,
        },
        "sanitization": {"status": "PASS", "private_paths_included": False},
    }


def resource_window_evidence() -> dict[str, bytes]:
    rows = (
        ("node-a", 330, 330, 0, 0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 118_004, 587_702, 1_788_193_068_061_594_182, 1_788_193_078_387_640_950, 10_326_046_768),
        ("node-b", 180, 180, 0, 0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 1_080, 504, 1_788_193_069_469_353_593, 1_788_193_079_591_911_157, 10_122_557_564),
        ("node-c", 92, 91, 1, 0, 0, 0, 0, 1, 1, 100, 1_011, 5, 1_652_461_568, 24_449_024, 174, 174, 1_788_193_067_485_996_867, 1_788_193_078_250_664_547, 10_764_667_680),
        ("node-d", 39, 38, 1, 0, 0, 0, 0, 1, 1, 100, 1_089, 2, 1_641_517_056, 13_967_360, 0, 0, 1_788_193_142_655_932_024, 1_788_193_152_672_081_689, 10_016_149_665),
    )
    payloads: dict[str, bytes] = {}
    reports = []
    for (
        node, engaged, completed, running, failed, abandoned, orphaned, unresolved,
        measured, running_end, ticks, app_ticks, system_ticks, peak_rss, writes,
        rx, tx, started, ended, duration,
    ) in rows:
        value = {
            "schema_version": 1, "contract_id": "NERIVANE-FULL-H1-PUBLIC-EVIDENCE-V1",
            "status": "PASS_OBSERVED_WINDOW", "observation_scope": "OBSERVED_WINDOW",
            "complete_campaign_observation": False, "full_campaign_claim_allowed": False,
            "node_ref": node,
            "window": {"started_unix_ns": started, "ended_unix_ns": ended, "duration_ns": duration, "sample_count": 2},
            "campaign_health": "HEALTHY_WITHIN_OBSERVED_WINDOW",
            "source_reported_error_count": 0,
            "jobs": {"engaged": engaged, "running": running, "completed": completed, "failed": failed, "abandoned": abandoned, "orphaned": orphaned, "unresolved": unresolved, "orphan_refs": []},
            "resources": {
                "process_scope": "MATCHED_H1_WORKER_PROCESSES",
                "processes_running_at_end": running_end,
                "processes_measured_across_window": measured,
                "cpu_clock_ticks_per_second": ticks,
                "cpu_application_ticks_delta": app_ticks,
                "cpu_system_ticks_delta": system_ticks,
                "peak_rss_bytes": peak_rss, "process_read_bytes_delta": 0,
                "process_write_bytes_delta": writes,
                "network_scope": "HOST_NON_LOOPBACK_AGGREGATE_NOT_PROCESS_ATTRIBUTED",
                "aggregate_rx_bytes_delta": rx, "aggregate_tx_bytes_delta": tx,
            },
            "gpu": {"h1_used": False, "status": "NOT_USED_BY_H1_PIPELINE"},
            "sanitization": {"status": "PASS", "node_identity": "PSEUDONYMIZED", "removed_categories": ["FILESYSTEM_PATHS", "HOSTNAMES", "IP_ADDRESSES", "PIDS", "DEVICE_SERIALS", "USER_IDENTITIES"]},
            "mutation_boundary": {"runtime_written": False, "data_written": False, "control_dir_written": False, "process_signalled": False, "network_accessed": False},
        }
        raw = canonical(value)
        path = f"evidence/resource-windows/{node}.json"
        payloads[path] = raw
        reports.append({"node_ref": node, "path": f"{node}.json", "sha256": digest(raw)})
    manifest = canonical({
        "schema_version": 1,
        "contract_id": "NERIVANE-FULL-H1-RESOURCE-WINDOWS-PUBLIC-PACKAGE-V1",
        "status": "PASS_OBSERVED_WINDOWS", "full_campaign_claim_allowed": False,
        "gpu": {"h1_used": False, "status": "NOT_USED_BY_H1_PIPELINE"},
        "limitations": ["OBSERVED_WINDOWS_NOT_COMPLETE_CAMPAIGN_MEASUREMENT", "NETWORK_COUNTERS_HOST_AGGREGATE_NOT_PROCESS_ATTRIBUTED", "NO_CONCURRENCY_OR_PERFORMANCE_BENCHMARK_CLAIM"],
        "node_count": 4, "reports": reports,
        "summary": {"active_process_windows": 2, "completed_jobs_observed": 639, "failed_jobs_observed": 0, "nodes_with_completed_jobs": 4, "orphaned_jobs_observed": 0, "peak_rss_bytes_observed": 1_652_461_568, "process_write_bytes_delta_observed": 38_416_384},
    })
    assert digest(manifest) == "0140c6c939844c1a213c5188b3d8d48d4dbd3976fa01f11b00020a5a716caa21"
    payloads["evidence/resource-windows/manifest.json"] = manifest
    return payloads


def replay_evidence(
    *, h1_payload: bytes, ai_payload: bytes, resource_manifest_payload: bytes,
) -> dict[str, object]:
    return {
        "schema_version": 2, "contract_id": "NERIVANE-PUBLIC-REPLAY-V2",
        "status": "SEALED_PUBLIC_REPLAY", "fictional": True,
        "scenario_id": "NERIVANE-KPI-2026-07",
        "counts": {"documents": 28, "people": 26, "roles": 18, "assignments": 37, "sites": 10, "source_systems": 4, "steps": 7},
        "gates": {"ai_local_fail_closed": "VALIDÉ", "bigquery_h1_sample": "VALIDÉ", "full_h1": "VALIDÉ", "public_sanitization": "VALIDÉ", "seven_step_replay": "VALIDÉ"},
        "source": {"repository": "johann-DP/datapredict-governed-kpi-demo", "commit": "a" * 40},
        "source_bindings": {
            "replay_candidate_v1_tree_sha256": "9" * 64,
            "full_h1_public_report_sha256": digest(h1_payload),
            "full_h1_sample_selection_plan_sha256": "5" * 64,
            "local_materialization_proof_sha256": "6" * 64,
            "local_36_controls_proof_sha256": "7" * 64,
            "ai_fail_closed_overlay_sha256": digest(ai_payload),
            "h1_resource_windows_manifest_sha256": digest(resource_manifest_payload),
        },
        "publication": {"automatic_activation_permitted": False, "maintenance_removal_permitted": False},
        "evidence": {"full_h1": "evidence/full-h1-final-public.json", "park_resource_windows": "evidence/resource-windows/manifest.json", "bigquery_h1_sample": "evidence/bigquery-h1-sample-public.json", "ai_local_fail_closed": "evidence/ai-local-fail-closed.json"},
        "steps": [f"steps/{index:02d}.html" for index in range(1, 8)],
        "limitations": ["INACTIVE_SITE_IMPORT_ONLY", "NO_AUTOMATIC_ACTIVATION", "NO_MAINTENANCE_REMOVAL", "NO_GCP_V2_LOAD_CLAIM_LOCAL_SAMPLE_ONLY", "SELECTED_AI_MODEL_REJECTED_NOT_DEPLOYED"],
    }


def active_data_payload(
    release_placeholder: str,
    *,
    replay_payload: bytes,
    h1_payload: bytes,
    resource_manifest_payload: bytes,
    sample_payload: bytes,
    ai_payload: bytes,
) -> bytes:
    release_root = (
        "../assets/validated-releases/nerivane-v2/" f"{release_placeholder}"
    )
    step_ids = (
        "impasse-metier",
        "diagnostic-opposable",
        "h1-massif",
        "topologie-heterogene",
        "echantillon-controle",
        "veto-ia-fail-closed",
        "transfert-controle",
    )
    titles = (
        "Constater l'impasse métier",
        "Rendre le diagnostic opposable",
        "Prouver le traitement massif H1",
        "Gouverner une topologie hétérogène",
        "Matérialiser et contrôler l'échantillon",
        "Exécuter le veto IA fail-closed",
        "Sceller un transfert inactif",
    )
    steps = [
        {
            "action": f"Action datapredict {index}",
            "href": f"{release_root}/steps/{index:02d}.html",
            "id": step_ids[index - 1],
            "limitation": f"Limite publique {index}",
            "order": index,
            "problem": f"Problème gouverné {index}",
            "proof": f"Preuve assainie {index}",
            "status": "VALIDÉ_FAIL_CLOSED" if index == 6 else "VALIDÉ",
            "title": titles[index - 1],
        }
        for index in range(1, 8)
    ]
    return canonical(
        {
            "boundaries": [
                {
                    "text": "Rapproché par règles déterministes, mais publication bloquée par le modèle IA rejeté.",
                    "title": "KPI métier",
                },
                {
                    "text": "Échantillon au schéma BigQuery contrôlé localement; aucun chargement GCP V2 revendiqué.",
                    "title": "Cloud",
                },
                {
                    "text": "Inférence capturée, qualification échouée, modèle non déployé et porte fail-closed.",
                    "title": "IA locale",
                },
            ],
            "contract_id": "DATAPREDICT-NERIVANE-ACTIVE-SITE-DATA-V2",
            "evidence": [
                {
                    "href": f"{release_root}/replay-manifest.json",
                    "id": "replay-v2",
                    "label": "Manifeste du replay V2",
                    "sha256": digest(replay_payload),
                },
                {
                    "href": f"{release_root}/evidence/full-h1-final-public.json",
                    "id": "full-h1",
                    "label": "Preuve H1 finale assainie",
                    "sha256": digest(h1_payload),
                },
                {
                    "href": f"{release_root}/evidence/resource-windows/manifest.json",
                    "id": "park-resources",
                    "label": "Fenêtres CPU et mémoire du parc H1",
                    "sha256": digest(resource_manifest_payload),
                },
                {
                    "href": f"{release_root}/evidence/bigquery-h1-sample-public.json",
                    "id": "sample-controls",
                    "label": "Synthèse de l’échantillon et des 36 contrôles",
                    "sha256": digest(sample_payload),
                },
                {
                    "href": f"{release_root}/evidence/ai-local-fail-closed.json",
                    "id": "ai-fail-closed",
                    "label": "Overlay IA local fail-closed",
                    "sha256": digest(ai_payload),
                },
            ],
            "fictional_scenario": True,
            "format_version": "2.0.0",
            "metrics": [
                {
                    "label": "Volume H1 encodé",
                    "scope": "Plus de 1,5 Tio sur RAW, BRONZE et SILVER",
                    "value": "1\u202f800\u202f000\u202f000\u202f000 octets",
                },
                {
                    "label": "Lignes physiques",
                    "scope": "Trois couches durables, campagne 2021-H1",
                    "value": "2\u202f004\u202f364\u202f194",
                },
                {
                    "label": "Production distribuée",
                    "scope": "Quatre nœuds pseudonymisés, 330 triplets chacun",
                    "value": "1\u202f320 triplets",
                },
                {
                    "label": "Échantillon gouverné",
                    "scope": "17 tables, matérialisation et contrôles locaux",
                    "value": "210\u202f724 lignes · 36/36 PASS",
                },
            ],
            "publication_boundary": {
                "ai_model_deployment_status": "NOT_DEPLOYED",
                "gcp_v2_load_status": "NOT_CLAIMED_LOCAL_ONLY",
                "kpi_publication_status": "BLOCKED_BY_REJECTED_AI_MODEL",
                "site_replay_status": "ACTIVE",
            },
            "release_reference": release_root,
            "source_commit": "a" * 40,
            "status": "ACTIVE_REPLAY_AVAILABLE",
            "steps": steps,
            "subtitle": "Chaque chiffre est relié au bundle content-addressé.",
            "title": "Les preuves derrière la décision",
        }
    )


def source_payloads(
    *,
    replay_status: str = "SEALED_PUBLIC_REPLAY",
    replay_contract_id: str = importer.REPLAY_CONTRACT_ID,
    promotion_contract_payload: bytes | None = None,
    private_token: str | None = None,
) -> dict[str, tuple[str, bytes]]:
    release_placeholder = "__NERIVANE_V2_RELEASE_ID__"
    h1_payload = canonical(h1_evidence())
    ai_payload = canonical(ai_evidence())
    sample_payload = canonical(sample_evidence())
    resource_payloads = resource_window_evidence()
    replay_value = replay_evidence(
        h1_payload=h1_payload,
        ai_payload=ai_payload,
        resource_manifest_payload=resource_payloads["evidence/resource-windows/manifest.json"],
    )
    replay_value["contract_id"] = replay_contract_id
    replay_value["status"] = replay_status
    replay_payload = canonical(replay_value)
    payloads: dict[str, tuple[str, bytes]] = {
        "index.html": (
            "public_html",
            b"<!doctype html><html lang='fr'><title>Nerivane V2</title></html>",
        ),
        "replay-manifest.json": (
            "public_json",
            replay_payload,
        ),
        "evidence/full-h1-final-public.json": (
            "public_evidence",
            h1_payload,
        ),
        "evidence/bigquery-h1-sample-public.json": (
            "public_evidence",
            sample_payload,
        ),
        "evidence/ai-local-fail-closed.json": (
            "public_evidence",
            ai_payload,
        ),
        **{
            path: ("public_evidence", payload)
            for path, payload in resource_payloads.items()
        },
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
                "<meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<title>Nérivane Distribution — gouvernance d’un KPI à l’échelle Big Data | datapredict</title>"
                "<meta name=\"description\" content=\"Explorez une reprise de gouvernance Data étayée par un corpus H1 massif, un lignage contrôlé et un veto IA local fail-closed.\">"
                "<link rel=\"canonical\" href=\"https://www.datapredict.org/demonstrations/nerivane-distribution.html\">"
                "<meta property=\"og:locale\" content=\"fr_FR\">"
                "<meta property=\"og:type\" content=\"website\">"
                "<meta property=\"og:title\" content=\"Nérivane Distribution — gouvernance d’un KPI à l’échelle Big Data | datapredict\">"
                "<meta property=\"og:description\" content=\"Un replay en sept étapes pour examiner une gouvernance Data prouvée à grande échelle et son veto IA fail-closed.\">"
                "<meta property=\"og:url\" content=\"https://www.datapredict.org/demonstrations/nerivane-distribution.html\">"
                "<meta property=\"og:image\" content=\"https://www.datapredict.org/assets/img/social-datapredict.png\">"
                "<meta name=\"twitter:card\" content=\"summary_large_image\">"
                "<link rel=\"stylesheet\" href=\"../assets/css/site.css\">"
                "<link rel=\"stylesheet\" href=\"../assets/css/demo-nerivane.css\">"
                "<script src=\"../assets/js/demo-nerivane.js\" defer></script>"
                "<script src=\"../assets/js/audience-counter.js\" defer></script>"
                "</head>"
                f"<body class=\"nerivane-demo-page\" data-release-id=\"{release_placeholder}\"><header>"
                "<span id=\"nerivane-public-state\" class=\"nerivane-header__state\" "
                "data-status=\"verification\" role=\"status\" aria-live=\"polite\" "
                "aria-busy=\"true\" aria-label=\"Vérification du replay public en cours\">"
                "<span aria-hidden=\"true\">●</span><span data-state-label>Vérification…</span>"
                "</span></header><main id=\"contenu\"><h1>Nerivane V2 active</h1>"
                "<a href=\"../assets/validated-releases/nerivane-v2/"
                f"{release_placeholder}/index.html\">Replay V2</a></main></body></html>"
            ).encode("utf-8"),
        ),
        "activation/assets/data/nerivane-governance-replay.json": (
            "public_json",
            active_data_payload(
                release_placeholder,
                replay_payload=replay_payload,
                h1_payload=h1_payload,
                resource_manifest_payload=resource_payloads["evidence/resource-windows/manifest.json"],
                sample_payload=sample_payload,
                ai_payload=ai_payload,
            ),
        ),
        "activation/assets/js/demo-nerivane.js": (
            "public_script",
            (
                '"use strict";\n'
                'const DATA_URL = "../assets/data/nerivane-governance-replay.json";\n'
                'const CONTRACT_ID = "DATAPREDICT-NERIVANE-ACTIVE-SITE-DATA-V2";\n'
                'const root = document.getElementById("nerivane-reader");\n'
                'const page = document.body;\n'
                'const headerState = document.getElementById("nerivane-public-state");\n'
                'function setHeaderState(status, label, ariaLabel) {\n'
                '  const labelNode = headerState.querySelector("[data-state-label]");\n'
                '  headerState.dataset.status = status;\n'
                '  headerState.setAttribute("aria-busy", "false");\n'
                '  headerState.setAttribute("aria-label", ariaLabel);\n'
                '  labelNode.textContent = label;\n'
                '}\n'
                'function requireText(value) {\n'
                '  if (typeof value !== "string" || value.trim() === "") throw new Error("text");\n'
                '  return value;\n'
                '}\n'
                'function requireSha(value, label) {\n'
                '  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new Error(`sha:${label}`);\n'
                '  return value;\n'
                '}\n'
                'function validateData(data) {\n'
                '  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("data");\n'
                '  if (data.contract_id !== CONTRACT_ID || data.format_version !== "2.0.0" ||\n'
                '      data.fictional_scenario !== true || data.status !== "ACTIVE_REPLAY_AVAILABLE") {\n'
                '    throw new Error("contract");\n'
                '  }\n'
                '  const releaseId = requireText(page.dataset.releaseId);\n'
                '  if (!/^[0-9a-f]{64}$/.test(releaseId)) throw new Error("release");\n'
                '  const releaseRoot = `../assets/validated-releases/nerivane-v2/${releaseId}`;\n'
                '  if (data.release_reference !== releaseRoot) throw new Error("reference");\n'
                '  if (!Array.isArray(data.metrics) || data.metrics.length !== 4 ||\n'
                '      !Array.isArray(data.steps) || data.steps.length !== 7 ||\n'
                '      !Array.isArray(data.evidence) || data.evidence.length !== 5 ||\n'
                '      !Array.isArray(data.boundaries) || data.boundaries.length !== 3) {\n'
                '    throw new Error("schema");\n'
                '  }\n'
                '  data.steps.forEach((step, index) => {\n'
                '    if (step.order !== index + 1 || step.href !== `${releaseRoot}/steps/${String(index + 1).padStart(2, "0")}.html`) throw new Error("step");\n'
                '  });\n'
                '  const expectedEvidence = [\n'
                '    ["replay-v2", "replay-manifest.json"],\n'
                '    ["full-h1", "evidence/full-h1-final-public.json"],\n'
                '    ["park-resources", "evidence/resource-windows/manifest.json"],\n'
                '    ["sample-controls", "evidence/bigquery-h1-sample-public.json"],\n'
                '    ["ai-fail-closed", "evidence/ai-local-fail-closed.json"],\n'
                '  ];\n'
                '  data.evidence.forEach((proof, index) => {\n'
                '    const [expectedId, expectedPath] = expectedEvidence[index];\n'
                '    if (proof.id !== expectedId) throw new Error("evidence-id");\n'
                '    requireSha(proof.sha256, `evidence[${index}].sha256`);\n'
                '    if (proof.href !== `${releaseRoot}/${expectedPath}`) throw new Error("evidence");\n'
                '  });\n'
                '  return data;\n'
                '}\n'
                'function render(data) {\n'
                '  root.setAttribute("aria-busy", "false");\n'
                '  setHeaderState("valide", "Replay scellé", "Replay authentifié et scellé");\n'
                '}\n'
                'function renderError() {\n'
                '  root.setAttribute("aria-busy", "false");\n'
                '  setHeaderState(\n'
                '      "indisponible",\n'
                '      "Indisponible / non authentifié",\n'
                '      "Replay public indisponible ou non authentifié",\n'
                '  );\n'
                '}\n'
                'fetch(DATA_URL, { credentials: "same-origin", cache: "no-cache" })\n'
                '    .then((response) => {\n'
                '      if (!response.ok) throw new Error("Registre public indisponible");\n'
                '      return response.json();\n'
                '    })\n'
                '    .then(validateData)\n'
                '    .then(render)\n'
                '    .catch(renderError);\n'
            ).encode("utf-8"),
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
            b'<span data-maintenance="true">Maintenance</span>'
            b'<p>Maintenance planifi\xc3\xa9e</p>'
            b'<h1>La d\xc3\xa9monstration N\xc3\xa9rivane est en cours de finalisation</h1>'
            b'</body></html>'
        ),
        "assets/data/nerivane-governance-replay.json": b"maintenance data",
        "assets/js/demo-nerivane.js": b"maintenance js",
        "assets/css/demo-nerivane.css": b"maintenance css",
        "demonstrations.html": (
            b'<!doctype html><html lang="fr"><body><ul>\n'
            b'<!-- NERIVANE_CATALOGUE_CARD_START -->\n'
            b'<li><a aria-labelledby="nerivane-title"><h3 id="nerivane-title">'
            b'Nerivane</h3><span>Disponible \xc2\xb7 maintenance</span>'
            b'<span>Consulter la version de maintenance</span></a></li>\n'
            b'<!-- NERIVANE_CATALOGUE_CARD_END -->\n'
            b'<li id="fissures"><a class="demonstrations-page__card-link" '
            b'href="demonstrations/fissures.html"><span class="demonstrations-page__card-status">'
            b'En maintenance</span><span>Consulter la version en maintenance</span></a>'
            b'</li></ul></body></html>'
        ),
        "assets/nerivane-public-v1/SHA256SUMS": b"legacy sums",
        "assets/nerivane-public-v1/index.html": b"legacy replay",
        "demonstrations/fissures.html": (
            b'<!doctype html><html lang="fr"><body class="fissures-demo" '
            b'data-maintenance="true"><h1>D\xc3\xa9monstration 2 \xc2\xb7 En maintenance</h1>'
            b'</body></html>'
        ),
        "assets/css/demo-fissures.css": b"protected fissures css",
        "assets/css/site.css": b"protected responsive site css",
        "assets/css/demo-ormevia.css": b"protected ormevia css",
        "assets/data/ormevia-scenarios.json": b"protected ormevia data",
        "assets/js/audience-counter.js": b"protected audience counter",
        "assets/js/demo-fissures.js": b"protected fissures js",
        "assets/js/demo-ormevia.js": b"protected ormevia js",
        "assets/figures/demo-2/content-manifest.json": b"protected demo2 figures",
        "assets/img/demo-2-thumbnails/figure.webp": b"protected demo2 thumbnail",
        "assets/validated-releases/demo-2/release/.READY": b"protected demo2 release",
        "contracts/nerivane-v2-site-promotion-v1.json": (
            importer.PROMOTION_CONTRACT_PATH.read_bytes()
        ),
        "demonstrations/ormevia-batiment.html": b"protected ormevia page",
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
        self.assertEqual(result["published_file_count"], 24)
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
        for private_token in (
            " /home/jo/private ",
            " /run/user/1000/private/socket ",
        ):
            with self.subTest(private_token=private_token):
                source = build_source(self.sources, private_token=private_token)

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
