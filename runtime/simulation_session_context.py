"""Per-run simulation session context for environment API calls."""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Optional


_SIMULATION_SESSION_ID: ContextVar[Optional[str]] = ContextVar(
    "simulation_session_id",
    default=None,
)


def get_simulation_session_id() -> Optional[str]:
    return _SIMULATION_SESSION_ID.get() or os.getenv("SIMULATION_SESSION_ID")


def set_simulation_session_id(session_id: Optional[str]):
    return _SIMULATION_SESSION_ID.set(session_id)


def reset_simulation_session_id(token) -> None:
    _SIMULATION_SESSION_ID.reset(token)
