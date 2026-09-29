"""Read-side query helpers for SQL mirror projections."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.sql_mirror import SQLiteMirrorRepository
from persistence.sql_projection_tables import (
    ENTERPRISE_DAILY_METRICS_TABLE,
    ORDER_LIFECYCLE_ORDERS_TABLE,
    TOPOLOGY_EDGES_TABLE,
    TOPOLOGY_NODES_TABLE,
)


RUN_METRICS_PROJECTION = "run_metrics_projection"
CASE_EVALUATION_PROJECTION = "case_evaluation_projection"


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _matches(value: Any, expected: Optional[str]) -> bool:
    return expected is None or str(value or "") == str(expected)


class SQLMirrorQueryService:
    """
    Thin read model over the SQL mirror repository.

    The mirror remains a secondary store. These queries are intended for
    dashboards, operations pages, and post-run inspection rather than runtime
    decision making.
    """

    def __init__(self, repository: SQLiteMirrorRepository):
        self.repository = repository

    def list_runs(
        self,
        *,
        scenario_id: Optional[str] = None,
        status: Optional[str] = None,
        orchestrator: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        matched: List[Dict[str, Any]] = []
        for run in self.repository.list_runs():
            if not _matches(run.get("scenario_id"), scenario_id):
                continue
            if not _matches(run.get("status"), status):
                continue
            if not _matches(run.get("orchestrator"), orchestrator):
                continue
            matched.append(run)
            if limit is not None and len(matched) >= max(0, int(limit)):
                break
        return matched

    def list_scenarios(self) -> List[Dict[str, Any]]:
        scenarios: Dict[str, Dict[str, Any]] = {}
        for run in self.repository.list_runs():
            scenario_id = str(run.get("scenario_id") or "")
            if not scenario_id:
                continue
            scenario = scenarios.setdefault(
                scenario_id,
                {
                    "scenario_id": scenario_id,
                    "name": "",
                    "run_count": 0,
                    "status_counts": {},
                    "orchestrators": [],
                },
            )
            scenario["run_count"] += 1
            status = str(run.get("status") or "unknown")
            scenario["status_counts"][status] = (
                scenario["status_counts"].get(status, 0) + 1
            )
            orchestrator = str(run.get("orchestrator") or "")
            if orchestrator and orchestrator not in scenario["orchestrators"]:
                scenario["orchestrators"].append(orchestrator)
            if not scenario["name"]:
                scenario_meta = run.get("scenario_meta") or {}
                scenario["name"] = str(scenario_meta.get("name") or scenario_id)
        return [scenarios[key] for key in sorted(scenarios)]

    def get_run_metrics_summary(
        self,
        run_id: str,
        *,
        round_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._latest_projection_payload(
            RUN_METRICS_PROJECTION,
            run_id=run_id,
            round_id=round_id,
        )

    def get_case_evaluation_summary(
        self,
        run_id: str,
        *,
        case_id: Optional[str] = None,
        round_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._latest_projection_payload(
            CASE_EVALUATION_PROJECTION,
            run_id=run_id,
            case_id=case_id,
            round_id=round_id,
        )

    def list_order_rows(
        self,
        run_id: str,
        *,
        round_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return list(
            self.repository.list_physical_projection_rows(
                ORDER_LIFECYCLE_ORDERS_TABLE,
                run_id=run_id,
                round_id=round_id,
            )
        )

    def list_topology_nodes(
        self,
        run_id: str,
        *,
        round_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return list(
            self.repository.list_physical_projection_rows(
                TOPOLOGY_NODES_TABLE,
                run_id=run_id,
                round_id=round_id,
            )
        )

    def list_topology_edges(
        self,
        run_id: str,
        *,
        round_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return list(
            self.repository.list_physical_projection_rows(
                TOPOLOGY_EDGES_TABLE,
                run_id=run_id,
                round_id=round_id,
            )
        )

    def list_enterprise_daily_metrics(
        self,
        run_id: str,
        *,
        round_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return list(
            self.repository.list_physical_projection_rows(
                ENTERPRISE_DAILY_METRICS_TABLE,
                run_id=run_id,
                round_id=round_id,
            )
        )

    def _latest_projection_payload(
        self,
        projection_name: str,
        *,
        run_id: str,
        case_id: Optional[str] = None,
        round_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for record in self.repository.list_projection_records(projection_name):
            key = record.get("key") or {}
            if str(key.get("run_id") or "") != str(run_id):
                continue
            if case_id is not None and str(key.get("case_id") or "") != str(case_id):
                continue
            if round_id is not None and _safe_int(key.get("round_id")) != int(round_id):
                continue
            candidates.append(record)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: _safe_int((item.get("key") or {}).get("round_id")),
            reverse=True,
        )
        return candidates[0].get("payload") or {}
