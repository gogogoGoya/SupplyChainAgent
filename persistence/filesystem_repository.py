"""Filesystem-backed read adapter for existing run archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from core.integration_contracts import SimulationEvent


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class FilesystemRunArchiveRepository:
    """
    Read-side adapter over the current filesystem run archive.

    Existing simulation code remains responsible for writing files. This
    adapter gives parity checks and future dashboards a repository-shaped way
    to read the authoritative filesystem artifacts without changing the run
    archive layout.
    """

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)

    def create_run(self, run: Dict[str, Any]) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def update_run(self, run_id: str, changes: Dict[str, Any]) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        payload = _read_json(self.workspace_dir / "run_meta.json")
        if not payload:
            return None
        stored_run_id = str(payload.get("run_id") or "workspace_unarchived")
        return payload if stored_run_id == str(run_id) else None

    def list_runs(self, limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
        payload = _read_json(self.workspace_dir / "run_meta.json")
        if not payload:
            return
        if limit is not None and int(limit) <= 0:
            return
        yield payload

    def append(self, event: SimulationEvent) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def list_events(
        self,
        run_id: str,
        enterprise_id: Optional[str] = None,
        day: Optional[int] = None,
    ) -> Iterable[SimulationEvent]:
        return []

    def upsert_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def get_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        path = self._projection_path(projection_name, key)
        if path is None:
            return None
        payload = _read_json(path)
        return payload or None

    def list_projection_records(
        self,
        projection_name: str,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        count = 0
        for key, path in self._projection_paths(projection_name):
            payload = _read_json(path)
            if not payload:
                continue
            yield {
                "projection_name": projection_name,
                "key": key,
                "payload": payload,
            }
            count += 1
            if limit is not None and count >= max(0, int(limit)):
                break

    def save_version(self, version: Dict[str, Any]) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        return None

    def create_job(self, job: Dict[str, Any]) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def update_job(self, job_id: str, changes: Dict[str, Any]) -> None:
        raise NotImplementedError("filesystem archive writes stay on the legacy path")

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return None

    def _projection_path(
        self,
        projection_name: str,
        key: Dict[str, Any],
    ) -> Optional[Path]:
        if projection_name == "history_projection":
            day = _safe_int(key.get("day"))
            enterprise_id = str(key.get("enterprise_id") or "")
            if day < 0 or not enterprise_id:
                return None
            return (
                self.workspace_dir
                / "projections"
                / "history"
                / f"day{day}"
                / enterprise_id
                / "history_projection.json"
            )
        if projection_name == "run_metrics_projection":
            round_id = _safe_int(key.get("round_id"))
            if round_id < 0:
                return None
            return (
                self.workspace_dir
                / "projections"
                / "run_metrics"
                / f"day{round_id}"
                / "run_metrics_projection.json"
            )
        if projection_name == "case_evaluation_projection":
            round_id = _safe_int(key.get("round_id"))
            if round_id < 0:
                return None
            return (
                self.workspace_dir
                / "projections"
                / "case_evaluation"
                / f"day{round_id}"
                / "case_evaluation_projection.json"
            )
        if projection_name in {
            "order_lifecycle_projection",
            "topology_projection",
            "enterprise_daily_metrics_projection",
        }:
            round_id = _safe_int(key.get("round_id"))
            if round_id < 0:
                return None
            return (
                self.workspace_dir
                / "projections"
                / "multi_enterprise"
                / f"day{round_id}"
                / f"{projection_name}.json"
            )
        return None

    def _projection_paths(self, projection_name: str) -> Iterable[tuple]:
        if projection_name == "history_projection":
            root = self.workspace_dir / "projections" / "history"
            for path in sorted(root.glob("day*/*/history_projection.json")):
                day = _safe_int(path.parent.parent.name.replace("day", ""))
                enterprise_id = path.parent.name
                yield {
                    "enterprise_id": enterprise_id,
                    "day": day,
                }, path
        elif projection_name == "run_metrics_projection":
            root = self.workspace_dir / "projections" / "run_metrics"
            for path in sorted(root.glob("day*/run_metrics_projection.json")):
                yield {
                    "round_id": _safe_int(path.parent.name.replace("day", "")),
                }, path
        elif projection_name == "case_evaluation_projection":
            root = self.workspace_dir / "projections" / "case_evaluation"
            for path in sorted(root.glob("day*/case_evaluation_projection.json")):
                payload = _read_json(path)
                yield {
                    "case_id": payload.get("case_id"),
                    "round_id": _safe_int(path.parent.name.replace("day", "")),
                }, path
        elif projection_name in {
            "order_lifecycle_projection",
            "topology_projection",
            "enterprise_daily_metrics_projection",
        }:
            root = self.workspace_dir / "projections" / "multi_enterprise"
            for path in sorted(root.glob(f"day*/{projection_name}.json")):
                yield {
                    "round_id": _safe_int(path.parent.name.replace("day", "")),
                }, path
