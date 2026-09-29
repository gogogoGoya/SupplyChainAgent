"""Runtime helpers for optional SQL mirror writes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from config.project_paths import PROJECT_ROOT, resolve_project_path
from persistence.postgres_mirror import PostgresMirrorRepository
from persistence.sql_mirror import SQLiteMirrorRepository


SQL_MIRROR_PATH_ENV = "SIMULATION_SQL_MIRROR_PATH"
POSTGRES_DSN_ENV = "SIMULATION_POSTGRES_DSN"
SQL_MIRROR_DISABLED_ENV = "SIMULATION_SQL_MIRROR_DISABLED"
DEFAULT_SQL_MIRROR_PATH = (
    PROJECT_ROOT
    / "ccAgent"
    / "CCSDKAgent"
    / "workspace_jobs"
    / "_operations"
    / "supplychain_integrated.sqlite"
)
SQL_MIRROR_STORAGE_PROFILES = {"postgres_mirror", "postgres_checkpoint"}


def _env_flag_enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_default_sqlite_mirror_path() -> Path:
    return resolve_project_path(
        os.getenv(SQL_MIRROR_PATH_ENV),
        default=DEFAULT_SQL_MIRROR_PATH,
        relative_to=PROJECT_ROOT,
    )


def sql_mirror_enabled(profiles: Dict[str, Any]) -> bool:
    if _env_flag_enabled(os.getenv(SQL_MIRROR_DISABLED_ENV)):
        return False
    storage_profile = (
        (((profiles or {}).get("infrastructure") or {}).get("storage") or {})
        .get("profile")
    )
    return storage_profile in SQL_MIRROR_STORAGE_PROFILES


def get_sql_mirror_repository(
    profiles: Dict[str, Any],
    postgres_connect: Optional[Callable[[str], Any]] = None,
) -> Optional[Any]:
    if not sql_mirror_enabled(profiles):
        return None
    postgres_dsn = os.getenv(POSTGRES_DSN_ENV)
    if postgres_dsn:
        return PostgresMirrorRepository(
            postgres_dsn,
            connect=postgres_connect,
        )
    return SQLiteMirrorRepository(get_default_sqlite_mirror_path())


def _repository_locator(repository: Any) -> str:
    if hasattr(repository, "dsn"):
        return str(repository.dsn)
    if hasattr(repository, "db_path"):
        return str(repository.db_path)
    return "sql_mirror"


def mirror_run_metadata_if_enabled(
    profiles: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Optional[str]:
    repository = get_sql_mirror_repository(profiles)
    if repository is None:
        return None
    repository.create_run(metadata)
    return _repository_locator(repository)


def mirror_run_update_if_enabled(
    profiles: Dict[str, Any],
    run_id: str,
    changes: Dict[str, Any],
) -> Optional[str]:
    repository = get_sql_mirror_repository(profiles)
    if repository is None:
        return None
    repository.update_run(run_id, changes)
    return _repository_locator(repository)


def mirror_config_version_if_enabled(
    profiles: Dict[str, Any],
    *,
    version_id: str,
    scenario_id: str,
    scenario_config: Dict[str, Any],
    integration_profiles: Dict[str, Any],
) -> Optional[str]:
    repository = get_sql_mirror_repository(profiles)
    if repository is None:
        return None
    repository.save_version(
        {
            "version_id": version_id,
            "scenario_id": scenario_id,
            "scenario_config": scenario_config,
            "integration_profiles": integration_profiles,
        }
    )
    return _repository_locator(repository)


def mirror_job_if_enabled(
    profiles: Dict[str, Any],
    job: Dict[str, Any],
) -> Optional[str]:
    repository = get_sql_mirror_repository(profiles)
    if repository is None:
        return None
    repository.create_job(job)
    return _repository_locator(repository)


def mirror_job_update_if_enabled(
    profiles: Dict[str, Any],
    job_id: str,
    changes: Dict[str, Any],
) -> Optional[str]:
    repository = get_sql_mirror_repository(profiles)
    if repository is None:
        return None
    repository.update_job(job_id, changes)
    return _repository_locator(repository)
