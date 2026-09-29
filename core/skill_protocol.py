"""Skill context filtering, legacy output adaptation, and audit contracts."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.integration_contracts import AgentOutputEnvelope


SCENARIO_POLICY_RULES = {
    "cobweb_model": {
        "mode": "cobweb",
        "departments": {"analyst", "production", "sales", "procurement"},
    },
    "shared_resource": {
        "mode": "shared_resource",
        "departments": {
            "analyst",
            "production",
            "sales",
            "inventory",
            "finance",
        },
    },
    "herding_signal": {
        "mode": "herding",
        "departments": {
            "analyst",
            "production",
            "sales",
            "inventory",
            "finance",
        },
    },
}


@dataclass
class ContextAudit:
    department: str
    source_files: Dict[str, str]
    active_modes: Dict[str, bool] = field(default_factory=dict)
    visible_policy_names: List[str] = field(default_factory=list)
    disallowed_policy_names: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.disallowed_policy_names

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


@dataclass
class SkillExecutionAudit:
    schema_version: str
    run_id: str
    scenario_id: str
    enterprise_id: str
    department: str
    phase: str
    day: int
    context_validation_mode: str
    validation_mode: str
    attempts: int
    success: bool
    fallback_used: bool
    elapsed_seconds: float
    output_file: str
    raw_messages_artifacts: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    context_audit: Dict[str, Any] = field(default_factory=dict)
    normalized_envelope: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def audit_policy_context(
    policy_context: Dict[str, Any],
    department: str,
) -> ContextAudit:
    """Report scenario-specific fields that should not be visible to a department."""
    department = str(department or "").lower()
    policy_context = _safe_dict(policy_context)
    active_modes = {
        str(key): bool(value)
        for key, value in _safe_dict(policy_context.get("active_modes")).items()
    }
    relevant_policies = _safe_dict(policy_context.get("relevant_policies"))
    disallowed = []

    for policy_name, rule in SCENARIO_POLICY_RULES.items():
        if policy_name not in relevant_policies:
            continue
        mode_enabled = bool(active_modes.get(rule["mode"]))
        department_allowed = department in rule["departments"]
        if not mode_enabled or not department_allowed:
            disallowed.append(policy_name)

    return ContextAudit(
        department=department,
        source_files={},
        active_modes=active_modes,
        visible_policy_names=sorted(relevant_policies),
        disallowed_policy_names=sorted(disallowed),
    )


def filter_policy_context(
    policy_context: Dict[str, Any],
    department: str,
) -> Dict[str, Any]:
    """Return a copy with scenario fields outside the allowlist removed."""
    policy_context = dict(_safe_dict(policy_context))
    relevant_policies = dict(_safe_dict(policy_context.get("relevant_policies")))
    audit = audit_policy_context(policy_context, department)
    for policy_name in audit.disallowed_policy_names:
        relevant_policies.pop(policy_name, None)
    policy_context["relevant_policies"] = relevant_policies
    return policy_context


def audit_context_files(
    *,
    department: str,
    state_path: str,
    blackboard_path: str,
    trade_decision_card_path: Optional[str],
    history_projection_path: Optional[str] = None,
    read_json: Any,
) -> ContextAudit:
    """Inspect generated context files without mutating current runtime inputs."""
    source_files = {
        "state": state_path,
        "blackboard": blackboard_path,
    }
    if trade_decision_card_path:
        source_files["trade_decision_card"] = trade_decision_card_path
    if history_projection_path:
        source_files["history_projection"] = history_projection_path

    missing_files = [
        name for name, path in source_files.items()
        if not Path(path).exists()
    ]
    state_payload = read_json(Path(state_path), {})
    blackboard_payload = read_json(Path(blackboard_path), {})
    trade_payload = (
        read_json(Path(trade_decision_card_path), {})
        if trade_decision_card_path
        else {}
    )
    policy_contexts = [
        _safe_dict(state_payload.get("policy_context")),
        _safe_dict(blackboard_payload.get("policy_context")),
        _safe_dict(
            (_safe_dict(blackboard_payload.get("policy_context_by_department")))
            .get(department)
        ),
        _safe_dict(trade_payload.get("policy_context")),
    ]
    audits = [
        audit_policy_context(policy_context, department)
        for policy_context in policy_contexts
        if policy_context
    ]
    active_modes = {}
    visible_policy_names = set()
    disallowed_policy_names = set()
    for item in audits:
        active_modes.update(item.active_modes)
        visible_policy_names.update(item.visible_policy_names)
        disallowed_policy_names.update(item.disallowed_policy_names)

    audit = ContextAudit(
        department=str(department or "").lower(),
        source_files={},
        active_modes=active_modes,
        visible_policy_names=sorted(visible_policy_names),
        disallowed_policy_names=sorted(disallowed_policy_names),
    )
    audit.source_files = source_files
    audit.missing_files = missing_files
    return audit


def _extract_evidence_refs(actions: Iterable[Dict[str, Any]]) -> List[str]:
    refs = []
    seen = set()
    for item in actions:
        for key in ("evidence_ref", "evidence_refs"):
            value = item.get(key)
            values = value if isinstance(value, list) else [value]
            for ref in values:
                if ref in (None, ""):
                    continue
                normalized = str(ref)
                if normalized not in seen:
                    seen.add(normalized)
                    refs.append(normalized)
    return refs


def adapt_legacy_actions(
    *,
    run_id: str,
    enterprise_id: str,
    department: str,
    day: int,
    actions: Any,
    output_file: str,
    fallback_used: bool = False,
    communications: Any = None,
) -> AgentOutputEnvelope:
    normalized_actions = actions if isinstance(actions, list) else []
    normalized_communications = (
        communications if isinstance(communications, list) else []
    )
    reasons = [
        str(item.get("action_reason"))
        for item in normalized_actions
        if isinstance(item, dict) and item.get("action_reason")
    ]
    envelope = AgentOutputEnvelope(
        schema_version="1.0",
        run_id=run_id,
        enterprise_id=enterprise_id,
        department=department,
        day=day,
        status="fallback" if fallback_used else "ok",
        analysis_summary="; ".join(reasons),
        actions=[] if fallback_used else normalized_actions,
        communications=normalized_communications,
        evidence_refs=_extract_evidence_refs(
            item for item in normalized_actions if isinstance(item, dict)
        ),
        warnings=(
            ["Legacy action_pass fallback was executed."]
            if fallback_used
            else []
        ),
        raw_artifact=output_file,
    )
    return envelope


def adapt_legacy_analysis(
    *,
    run_id: str,
    enterprise_id: str,
    day: int,
    analysis: Any,
    output_file: str,
) -> AgentOutputEnvelope:
    analysis = analysis if isinstance(analysis, dict) else {}
    summary = (
        analysis.get("analysis_summary")
        or analysis.get("summary")
        or analysis.get("overall_assessment")
        or ""
    )
    evidence_refs = analysis.get("evidence_refs") or []
    if not isinstance(evidence_refs, list):
        evidence_refs = [str(evidence_refs)]
    return AgentOutputEnvelope(
        schema_version="1.0",
        run_id=run_id,
        enterprise_id=enterprise_id,
        department="analyst",
        day=day,
        analysis_summary=str(summary),
        evidence_refs=[str(item) for item in evidence_refs if item not in (None, "")],
        raw_artifact=output_file,
    )
