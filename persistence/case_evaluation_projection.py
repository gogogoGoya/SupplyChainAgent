"""Case evaluation projection for single-enterprise diagnostic scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.single_case_evaluation import evaluate_case_action_records


CASE_EVALUATION_PROJECTION_SCHEMA_VERSION = "case_evaluation_projection.v1"
DEFAULT_ACTION_DEPARTMENTS = (
    "finance",
    "hr",
    "inventory",
    "procurement",
    "production",
    "sales",
)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def _normalize_action_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _payload_has_failure(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered_key = str(key).lower()
            if lowered_key in {"failed_output", "failures", "errors"} and value:
                return True
            if lowered_key in {"success", "ok"} and value is False:
                return True
            if lowered_key in {"status", "result"} and str(value).lower() in {"failed", "error"}:
                return True
            if _payload_has_failure(value):
                return True
    if isinstance(payload, list):
        return any(_payload_has_failure(item) for item in payload)
    return False


class CaseEvaluationProjectionBuilder:
    """Build a per-round projection from single-enterprise action files."""

    def __init__(
        self,
        read_json: Callable[[Path, Any], Any] = None,
        action_departments: List[str] = None,
    ):
        self.read_json = read_json or _read_json
        self.action_departments = tuple(action_departments or DEFAULT_ACTION_DEPARTMENTS)

    def _read_department_actions(
        self,
        enterprise_dir: Path,
        round_id: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        actions_by_department: Dict[str, List[Dict[str, Any]]] = {}
        for department in self.action_departments:
            day_dir = enterprise_dir / "department" / department / f"day{round_id}"
            candidates = [day_dir / f"{department}_action.json"]
            if department in {"procurement", "sales"}:
                candidates.append(day_dir / f"pre_{department}_action.json")
            if department == "sales":
                # Market seeds are separate artifacts so same-day order creation
                # and acceptance remain executable during custom prewarm.
                candidates.append(day_dir / "sales_market_seed_action.json")
            records: List[Dict[str, Any]] = []
            source_files: List[str] = []
            for candidate in candidates:
                payload = self.read_json(candidate, None)
                normalized = _normalize_action_payload(payload)
                if normalized:
                    records.extend(normalized)
                    source_files.append(str(candidate))
            if records:
                result_candidates = [day_dir / f"{department}_result.json"]
                if department == "finance":
                    result_candidates.append(day_dir / "finance_advice_result.json")
                if department == "sales":
                    result_candidates.append(day_dir / "sales_market_seed_result.json")
                result_files = []
                execution_failed = False
                for candidate in result_candidates:
                    payload = self.read_json(candidate, None)
                    if payload is None:
                        continue
                    result_files.append(str(candidate))
                    execution_failed = execution_failed or _payload_has_failure(payload)
                actions_by_department[department] = [
                    {
                        "actions": records,
                        "source_files": source_files,
                        "result_files": result_files,
                        "execution_failed": execution_failed,
                    }
                ]
        return actions_by_department

    def _read_department_actions_for_rounds(
        self,
        enterprise_dir: Path,
        round_ids: List[int],
    ) -> Dict[str, List[Dict[str, Any]]]:
        merged: Dict[str, List[Dict[str, Any]]] = {}
        for round_id in round_ids:
            round_actions = self._read_department_actions(enterprise_dir, round_id)
            for department, records in round_actions.items():
                bucket = merged.setdefault(department, [])
                for record in records:
                    enriched = dict(record)
                    enriched["round_id"] = round_id
                    bucket.append(enriched)
        return merged

    @staticmethod
    def _diagnostic_rounds(case_policy: Dict[str, Any], round_id: int) -> List[int]:
        mode = str(case_policy.get("evaluation_mode") or "diagnostic_window")
        if mode == "full_run_guard":
            return list(range(0, int(round_id) + 1))
        configured = case_policy.get("diagnostic_evaluation_rounds") or [0]
        rounds = []
        for value in configured:
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                continue
            if numeric <= int(round_id):
                rounds.append(numeric)
        if not rounds:
            rounds = [0]
        return sorted(set(rounds))

    def build(
        self,
        *,
        workspace_dir: Path,
        round_id: int,
    ) -> Optional[Dict[str, Any]]:
        workspace_dir = Path(workspace_dir)
        run_meta = _safe_dict(self.read_json(workspace_dir / "run_meta.json", {}))
        case_policy = _safe_dict(
            run_meta.get("single_enterprise_case")
            or _safe_dict(run_meta.get("scenario_config")).get("single_enterprise_case")
        )
        case_id = str(
            case_policy.get("case_id")
            or run_meta.get("scenario_id")
            or ""
        )
        if not case_id.startswith("single_case_"):
            return None

        enterprise_ids = [
            str(item)
            for item in run_meta.get("enterprise_ids", [])
            if str(item or "").strip()
        ]
        if len(enterprise_ids) != 1:
            return None

        enterprise_id = enterprise_ids[0]
        enterprise_dir = workspace_dir / "enterprises" / enterprise_id
        diagnostic_rounds = self._diagnostic_rounds(case_policy, round_id)
        window_actions_by_department = self._read_department_actions_for_rounds(
            enterprise_dir,
            diagnostic_rounds,
        )
        evaluation = evaluate_case_action_records(case_id, window_actions_by_department)
        actions_by_department = self._read_department_actions(
            enterprise_dir,
            round_id,
        )
        round_evaluation = evaluate_case_action_records(
            case_id,
            actions_by_department,
            allow_stable_noop_round=bool(evaluation.get("passed")),
            stable_noop_reason=(
                "diagnostic_window_already_passed_current_round_has_no_execution_failure"
            ),
        )
        return {
            "schema_version": CASE_EVALUATION_PROJECTION_SCHEMA_VERSION,
            "run_id": str(run_meta.get("run_id") or "workspace_unarchived"),
            "scenario_id": str(run_meta.get("scenario_id") or case_id),
            "case_id": case_id,
            "enterprise_id": enterprise_id,
            "round_id": int(round_id),
            "case_policy": case_policy,
            "evaluation_scope": {
                "mode": str(case_policy.get("evaluation_mode") or "diagnostic_window"),
                "diagnostic_rounds": diagnostic_rounds,
                "current_round": int(round_id),
                "primary_evaluation": "diagnostic_window_cumulative",
            },
            "evaluation": evaluation,
            "round_evaluation": round_evaluation,
            "actions_by_department": actions_by_department,
            "window_actions_by_department": window_actions_by_department,
        }


def write_case_evaluation_projection(
    *,
    workspace_dir: Path,
    round_id: int,
    output_path: Path,
) -> Optional[Dict[str, Any]]:
    payload = CaseEvaluationProjectionBuilder().build(
        workspace_dir=workspace_dir,
        round_id=round_id,
    )
    if payload is None:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
