"""PostgreSQL mirror repository for optional external SQL storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from core.integration_contracts import SimulationEvent
from persistence.sql_projection_tables import (
    ENTERPRISE_DAILY_METRICS_TABLE,
    ORDER_LIFECYCLE_ORDERS_TABLE,
    PHYSICAL_PROJECTION_TABLES,
    TOPOLOGY_EDGES_TABLE,
    TOPOLOGY_NODES_TABLE,
    build_physical_projection_rows,
)


POSTGRES_MIRROR_SCHEMA_VERSION = "postgres_mirror.v1"


def _json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _json_load_any(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _row_payload(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return _json_load_any(row.get("payload"))
    if isinstance(row, (list, tuple)) and row:
        return _json_load_any(row[0])
    return {}


def _split_sql_statements(sql_text: str) -> Iterable[str]:
    for statement in sql_text.split(";"):
        statement = statement.strip()
        if statement:
            yield statement


class PostgresMirrorRepository:
    """
    Optional PostgreSQL mirror repository.

    It mirrors the SQLite repository semantics but remains a secondary
    projection store. The filesystem archive is still the authoritative
    source unless a future postgres_authoritative profile explicitly changes
    that contract.
    """

    def __init__(
        self,
        dsn: str,
        *,
        connect: Optional[Callable[[str], Any]] = None,
        initialize: bool = True,
        schema_path: Optional[Path] = None,
    ):
        self.dsn = str(dsn)
        self._connect_factory = connect or self._default_connect
        self.schema_path = schema_path or (
            Path(__file__).resolve().parent / "postgres_projection_schema.sql"
        )
        if initialize:
            self.initialize()

    @staticmethod
    def _default_connect(dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL mirror requires psycopg. Install psycopg or unset "
                "SIMULATION_POSTGRES_DSN to use SQLite mirror."
            ) from exc
        return psycopg.connect(dsn, row_factory=dict_row)

    def _connect(self):
        return self._connect_factory(self.dsn)

    def initialize(self) -> None:
        with self._connect() as connection:
            for statement in _split_sql_statements(_CORE_SCHEMA_SQL):
                connection.execute(statement)
            if self.schema_path.exists():
                for statement in _split_sql_statements(
                    self.schema_path.read_text(encoding="utf-8")
                ):
                    connection.execute(statement)

    def create_run(self, run: Dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(run_id, payload, updated_at)
                VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (run_id, _json_dump(run)),
            )

    def update_run(self, run_id: str, changes: Dict[str, Any]) -> None:
        current = self.get_run(run_id) or {"run_id": run_id}
        current.update(changes or {})
        self.create_run(current)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT payload FROM runs WHERE run_id = %s",
                (run_id,),
            )
            payload = _row_payload(cursor.fetchone())
        return payload or None

    def list_runs(self, limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
        query = "SELECT payload FROM runs ORDER BY updated_at DESC, run_id DESC"
        params = []
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            payload = _row_payload(row)
            if payload:
                yield payload

    def append(self, event: SimulationEvent) -> None:
        event.assert_valid()
        payload = event.to_dict()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(
                    event_id, run_id, enterprise_id, day, event_type, payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (event_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
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
        clauses = ["run_id = %s"]
        params = [run_id]
        if enterprise_id is not None:
            clauses.append("enterprise_id = %s")
            params.append(enterprise_id)
        if day is not None:
            clauses.append("day = %s")
            params.append(int(day))
        query = (
            "SELECT payload FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY day, event_id"
        )
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            payload = _row_payload(row)
            if payload:
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
                INSERT INTO projections(projection_name, key_json, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (projection_name, key_json)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
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
            cursor = connection.execute(
                """
                SELECT payload FROM projections
                WHERE projection_name = %s AND key_json = %s
                """,
                (projection_name, _json_dump(key)),
            )
            payload = _row_payload(cursor.fetchone())
        return payload or None

    def list_projection_records(
        self,
        projection_name: str,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        query = """
            SELECT key_json, payload FROM projections
            WHERE projection_name = %s
            ORDER BY updated_at DESC, key_json DESC
        """
        params = [projection_name]
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            if isinstance(row, dict):
                key_json = row.get("key_json")
                payload = row.get("payload")
            else:
                key_json, payload = row[0], row[1]
            yield {
                "projection_name": projection_name,
                "key": _json_load_any(key_json),
                "payload": _json_load_any(payload),
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
            clauses.append("run_id = %s")
            params.append(str(run_id))
        if round_id is not None:
            clauses.append("round_id = %s")
            params.append(int(round_id))
        query = f"SELECT * FROM {table_name}"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY run_id, round_id"
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            payload = dict(row) if isinstance(row, dict) else {}
            if payload:
                yield payload

    def save_version(self, version: Dict[str, Any]) -> None:
        version_id = str(version.get("version_id") or "")
        if not version_id:
            raise ValueError("version_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO config_versions(version_id, payload, updated_at)
                VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (version_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (version_id, _json_dump(version)),
            )

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT payload FROM config_versions WHERE version_id = %s",
                (version_id,),
            )
            payload = _row_payload(cursor.fetchone())
        return payload or None

    def create_job(self, job: Dict[str, Any]) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise ValueError("job_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(job_id, payload, updated_at)
                VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (job_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
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
                "DELETE FROM jobs WHERE job_id = %s",
                (job_id,),
            )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = %s",
                (job_id,),
            )
            payload = _row_payload(cursor.fetchone())
        return payload or None

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        query = "SELECT payload FROM jobs ORDER BY updated_at DESC, job_id DESC"
        params = []
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, int(limit)))
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            payload = _row_payload(row)
            if not payload:
                continue
            if status is not None and str(payload.get("status") or "") != str(status):
                continue
            yield payload

    def _materialize_projection(
        self,
        connection: Any,
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
                f"DELETE FROM {table_name} WHERE run_id = %s AND scenario_id = %s AND round_id = %s",
                (identity["run_id"], identity["scenario_id"], identity["round_id"]),
            )
            for row in rows:
                self._insert_physical_projection_row(connection, table_name, row)

    def _insert_physical_projection_row(
        self,
        connection: Any,
        table_name: str,
        row: Dict[str, Any],
    ) -> None:
        if table_name == ORDER_LIFECYCLE_ORDERS_TABLE:
            connection.execute(
                """
                INSERT INTO order_lifecycle_orders(
                    run_id, scenario_id, round_id, exchange_id, order_id,
                    seller_id, buyer_id, product_id, quantity, value, status,
                    planned_delivery_round, payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id, round_id, order_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
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
                INSERT INTO topology_nodes(
                    run_id, scenario_id, round_id, enterprise_id, name, tier,
                    role_tags, payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id, round_id, enterprise_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["enterprise_id"],
                    row["name"],
                    row["tier"],
                    json.dumps(row["role_tags"], ensure_ascii=False),
                    _json_dump(row["payload"]),
                ),
            )
        elif table_name == TOPOLOGY_EDGES_TABLE:
            connection.execute(
                """
                INSERT INTO topology_edges(
                    run_id, scenario_id, round_id, supplier_id, customer_id,
                    valid, compatible_products, payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id, round_id, supplier_id, customer_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (
                    row["run_id"],
                    row["scenario_id"],
                    row["round_id"],
                    row["supplier_id"],
                    row["customer_id"],
                    bool(row["valid"]),
                    json.dumps(row["compatible_products"], ensure_ascii=False),
                    _json_dump(row["payload"]),
                ),
            )
        elif table_name == ENTERPRISE_DAILY_METRICS_TABLE:
            connection.execute(
                """
                INSERT INTO enterprise_daily_metrics(
                    run_id, scenario_id, round_id, enterprise_id, cash,
                    net_profit, bought_order_count, sold_order_count,
                    bought_quantity, sold_quantity, bought_value, sold_value,
                    payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id, round_id, enterprise_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP
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


_CORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    enterprise_id TEXT,
    day INTEGER,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_run_enterprise_day
    ON events(run_id, enterprise_id, day);
CREATE TABLE IF NOT EXISTS projections (
    projection_name TEXT NOT NULL,
    key_json TEXT NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (projection_name, key_json)
);
CREATE TABLE IF NOT EXISTS config_versions (
    version_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
"""
