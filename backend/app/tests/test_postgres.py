"""Tests for Postgres connector support.

No real Postgres / Neon is contacted:
- the connector's DB access is mocked (`_connect`), and
- the end-to-end /query test uses a local-safe fake connector that delegates to
  the seeded SQLite demo but reports the postgres dialect.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.connectors.base import BaseConnector
from app.db.connectors.postgres_connector import PostgresConnector
from app.db.connectors.sqlite_connector import SQLiteConnector
from app.main import app
from app.services import schema_service


# --- connection registry ---------------------------------------------------

@pytest.mark.parametrize("cid", ["demo", "demo_sqlite"])
def test_get_connector_sqlite_ids(cid):
    assert isinstance(schema_service.get_connector(cid), SQLiteConnector)


def test_get_connector_postgres_requires_database_url(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "postgres_database_url", "")
    with pytest.raises(schema_service.ConnectionUnavailableError):
        schema_service.get_connector("demo_postgres")


def test_get_connector_postgres_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@host/db")
    conn = schema_service.get_connector("demo_postgres")
    assert isinstance(conn, PostgresConnector)
    assert conn.dialect == "postgresql"
    assert conn.dsn == "postgresql://u:p@host/db"


def test_get_connector_postgres_from_postgres_database_url(monkeypatch):
    """POSTGRES_DATABASE_URL alone enables demo_postgres."""
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "postgres_database_url", "postgresql://u:p@neon/db")
    conn = schema_service.get_connector("demo_postgres")
    assert isinstance(conn, PostgresConnector)
    assert conn.dsn == "postgresql://u:p@neon/db"


def test_postgres_database_url_takes_precedence(monkeypatch):
    """POSTGRES_DATABASE_URL wins over DATABASE_URL."""
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@generic/db")
    monkeypatch.setattr(settings, "postgres_database_url", "postgresql://u:p@neon/db")
    assert settings.postgres_url == "postgresql://u:p@neon/db"
    assert schema_service.get_connector("demo_postgres").dsn == "postgresql://u:p@neon/db"


def test_get_connector_unknown_id():
    with pytest.raises(schema_service.UnknownConnectionError):
        schema_service.get_connector("nope")


# --- PostgresConnector with a mocked driver connection ---------------------

def _fake_conn(fetch_results, description=None):
    """Build a fake psycopg-style connection whose cursor returns canned rows."""
    cur = MagicMock()
    cur.fetchall.side_effect = list(fetch_results)
    cur.fetchone.side_effect = [(row,) for row in ()]  # overridden per-test if needed
    cur.description = description

    cur_cm = MagicMock()
    cur_cm.__enter__.return_value = cur
    cur_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cur_cm
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn, cur


def test_postgres_list_tables(monkeypatch):
    pg = PostgresConnector("postgresql://u:p@host/db")
    conn, _ = _fake_conn([[("customers",), ("orders",)]])
    monkeypatch.setattr(pg, "_connect", lambda: conn)
    assert pg.list_tables() == ["customers", "orders"]


def test_postgres_get_columns(monkeypatch):
    pg = PostgresConnector("postgresql://u:p@host/db")
    # First fetchall -> PK rows; second fetchall -> column rows.
    conn, _ = _fake_conn([
        [("id",)],
        [("id", "integer", "NO"), ("name", "text", "YES")],
    ])
    monkeypatch.setattr(pg, "_connect", lambda: conn)
    cols = pg.get_columns("customers")
    assert [c.name for c in cols] == ["id", "name"]
    assert cols[0].primary_key is True and cols[0].nullable is False
    assert cols[1].primary_key is False and cols[1].nullable is True


class _Col:
    def __init__(self, name):
        self.name = name


def test_postgres_run_select_builds_query_result(monkeypatch):
    pg = PostgresConnector("postgresql://u:p@host/db")
    conn, cur = _fake_conn(
        [[("Austin", 5)]],
        description=[_Col("city"), _Col("customer_count")],
    )
    monkeypatch.setattr(pg, "_connect", lambda: conn)

    result = pg.run_select("SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city", 5.0)
    assert result.columns == ["city", "customer_count"]
    assert result.rows == [{"city": "Austin", "customer_count": 5}]
    assert result.row_count == 1
    # Read-only transaction was requested and a statement timeout was set.
    assert conn.read_only is True
    assert any("statement_timeout" in str(c.args[0]) for c in cur.execute.call_args_list)


# --- end-to-end /query with connection_id demo_postgres (local-safe) -------

class _FakePostgresConnector(BaseConnector):
    """Reports postgres dialect but delegates to the seeded SQLite demo, so the
    full pipeline runs without a real Postgres server."""

    dialect = "postgresql"

    def __init__(self):
        self._sqlite = SQLiteConnector(settings.demo_db_path)

    def list_tables(self):
        return self._sqlite.list_tables()

    def get_columns(self, table):
        return self._sqlite.get_columns(table)

    def get_sample_rows(self, table, limit):
        return self._sqlite.get_sample_rows(table, limit)

    def count_rows(self, table):
        return self._sqlite.count_rows(table)

    def run_select(self, sql, timeout_seconds):
        return self._sqlite.run_select(sql, timeout_seconds)


def test_query_with_demo_postgres(monkeypatch):
    def fake_get_connector(connection_id):
        assert connection_id == "demo_postgres"
        return _FakePostgresConnector()

    monkeypatch.setattr(schema_service, "get_connector", fake_get_connector)

    resp = TestClient(app).post(
        "/query",
        json={"question": "Which city has the most customers?", "connection_id": "demo_postgres"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connection_id"] == "demo_postgres"
    assert body["dialect"] == "postgresql"
    assert body["intent"] == "city_most_customers"
    assert body["row_count"] > 0
    assert body["columns"] == ["city", "customer_count"]
    assert body["verification"]["verified"] is True


def test_connections_lists_postgres_availability(monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(settings, "postgres_database_url", "")
    monkeypatch.setattr(settings, "database_url", "")
    conns = {c["id"]: c for c in client.get("/connections").json()["connections"]}
    assert conns["demo_sqlite"]["available"] is True
    assert conns["demo_postgres"]["available"] is False

    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@host/db")
    conns = {c["id"]: c for c in client.get("/connections").json()["connections"]}
    assert conns["demo_postgres"]["available"] is True


def test_schema_inspection_for_demo_postgres(monkeypatch):
    monkeypatch.setattr(schema_service, "get_connector", lambda cid: _FakePostgresConnector())
    resp = TestClient(app).get("/connections/demo_postgres/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dialect"] == "postgresql"
    assert body["table_count"] == 6
    assert {t["name"] for t in body["tables"]} >= {"customers", "orders", "products"}
