"""Auditable Agent/Scripted replay support for interrupted E1 runs."""

from __future__ import annotations

import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.multi_tenant_utils import MultiTenantUtils


class LongHorizonHybridReplayRunner:
    """Reuse valid archived Agent actions and repair fallback calls with rules."""

    def __init__(self, workspace_dir: Path, enterprise_spec: Any, scripted_runner: Any):
        self.workspace_dir = Path(workspace_dir)
        self.enterprise_spec = enterprise_spec
        self.enterprise_name = str(enterprise_spec.enterprise_name)
        self.scripted_runner = scripted_runner

    def _policy(self) -> Dict[str, Any]:
        run_meta = MultiTenantUtils._read_json_if_exists(
            self.workspace_dir / "run_meta.json",
            {},
        )
        scenario_config = run_meta.get("scenario_config") or {}
        runtime = scenario_config.get("runtime_injection") or {}
        policy = runtime.get("long_horizon_hybrid_replay_policy") or {}
        return policy if isinstance(policy, dict) else {}

    def enabled_for_round(self, round_id: int) -> bool:
        policy = self._policy()
        if not policy.get("enabled"):
            return False
        try:
            start_round = int(policy.get("start_round", 0))
            end_round = int(policy.get("end_round", -1))
        except (TypeError, ValueError):
            return False
        return start_round <= int(round_id) <= end_round

    def _source_root(self) -> Path:
        raw = str(self._policy().get("source_artifact_root") or "").strip()
        if not raw:
            raise ValueError("Hybrid replay source_artifact_root is missing")
        source = Path(raw).expanduser()
        if not source.is_absolute():
            source = (self.workspace_dir.parent / source).resolve()
        else:
            source = source.resolve()
        if source == self.workspace_dir.resolve():
            raise ValueError("Hybrid replay source and output workspace must differ")
        if not (source / "run_meta.json").exists():
            raise FileNotFoundError(f"Hybrid replay source is invalid: {source}")
        return source

    def write_analysis(self, round_id: int) -> Optional[List[dict]]:
        if not self.enabled_for_round(round_id):
            return None
        source_root = self._source_root()
        target_root = self.workspace_dir / "enterprises" / self.enterprise_name
        source_analysis = (
            source_root
            / "enterprises"
            / self.enterprise_name
            / "records"
            / f"day{round_id}"
            / "analysis.json"
        )
        analyst_dir = (
            target_root / "department" / "analyst" / f"day{round_id}"
        )
        analyst_dir.mkdir(parents=True, exist_ok=True)
        if source_analysis.exists():
            shutil.copy2(source_analysis, analyst_dir / "parent_agent_analysis.json")

        payload = {
            "schema_version": "hybrid_replay_analysis.v1",
            "round_id": int(round_id),
            "control_mode": "archived_agent_with_state_driven_scripted_repair",
            "enterprise_summarys": (
                "Derived E1 replay: archived non-fallback Agent actions are reused "
                "when executable; fallback or incompatible calls use current-state rules."
            ),
            "department_targets": {
                department: {
                    "target": "Preserve profitable service with executable current-state actions.",
                    "evaluation": "Every action records archived_agent or scripted_repair provenance.",
                    "reason": "Hybrid replay is a derived diagnostic run, not a pure Agent sample.",
                }
                for department in ("sales", "procurement", "production", "inventory", "hr")
            },
            "parent_agent_analysis_available": source_analysis.exists(),
            "parent_run_id": self._policy().get("source_run_id"),
        }
        self.scripted_runner._write_json(target_root / "analysis.json", payload)
        self.scripted_runner._write_json(
            analyst_dir / "analyst_execution_audit.json",
            {
                "schema_version": "skill_audit.v1",
                "status": "hybrid_replay",
                "enterprise_id": self.enterprise_name,
                "department": "analyst",
                "phase": "analyst",
                "day": int(round_id),
                "attempts": 0,
                "success": True,
                "fallback_used": False,
                "decision_source": "hybrid_replay_control_analysis",
                "parent_agent_analysis_available": source_analysis.exists(),
            },
        )
        return [{
            "role": "hybrid_replay_analyst",
            "content": f"hybrid replay control analysis generated for day{round_id}",
        }]

    def run_department(
        self,
        dept: Any,
        round_id: int,
        *,
        need_trade: bool,
    ) -> Optional[List[dict]]:
        if not self.enabled_for_round(round_id):
            return None
        if str(getattr(dept, "type", "")) == "Auto":
            return None
        phase = "trade" if need_trade else "decision"
        source_root = self._source_root()
        department = str(dept.dept_id)
        source_day = (
            source_root
            / "enterprises"
            / self.enterprise_name
            / "department"
            / department
            / f"day{round_id}"
        )
        target_day = (
            self.workspace_dir
            / "enterprises"
            / self.enterprise_name
            / "department"
            / department
            / f"day{round_id}"
        )
        target_day.mkdir(parents=True, exist_ok=True)
        audit_name = (
            "trade_skill_execution_audit.json"
            if need_trade
            else "skill_execution_audit.json"
        )
        source_audit = self._read_json(source_day / audit_name, {})
        parent_fallback = bool(source_audit.get("fallback_used", True))
        source_action = source_day / self._source_action_name(dept, need_trade)
        target_action = target_day / f"{department}_action.json"
        started_at = time.time()
        decision_source = "scripted_repair_parent_fallback"
        archived_failure: Optional[Dict[str, Any]] = None

        if (
            not parent_fallback
            and source_audit.get("success") is not False
            and source_action.exists()
        ):
            archived_payload = self._read_json(source_action, None)
            if archived_payload is not None:
                remapped = self._remap_dynamic_identifiers(
                    archived_payload,
                    source_day=source_day,
                    target_day=target_day,
                    department=department,
                    need_trade=need_trade,
                )
                self.scripted_runner._write_json(target_action, remapped)
                MultiTenantUtils._normalize_action_file_if_possible(
                    target_action,
                    department,
                )
                result = MultiTenantUtils.execute_enterprise_dept_action(
                    round_id=round_id,
                    retry_time=0,
                    dept=department,
                    enterprise_name=self.enterprise_name,
                )
                if result.get("status") == "success":
                    decision_source = "archived_agent"
                    self._write_phase_artifacts(
                        target_day=target_day,
                        audit_name=audit_name,
                        department=department,
                        phase=phase,
                        round_id=round_id,
                        decision_source=decision_source,
                        parent_fallback=False,
                        source_action=source_action,
                        execution_result=result,
                        elapsed_seconds=time.time() - started_at,
                    )
                    return [self._message(department, round_id, decision_source)]
                archived_failure = {
                    "source_action": str(source_action),
                    "remapped_action": self._read_json(target_action, remapped),
                    "execution_result": result,
                }
                decision_source = "scripted_repair_after_agent_incompatibility"
                self._preserve_failed_agent_attempt(target_day, phase, archived_failure)

        scripted_payload = self._build_e1_scripted_action(
            department,
            round_id,
            need_trade=need_trade,
        )
        self.scripted_runner._write_json(target_action, scripted_payload)
        MultiTenantUtils._normalize_action_file_if_possible(target_action, department)
        result = MultiTenantUtils.execute_enterprise_dept_action(
            round_id=round_id,
            retry_time=1,
            dept=department,
            enterprise_name=self.enterprise_name,
        )
        scripted_recovery: Optional[Dict[str, Any]] = None
        if (
            result.get("status") != "success"
            and need_trade
            and self._is_already_resolved_trade_failure(result)
        ):
            scripted_recovery = {
                "reason": "proposal_already_resolved_by_concurrent_counterparty",
                "failed_action": self._read_json(target_action, scripted_payload),
                "execution_result": result,
            }
            self._preserve_failed_scripted_attempt(
                target_day,
                phase,
                scripted_recovery,
            )
            decision_source = f"{decision_source}_stale_trade_noop"
            noop_payload = self.scripted_runner._action_pass(
                department,
                "E1 long-horizon recovery rule: the counterparty already resolved this proposal; no duplicate response is required.",
            )
            self.scripted_runner._write_json(target_action, noop_payload)
            MultiTenantUtils._normalize_action_file_if_possible(
                target_action,
                department,
            )
            result = MultiTenantUtils.execute_enterprise_dept_action(
                round_id=round_id,
                retry_time=2,
                dept=department,
                enterprise_name=self.enterprise_name,
            )
        if result.get("status") != "success":
            raise RuntimeError(
                "E1 hybrid scripted repair action failed: "
                f"enterprise={self.enterprise_name}, department={department}, "
                f"round={round_id}, phase={phase}, result={result}"
            )
        self._write_phase_artifacts(
            target_day=target_day,
            audit_name=audit_name,
            department=department,
            phase=phase,
            round_id=round_id,
            decision_source=decision_source,
            parent_fallback=parent_fallback,
            source_action=source_action,
            execution_result=result,
            elapsed_seconds=time.time() - started_at,
            archived_failure=archived_failure,
            scripted_recovery=scripted_recovery,
        )
        return [self._message(department, round_id, decision_source)]

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return default

    @staticmethod
    def _source_action_name(dept: Any, need_trade: bool) -> str:
        department = str(dept.dept_id)
        # The normal round archiver moves both sales and procurement main-phase
        # files to pre_* before the trade refresh, even when that enterprise has
        # no second invocation for the department.
        if not need_trade and department in {"sales", "procurement"}:
            return f"pre_{department}_action.json"
        return f"{department}_action.json"

    def _build_e1_scripted_action(
        self,
        department: str,
        round_id: int,
        *,
        need_trade: bool,
    ) -> Any:
        payload = self.scripted_runner._build_department_action(
            department,
            round_id,
            need_trade,
        )
        if department == "sales" and not need_trade and self.enterprise_name != "Retailer":
            actions = payload if isinstance(payload, list) else [payload]
            actions = [
                item
                for item in actions
                if isinstance(item, dict)
                and (item.get("action") or {}).get("action_name") != "develop_market"
            ]
            if not actions:
                payload = self.scripted_runner._action_pass(
                    "sales",
                    "E1 upstream sales respond only to real B2B demand; no executable order is available and no external retail market will be created.",
                )
            else:
                payload = actions
        return self._replace_text(payload, {
            "ME-RB fixed rule": "E1 long-horizon recovery rule",
            "rule algorithm": "E1 state-driven recovery rule",
        })

    @classmethod
    def _replace_text(cls, value: Any, replacements: Dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {key: cls._replace_text(child, replacements) for key, child in value.items()}
        if isinstance(value, list):
            return [cls._replace_text(child, replacements) for child in value]
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
        return value

    def _remap_dynamic_identifiers(
        self,
        payload: Any,
        *,
        source_day: Path,
        target_day: Path,
        department: str,
        need_trade: bool,
    ) -> Any:
        remapped = deepcopy(payload)
        actions = remapped if isinstance(remapped, list) else [remapped]
        used_proposals: set[str] = set()
        used_orders: set[str] = set()
        for item in actions:
            if not isinstance(item, dict):
                continue
            action = item.get("action") or {}
            params = action.get("action_param") or {}
            if not isinstance(params, dict):
                continue
            action_name = str(action.get("action_name") or "")
            if action_name in {"accept_proposal_order", "reject_proposal_order"}:
                replacement = self._match_proposal_id(
                    source_day / "trade_decision_card.json",
                    target_day / "trade_decision_card.json",
                    str(params.get("proposal_id") or ""),
                    action_name,
                    used_proposals,
                )
                if replacement:
                    params["proposal_id"] = replacement
                    used_proposals.add(replacement)
            elif action_name in {"accept_order", "reject_order"}:
                replacement = self._match_sales_order_id(
                    source_day / f"{department}.json",
                    target_day / f"{department}.json",
                    str(params.get("order_id") or ""),
                    used_orders,
                )
                if replacement:
                    params["order_id"] = replacement
                    used_orders.add(replacement)
        return remapped

    def _match_proposal_id(
        self,
        source_path: Path,
        target_path: Path,
        old_id: str,
        action_name: str,
        used: set[str],
    ) -> Optional[str]:
        source = self._read_json(source_path, {})
        target = self._read_json(target_path, {})
        source_rows = self._collect_records(source, "proposal_id")
        target_rows = self._collect_records(target, "proposal_id")
        source_row = next((row for row in source_rows if str(row.get("proposal_id")) == old_id), {})
        candidates = [row for row in target_rows if str(row.get("proposal_id") or "") not in used]
        candidate_ids = {
            str((candidate.get("action_param") or {}).get("proposal_id") or candidate.get("proposal_id"))
            for candidate in target.get("action_candidates") or []
            if isinstance(candidate, dict) and candidate.get("action_name") == action_name
        }
        if candidate_ids:
            candidates = [row for row in candidates if str(row.get("proposal_id")) in candidate_ids]
        if not candidates:
            return None
        return str(min(candidates, key=lambda row: self._semantic_distance(source_row, row)).get("proposal_id"))

    def _match_sales_order_id(
        self,
        source_path: Path,
        target_path: Path,
        old_id: str,
        used: set[str],
    ) -> Optional[str]:
        source = self._read_json(source_path, {})
        target = self._read_json(target_path, {})
        source_rows = self._available_orders(source)
        target_rows = [
            row for row in self._available_orders(target)
            if str(row.get("order_id") or row.get("id") or "") not in used
        ]
        source_row = next(
            (
                row for row in source_rows
                if str(row.get("order_id") or row.get("id") or "") == old_id
            ),
            {},
        )
        if not target_rows:
            return None
        selected = min(target_rows, key=lambda row: self._semantic_distance(source_row, row))
        return str(selected.get("order_id") or selected.get("id") or "") or None

    @classmethod
    def _collect_records(cls, value: Any, identifier: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if isinstance(value, dict):
            if value.get(identifier):
                rows.append(value)
            for child in value.values():
                rows.extend(cls._collect_records(child, identifier))
        elif isinstance(value, list):
            for child in value:
                rows.extend(cls._collect_records(child, identifier))
        unique: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            unique.setdefault(str(row.get(identifier)), row)
        return list(unique.values())

    @staticmethod
    def _available_orders(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        self_state = payload.get("self_state") or {}
        orders = self_state.get("sales_orders") or self_state.get("orders") or {}
        return [row for row in orders.get("available") or [] if isinstance(row, dict)]

    @staticmethod
    def _semantic_distance(left: Dict[str, Any], right: Dict[str, Any]) -> tuple:
        def number(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        identity_fields = (
            "buyer_company_id",
            "seller_company_id",
            "source_id",
            "product_id",
            "material_id",
        )
        identity_mismatch = sum(
            1
            for field in identity_fields
            if left.get(field) not in (None, "")
            and right.get(field) not in (None, "")
            and str(left.get(field)) != str(right.get(field))
        )
        quantity_gap = abs(
            number(left.get("quantity") or left.get("requested_quantity"))
            - number(right.get("quantity") or right.get("requested_quantity"))
        )
        price_gap = abs(
            number(left.get("proposed_price") or left.get("unit_price"))
            - number(right.get("proposed_price") or right.get("unit_price"))
        )
        deadline_gap = abs(
            number(left.get("delivery_deadline") or left.get("proposed_delivery_round"))
            - number(right.get("delivery_deadline") or right.get("proposed_delivery_round"))
        )
        return (identity_mismatch, quantity_gap, price_gap, deadline_gap)

    @staticmethod
    def _preserve_failed_agent_attempt(
        target_day: Path,
        phase: str,
        payload: Dict[str, Any],
    ) -> None:
        attempt_dir = target_day / "hybrid_replay_attempts"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / f"{phase}_archived_agent_failure.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        for error_path in target_day.glob("*_error_*.json"):
            shutil.move(str(error_path), str(attempt_dir / error_path.name))

    @classmethod
    def _is_already_resolved_trade_failure(cls, result: Dict[str, Any]) -> bool:
        error_path = Path(str(result.get("file_path") or ""))
        payload = cls._read_json(error_path, [])
        text = json.dumps(payload, ensure_ascii=False, default=str).lower()
        return any(
            marker in text
            for marker in (
                "superseded",
                "already accepted",
                "already rejected",
                "status is accepted",
                "status is rejected",
                "status is cancelled",
                "status is expired",
            )
        )

    @staticmethod
    def _preserve_failed_scripted_attempt(
        target_day: Path,
        phase: str,
        payload: Dict[str, Any],
    ) -> None:
        attempt_dir = target_day / "hybrid_replay_attempts"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / f"{phase}_scripted_stale_trade.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        for error_path in target_day.glob("*_error_*.json"):
            target = attempt_dir / f"{phase}_scripted_{error_path.name}"
            shutil.move(str(error_path), str(target))

    def _write_phase_artifacts(
        self,
        *,
        target_day: Path,
        audit_name: str,
        department: str,
        phase: str,
        round_id: int,
        decision_source: str,
        parent_fallback: bool,
        source_action: Path,
        execution_result: Dict[str, Any],
        elapsed_seconds: float,
        archived_failure: Optional[Dict[str, Any]] = None,
        scripted_recovery: Optional[Dict[str, Any]] = None,
    ) -> None:
        action_payload = self._read_json(target_day / f"{department}_action.json", [])
        actions_count = len(action_payload) if isinstance(action_payload, list) else 1
        provenance = {
            "schema_version": "long_horizon_hybrid_provenance.v1",
            "derived_run": True,
            "pure_agent_sample": False,
            "parent_run_id": self._policy().get("source_run_id"),
            "parent_action_path": str(source_action),
            "enterprise_id": self.enterprise_name,
            "department": department,
            "phase": phase,
            "round_id": int(round_id),
            "parent_fallback_used": bool(parent_fallback),
            "decision_source": decision_source,
            "archived_agent_incompatibility": bool(archived_failure),
            "scripted_concurrency_recovery": bool(scripted_recovery),
        }
        self.scripted_runner._write_json(
            target_day / f"{phase}_provenance.json",
            provenance,
        )
        self.scripted_runner._write_json(
            target_day / audit_name,
            {
                "schema_version": "skill_audit.v1",
                "status": "hybrid_replay",
                "enterprise_id": self.enterprise_name,
                "department": department,
                "phase": phase,
                "day": int(round_id),
                "attempts": 0,
                "success": True,
                "fallback_used": False,
                "decision_source": decision_source,
                "parent_fallback_used": bool(parent_fallback),
                "actions_count": actions_count,
                "elapsed_seconds": float(elapsed_seconds),
                "execution_result": execution_result,
            },
        )
        context_name = (
            "trade_skill_context_audit.json"
            if phase == "trade"
            else "skill_context_audit.json"
        )
        self.scripted_runner._write_json(
            target_day / context_name,
            {
                "schema_version": "skill_context_audit.v1",
                "department": department,
                "phase": phase,
                "day": int(round_id),
                "ok": True,
                "derived_run": True,
                "decision_source": decision_source,
                "source_files": {
                    "state": str(target_day / f"{department}.json"),
                    "parent_action": str(source_action),
                },
                "missing_files": [],
            },
        )
        if phase == "decision":
            self.scripted_runner._write_json(
                target_day / f"{department}_communication.json",
                {
                    "schema_version": "enterprise_communication.v1",
                    "messages": [],
                    "reason": "Hybrid replay reuses actions without synthesizing Agent communications.",
                },
            )

    def _message(self, department: str, round_id: int, source: str) -> dict:
        return {
            "role": f"hybrid_replay_{department}",
            "content": (
                f"hybrid replay action generated for {self.enterprise_name}/"
                f"{department}/day{round_id}; source={source}"
            ),
        }
