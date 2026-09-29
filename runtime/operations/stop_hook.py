"""Worker-side helper for operations stop requests."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .service import OperationsService


class OperationsStopHook:
    """
    Convert repository stop requests into complete-round stop decisions.

    The hook is intentionally side-effect free until `seal_if_requested()` is
    called after a round has been fully written.
    """

    def __init__(self, service: OperationsService, job_id: str):
        self.service = service
        self.job_id = job_id

    def build_stop_reason(self, *, completed_round: int) -> Optional[Dict[str, Any]]:
        try:
            job = self.service.get_job(self.job_id)
        except ValueError:
            return None
        if job.get("status") != "stop_requested":
            return None
        stop_request = job.get("stop_request") or {}
        completed_steps = int(completed_round) + 1
        return {
            "type": "operations_stop_requested",
            "message": stop_request.get("reason") or "Operations stop requested",
            "policy": stop_request.get("policy") or "seal_last_complete_round",
            "requested_at": stop_request.get("requested_at"),
            "requested_by": stop_request.get("requested_by"),
            "completed_steps": completed_steps,
            "last_complete_round": int(completed_round),
        }

    def seal_if_requested(self, *, completed_round: int) -> Optional[Dict[str, Any]]:
        stop_reason = self.build_stop_reason(completed_round=completed_round)
        if not stop_reason:
            return None
        self.service.mark_stopped(
            self.job_id,
            completed_steps=stop_reason["completed_steps"],
            last_complete_round=stop_reason["last_complete_round"],
            reason=stop_reason["message"],
        )
        return stop_reason
