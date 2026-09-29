"""SQLite-backed mirror repository for integration projections and events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from core.integration_contracts import SimulationEvent
from persistence.sql_projection_tables import (
    ENTERPRISE_DAILY_METRICS_TABLE,
    ORDER_LIFECYCLE_ORDERS_TABLE,
    PHYSICAL_PROJECTION_TABLES,
    TOPOLOGY_EDGES_TABLE,
    TOPOLOGY_NODES_TABLE,
    build_physical_projection_rows,
)


SQL_MIRROR_SCHEMA_VERSION = "sql_mirror.v1"


class SQLiteMirrorWriteError(RuntimeError):
    """Raised when the configured SQLite mirror cannot be written."""


def _json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _json_load(value: str) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


class SQLiteMirrorRepository:
    """
    Storage-neutral repository implementation backed by SQLite.

    This is a mirror/checkpoint repository, not the authoritative simulation
    state. It is intentionally JSON-first so it can mirror filesystem run
    artifacts before a final PostgreSQL schema is selected.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(str(self.db_path), timeout=30.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            return connection
        except sqlite3.OperationalError as exc:
            raise self._write_error(exc) from exc

    def _write_error(self, exc: Exception) -> SQLiteMirrorWriteError:
        return SQLiteMirrorWriteError(
            "SQLite mirror database is not writable. "
            f"path={self.db_path}; parent={self.db_path.parent}; "
            "please ensure the service user can write the database file and "
            "its parent directory, or set SIMULATION_SQL_MIRROR_PATH / "
            "SIMULATION_OPERATIONS_SQLITE_PATH to a writable location. "
            f"original_error={exc}"
        )

    def _assert_writable(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS __write_probe__(id INTEGER)")
            connection.execute("INSERT INTO __write_probe__(id) VALUES (1)")
            connection.execute("DELETE FROM __write_probe__")
        except sqlite3.OperationalError as exc:
            raise self._write_error(exc) from exc

    def _initialize(self) -> None:
        with self._connect() as connection:
            self._assert_writable(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    enterprise_id TEXT,
                    day INTEGER,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_enterprise_day
                    ON events(run_id, enterprise_id, day);
                CREATE TABLE IF NOT EXISTS projections (
                    projection_name TEXT NOT NULL,
                    key_json TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (projection_name, key_json)
                );
                CREATE TABLE IF NOT EXISTS config_versions (
                    version_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS order_lifecycle_orders (
                    run_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    exchange_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    seller_id TEXT,
                    buyer_id TEXT,
                    product_id TEXT,
                    quantity REAL,
                    value REAL,
                    status TEXT,
                    planned_delivery_round INTEGER,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, round_id, order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_order_lifecycle_orders_run_round
                    ON order_lifecycle_orders(run_id, round_id);
                CREATE TABLE IF NOT EXISTS topology_nodes (
                    run_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    enterprise_id TEXT NOT NULL,
                    name TEXT,
                    tier INTEGER,
                    role_tags_json TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, round_id, enterprise_id)
                );
                CREATE TABLE IF NOT EXISTS topology_edges (
                    run_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    supplier_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    valid INTEGER NOT NULL,
                    compatible_products_json TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, round_id, supplier_id, customer_id)
                );
                CREATE TABLE IF NOT EXISTS enterprise_daily_metrics (
                    run_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    enterprise_id TEXT NOT NULL,
                    cash REAL,
                    net_profit REAL,
                    bought_order_count INTEGER,
                    sold_order_count INTEGER,
                    bought_quantity REAL,
                    sold_quantity REAL,
                    bought_value REAL,
                    sold_value REAL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, round_id, enterprise_id)
                );
                """
            )

    def create_run(self, run: Dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs(run_id, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (run_id, _json_dump(run)),
            )

    def update_run(self, run_id: str, changes: Dict[str, Any]) -> None:
        current = self.get_run(run_id) or {"run_id": run_id}
        current.update(changes or {})
        self.create_run(current)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _json_load(row["payload"]) if row else None

    def list_runs(self, limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
        query = "SELECT payload FROM runs ORDER BY updated_at DESC, run_id DESC"
        params = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            yield _json_load(row["payload"])

    def append(self, event: SimulationEvent) -> None:
        event.assert_valid()
        payload = event.to_dict()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO events(
                    event_id, run_id, enterprise_id, day, event_type, payload, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    payload["event_id"],
                    payload["run_id"],
                    payload.get("enterprise_id"),
                    payload["day"],
                    payload["event_type"],
                    _json_dump(payload),
                ),
            )

    def list_events(
        self,
        run_id: str,
        enterprise_id: Optional[str] = None,
        day: Optional[int] = None,
    ) -> Iterable[SimulationEvent]:
        clauses = ["run_id = ?"]
        params = [run_id]
        if enterprise_id is not None:
            clauses.append("enterprise_id = ?")
            params.append(enterprise_id)
        if day is not None:
            clauses.append("day = ?")
            params.append(int(day))
        query = (
            "SELECT payload FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY day, event_id"
        )
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            payload = _json_load(row["payload"])
            yield SimulationEvent(**payload)

    def upsert_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        if not projection_name:
            raise ValueError("projection_name is required")
        key_json = _json_dump(key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO projections(
                    projection_name, key_json, payload, updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (projection_name, key_json, _json_dump(payload)),
            )
            self._materialize_projection(connection, projection_name, key, payload)

    def get_projection(
        self,
        projection_name: str,
        key: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM projections
                WHERE projection_name = ? AND key_json = ?
                """,
                (projection_name, _json_dump(key)),
            ).fetchone()
        return _json_load(row["payload"]) if row else None

    def list_projection_records(
        self,
        projection_name: str,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        if not projection_name:
            return
        query = """
            SELECT key_json, payload FROM projections
            WHERE projection_name = ?
            ORDER BY updated_at DESC, key_json DESC
        """
        params = [projection_name]
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            yield {
                "projection_name": projection_name,
                "key": _json_load(row["key_json"]),
                "payload": _json_load(row["payload"]),
            }

    def list_physical_projection_rows(
        self,
        table_name: str,
        run_id: Optional[str] = None,
        round_id: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        if table_name not in PHYSICAL_PROJECTION_TABLES:
            raise ValueError(f"Unsupported physical projection table: {table_name}")
        clauses = []
        params = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if round_id is not None:
            clauses.append("round_id = ?")
            params.append(int(round_id))
        query = f"SELECT * FROM {table_name}"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY run_id, round_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            payload = dict(row)
            payload["payload"] = _json_load(payload.get("payload", ""))
            if "role_tags_json" in payload:
                payload["role_tags"] = _json_load(payload.pop("role_tags_json")).get(
                    "items",
                    [],
                )
            if "compatible_products_json" in payload:
                payload["compatible_products"] = _json_load(
                    payload.pop("compatible_products_json")
                ).get("items", [])
            yield payload

    def _materialize_projection(
        self,
        connection: sqlite3.Connection,
        projection_name: str,
        key: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        rows_by_table = build_physical_projection_rows(projection_name, key, payload)
        if not rows_by_table:
            return
        identity = {
            "run_id": str(payload.get("run_id") or key.get("run_id") or ""),
            "scenario_id": str(payload.get("scenario_id") or key.get("scenario_id") or ""),
            "round_id": int(payload.get("round_id", key.get("round_id", 0))),
        }
        for table_name, rows in rows_by_table.items():
            connection.execute(
                f"DELETE FROM {table_name} WHERE run_id = ? AND scenario_id = ? AND round_id = ?",
                (identity["run_id"], identity["scenario_id"], identity["round_id"]),
            )
            for row in rows:
                self._insert_physical_projection_row(connection, table_name, row)

    def _insert_physical_projection_row(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        row: Dict[str, Any],
    ) -> None:
        if table_name == ORDER_LIFECYCLE_ORDERS_TABLE:
            connection.execute(
                """
                INSERT OR REPLACE INTO order_lifecycle_orders(
                    run_id, scenario_id, round_id, exchange_id, order_id,
                    seller_id, buyer_id, product_id, quantity, value, status,
                    planned_delivery_round, payload, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["exchange_id"],
                    row["order_id"],
                    row["seller_id"],
                    row["buyer_id"],
                    row["product_id"],
                    row["quantity"],
                    row["value"],
                    row["status"],
                    row["planned_delivery_round"],
                    _json_dump(row["payload"]),
                ),
            )
        elif table_name == TOPOLOGY_NODES_TABLE:
            connection.execute(
                """
                INSERT OR REPLACE INTO topology_nodes(
                    run_id, scenario_id, round_id, enterprise_id, name, tier,
                    role_tags_json, payload, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["enterprise_id"],
                    row["name"],
                    row["tier"],
                    _json_dump({"items": row["role_tags"]}),
                    _json_dump(row["payload"]),
                ),
            )
        elif table_name == TOPOLOGY_EDGES_TABLE:
            connection.execute(
                """
                INSERT OR REPLACE INTO topology_edges(
                    run_id, scenario_id, round_id, supplier_id, customer_id,
                    valid, compatible_products_json, payload, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["supplier_id"],
                    row["customer_id"],
                    1 if row["valid"] else 0,
                    _json_dump({"items": row["compatible_products"]}),
                    _json_dump(row["payload"]),
                ),
            )
        elif table_name == ENTERPRISE_DAILY_METRICS_TABLE:
            connection.execute(
                """
                INSERT OR REPLACE INTO enterprise_daily_metrics(
                    run_id, scenario_id, round_id, enterprise_id, cash,
                    net_profit, bought_order_count, sold_order_count,
                    bought_quantity, sold_quantity, bought_value, sold_value,
                    payload, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["enterprise_id"],
                    row["cash"],
                    row["net_profit"],
                    row["bought_order_count"],
                    row["sold_order_count"],
                    row["bought_quantity"],
                    row["sold_quantity"],
                    row["bought_value"],
                    row["sold_value"],
                    _json_dump(row["payload"]),
                ),
            )

    def save_version(self, version: Dict[str, Any]) -> None:
        version_id = str(version.get("version_id") or "")
        if not version_id:
            raise ValueError("version_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO config_versions(version_id, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (version_id, _json_dump(version)),
            )

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM config_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        return _json_load(row["payload"]) if row else None

    def create_job(self, job: Dict[str, Any]) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise ValueError("job_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO jobs(job_id, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (job_id, _json_dump(job)),
            )

    def update_job(self, job_id: str, changes: Dict[str, Any]) -> None:
        current = self.get_job(job_id) or {"job_id": job_id}
        current.update(changes or {})
        self.create_job(current)

    def delete_job(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM jobs WHERE job_id = ?",
                (job_id,),
            )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _json_load(row["payload"]) if row else None

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        query = "SELECT payload FROM jobs ORDER BY updated_at DESC, job_id DESC"
        params = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            payload = _json_load(row["payload"])
            if status is not None and str(payload.get("status") or "") != str(status):
                continue
            yield payload


def mirror_history_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    enterprise_id: str,
    day: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "history_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "enterprise_id": enterprise_id,
            "day": int(day),
        },
        projection,
    )


def mirror_run_metrics_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    round_id: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "run_metrics_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
        },
        projection,
    )


def mirror_case_evaluation_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    case_id: str,
    round_id: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "case_evaluation_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "case_id": case_id,
            "round_id": int(round_id),
        },
        projection,
    )


def mirror_order_lifecycle_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    round_id: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "order_lifecycle_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
        },
        projection,
    )


def mirror_topology_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    round_id: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "topology_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
        },
        projection,
    )


def mirror_enterprise_daily_metrics_projection(
    repository: SQLiteMirrorRepository,
    *,
    run_id: str,
    scenario_id: str,
    round_id: int,
    projection: Dict[str, Any],
) -> None:
    repository.upsert_projection(
        "enterprise_daily_metrics_projection",
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "round_id": int(round_id),
        },
        projection,
    )
