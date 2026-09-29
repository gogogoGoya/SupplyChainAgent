"""Shared, storage-neutral contracts used by future integration work."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentOutputEnvelope:
    schema_version: str
    run_id: str
    enterprise_id: str
    department: str
    day: int
    status: str = "ok"
    analysis_summary: str = ""
    actions: List[Dict[str, Any]] = field(default_factory=list)
    communications: List[Dict[str, Any]] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_artifact: Optional[str] = None

    def validation_errors(self) -> List[str]:
        errors = []
        for field_name in (
            "schema_version",
            "run_id",
            "enterprise_id",
            "department",
        ):
            if not str(getattr(self, field_name, "") or "").strip():
                errors.append(f"{field_name} is required")
        if self.day < 0:
            errors.append("day must be >= 0")
        if self.status not in {"ok", "fallback", "error"}:
            errors.append("status must be ok, fallback, or error")
        if self.status == "fallback" and self.actions:
            errors.append("fallback envelopes cannot contain executable actions")
        if not all(isinstance(item, dict) for item in self.actions):
            errors.append("actions must contain objects")
        if not all(isinstance(item, dict) for item in self.communications):
            errors.append("communications must contain objects")
        return errors

    def assert_valid(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))

    def to_dict(self) -> Dict[str, Any]:
        self.assert_valid()
        return asdict(self)


@dataclass
class SimulationEvent:
    schema_version: str
    run_id: str
    scenario_id: str
    simulation_profile: str
    event_type: str
    day: int
    payload: Dict[str, Any]
    enterprise_id: Optional[str] = None
    department: Optional[str] = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=_utc_timestamp)
    source_artifact: Optional[str] = None

    def assert_valid(self) -> None:
        required = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "simulation_profile": self.simulation_profile,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
        }
        missing = [key for key, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"Missing event fields: {', '.join(missing)}")
        if self.day < 0:
            raise ValueError("day must be >= 0")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be an object")

    def to_dict(self) -> Dict[str, Any]:
        self.assert_valid()
        return asdict(self)


@dataclass
class MetricRecord:
    schema_version: str
    run_id: str
    scenario_id: str
    enterprise_id: str
    day: int
    metric_name: str
    value: Any
    dimensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        if not all(
            str(value or "").strip()
            for value in (
                self.schema_version,
                self.run_id,
                self.scenario_id,
                self.enterprise_id,
                self.metric_name,
            )
        ):
            raise ValueError("metric identity fields are required")
        if self.day < 0:
            raise ValueError("day must be >= 0")
        return asdict(self)

