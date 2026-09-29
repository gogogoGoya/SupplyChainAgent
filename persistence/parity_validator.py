"""Parity checks between filesystem artifacts and SQL mirror projections."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from persistence.filesystem_repository import FilesystemRunArchiveRepository
from persistence.sql_mirror import SQLiteMirrorRepository


PARITY_REPORT_SCHEMA_VERSION = "storage_parity_report.v1"


def _canonical(payload: Optional[Dict[str, Any]]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _projection_key(
    projection_name: str,
    *,
    run_id: str,
    scenario_id: str,
    round_id: int,
    enterprise_id: Optional[str] = None,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    if projection_name == "history_projection":
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "enterprise_id": enterprise_id,
            "day": int(round_id),
        }
    if projection_name in {
        "run_metrics_projection",
        "order_lifecycle_projection",
        "topology_projection",
        "enterprise_daily_metrics_projection",
    }:
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
        }
    if projection_name == "case_evaluation_projection":
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "case_id": case_id,
            "round_id": int(round_id),
        }
    return {}


class ProjectionParityValidator:
    """Compare authoritative filesystem artifacts with optional SQL mirror rows."""

    def __init__(
        self,
        filesystem_repository: FilesystemRunArchiveRepository,
        sql_repository: SQLiteMirrorRepository,
    ):
        self.filesystem_repository = filesystem_repository
        self.sql_repository = sql_repository

    def compare_run_metadata(self, run_id: str) -> Dict[str, Any]:
        filesystem_payload = self.filesystem_repository.get_run(run_id)
        sql_payload = self.sql_repository.get_run(run_id)
        return self._build_check(
            check_type="run_metadata",
            identity={"run_id": run_id},
            filesystem_payload=filesystem_payload,
            sql_payload=sql_payload,
        )

    def compare_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
    ) -> Dict[str, Any]:
        filesystem_payload = self.filesystem_repository.get_projection(
            projection_name,
            key,
        )
        sql_payload = self.sql_repository.get_projection(projection_name, key)
        return self._build_check(
            check_type=projection_name,
            identity={"projection_name": projection_name, "key": key},
            filesystem_payload=filesystem_payload,
            sql_payload=sql_payload,
        )

    def compare_core_round(
        self,
        *,
        run_id: str,
        scenario_id: str,
        round_id: int,
        enterprise_ids: List[str] = None,
        case_id: Optional[str] = None,
        include_multi_enterprise_projections: bool = False,
        include_run_metadata: bool = True,
    ) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        if include_run_metadata:
            checks.append(self.compare_run_metadata(run_id))

        for enterprise_id in enterprise_ids or []:
            checks.append(
                self.compare_projection(
                    "history_projection",
                    _projection_key(
                        "history_projection",
                        run_id=run_id,
                        scenario_id=scenario_id,
                        enterprise_id=enterprise_id,
                        round_id=round_id,
                    ),
                )
            )

        checks.append(
            self.compare_projection(
                "run_metrics_projection",
                _projection_key(
                    "run_metrics_projection",
                    run_id=run_id,
                    scenario_id=scenario_id,
                    round_id=round_id,
                ),
            )
        )
        if case_id:
            checks.append(
                self.compare_projection(
                    "case_evaluation_projection",
                    _projection_key(
                        "case_evaluation_projection",
                        run_id=run_id,
                        scenario_id=scenario_id,
                        case_id=case_id,
                        round_id=round_id,
                    ),
                )
            )
        if include_multi_enterprise_projections:
            for projection_name in (
                "order_lifecycle_projection",
                "topology_projection",
                "enterprise_daily_metrics_projection",
            ):
                checks.append(
                    self.compare_projection(
                        projection_name,
                        _projection_key(
                            projection_name,
                            run_id=run_id,
                            scenario_id=scenario_id,
                            round_id=round_id,
                        ),
                    )
                )
        return {
            "schema_version": PARITY_REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
            "ok": all(check["ok"] for check in checks),
            "checks": checks,
            "mismatch_count": sum(1 for check in checks if not check["ok"]),
        }

    def _build_check(
        self,
        *,
        check_type: str,
        identity: Dict[str, Any],
        filesystem_payload: Optional[Dict[str, Any]],
        sql_payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        filesystem_present = filesystem_payload is not None
        sql_present = sql_payload is not None
        payload_equal = _canonical(filesystem_payload) == _canonical(sql_payload)
        return {
            "check_type": check_type,
            "identity": identity,
            "ok": filesystem_present and sql_present and payload_equal,
            "filesystem_present": filesystem_present,
            "sql_present": sql_present,
            "payload_equal": payload_equal,
        }
