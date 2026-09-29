"""Dynamic, enterprise-local communication schema and structural validation."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


VALID_PRIORITIES = {"low", "medium", "high", "critical"}


@dataclass
class CommunicationEntry:
    source_department: str
    to_department: str
    message: str
    topic: str = "general"
    priority: str = "medium"
    evidence_refs: List[str] = field(default_factory=list)
    round_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CommunicationValidationResult:
    source_department: str
    mode: str
    entries: List[CommunicationEntry] = field(default_factory=list)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    repairs: List[Dict[str, Any]] = field(default_factory=list)
    input_format: str = "empty"

    @property
    def ok(self) -> bool:
        return not self.issues or self.mode != "strict"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_department": self.source_department,
            "mode": self.mode,
            "ok": self.ok,
            "entries": [entry.to_dict() for entry in self.entries],
            "issues": self.issues,
            "repairs": self.repairs,
            "input_format": self.input_format,
        }


def _normalize_department(value: Any) -> str:
    department = str(value or "").strip().lower()
    if department.startswith("to_"):
        department = department[3:]
    return department


def _normalize_topic(value: Any) -> str:
    topic = str(value or "general").strip().lower().replace(" ", "_")
    return topic or "general"


def _normalize_evidence_refs(value: Any) -> Tuple[List[str], Optional[str]]:
    if value in (None, ""):
        return [], None
    values = value if isinstance(value, list) else [value]
    normalized = []
    for item in values:
        if not isinstance(item, (str, int, float)):
            return [], "evidence_refs must contain scalar references"
        text = str(item).strip()
        if text:
            normalized.append(text)
    return list(dict.fromkeys(normalized)), None


def _iter_raw_messages(payload: Any) -> Tuple[str, Iterable[Dict[str, Any]]]:
    if payload in (None, {}, []):
        return "empty", []
    if isinstance(payload, list):
        return "message_list", payload
    if not isinstance(payload, dict):
        return "invalid", []
    if isinstance(payload.get("messages"), list):
        return "message_list", payload["messages"]

    entries = []
    for target, message in payload.items():
        entries.append(
            {
                "to_department": target,
                "message": message,
            }
        )
    return "route_map", entries


def validate_communications(
    *,
    source_department: str,
    payload: Any,
    enabled_departments: Set[str],
    round_id: int,
    mode: str,
) -> CommunicationValidationResult:
    """Normalize structural communication fields against dynamic departments."""
    source_department = _normalize_department(source_department)
    enabled_departments = {
        _normalize_department(item)
        for item in enabled_departments
        if _normalize_department(item)
    }
    input_format, raw_messages = _iter_raw_messages(payload)
    result = CommunicationValidationResult(
        source_department=source_department,
        mode=mode,
        input_format=input_format,
    )

    if input_format == "invalid":
        result.issues.append(
            {
                "code": "invalid_payload_type",
                "message": "communications must be a route map or message list",
            }
        )
        return result

    for index, item in enumerate(raw_messages):
        if not isinstance(item, dict):
            result.issues.append(
                {
                    "code": "invalid_message_type",
                    "entry_index": index,
                }
            )
            continue

        target = _normalize_department(
            item.get("to_department")
            or item.get("target_department")
            or item.get("route_key")
            or item.get("target")
            or item.get("to")
        )
        message = str(item.get("message") or "").strip()
        if not target and not message:
            result.repairs.append(
                {
                    "code": "drop_empty_entry",
                    "entry_index": index,
                }
            )
            continue
        if target not in enabled_departments:
            result.issues.append(
                {
                    "code": "invalid_target",
                    "entry_index": index,
                    "target": target,
                    "enabled_departments": sorted(enabled_departments),
                }
            )
            continue
        if target == source_department:
            result.issues.append(
                {
                    "code": "self_route",
                    "entry_index": index,
                    "target": target,
                }
            )
            continue
        if not message:
            result.issues.append(
                {
                    "code": "empty_message",
                    "entry_index": index,
                    "target": target,
                }
            )
            continue

        priority = str(item.get("priority") or "medium").strip().lower()
        if priority not in VALID_PRIORITIES:
            result.issues.append(
                {
                    "code": "invalid_priority",
                    "entry_index": index,
                    "priority": priority,
                    "allowed_priorities": sorted(VALID_PRIORITIES),
                }
            )
            continue

        evidence_refs, evidence_error = _normalize_evidence_refs(
            item.get("evidence_refs", item.get("evidence_ref"))
        )
        if evidence_error:
            result.issues.append(
                {
                    "code": "invalid_evidence_refs",
                    "entry_index": index,
                    "detail": evidence_error,
                }
            )
            continue

        raw_round_id = item.get("round_id", round_id)
        try:
            normalized_round_id = int(raw_round_id)
        except (TypeError, ValueError):
            result.issues.append(
                {
                    "code": "invalid_round_id",
                    "entry_index": index,
                    "round_id": raw_round_id,
                }
            )
            continue
        if normalized_round_id != round_id:
            result.issues.append(
                {
                    "code": "round_mismatch",
                    "entry_index": index,
                    "round_id": normalized_round_id,
                    "expected_round_id": round_id,
                }
            )
            continue

        result.entries.append(
            CommunicationEntry(
                source_department=source_department,
                to_department=target,
                message=message,
                topic=_normalize_topic(item.get("topic")),
                priority=priority,
                evidence_refs=evidence_refs,
                round_id=normalized_round_id,
            )
        )

    return result


def deduplicate_entries(
    entries: Iterable[CommunicationEntry],
) -> Tuple[List[CommunicationEntry], List[Dict[str, Any]]]:
    unique = []
    duplicates = []
    seen = set()
    for entry in entries:
        key = (
            entry.source_department,
            entry.to_department,
            entry.topic,
            entry.priority,
            entry.message,
            tuple(entry.evidence_refs),
            entry.round_id,
        )
        if key in seen:
            duplicates.append(entry.to_dict())
            continue
        seen.add(key)
        unique.append(entry)
    return unique, duplicates

