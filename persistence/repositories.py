"""Repository protocols; implementations are introduced in later work packages."""

from typing import Any, Dict, Iterable, Optional, Protocol

from core.integration_contracts import SimulationEvent


class RunRepository(Protocol):
    def create_run(self, run: Dict[str, Any]) -> None: ...

    def update_run(self, run_id: str, changes: Dict[str, Any]) -> None: ...

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]: ...


class EventRepository(Protocol):
    def append(self, event: SimulationEvent) -> None: ...

    def list_events(
        self,
        run_id: str,
        enterprise_id: Optional[str] = None,
        day: Optional[int] = None,
    ) -> Iterable[SimulationEvent]: ...


class ProjectionRepository(Protocol):
    def upsert_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None: ...

    def get_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]: ...


class ConfigVersionRepository(Protocol):
    def save_version(self, version: Dict[str, Any]) -> None: ...

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]: ...


class JobRepository(Protocol):
    def create_job(self, job: Dict[str, Any]) -> None: ...

    def update_job(self, job_id: str, changes: Dict[str, Any]) -> None: ...

    def delete_job(self, job_id: str) -> None: ...

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]: ...

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]: ...
