"""Warehouse adapters tested with fakes (no cloud account needed)."""

from types import SimpleNamespace

import pytest

from gulliver.config import Connection
from gulliver.engines import get_engine
from gulliver.engines.base import EngineError, MissingDriver
from gulliver.engines.bigquery import TIB, BigQueryEngine
from gulliver.engines.postgres import estimate_from_plan
from gulliver.engines.snowflake import SnowflakeEngine, estimate_from_explain


def test_postgres_plan_estimate():
    plan = [{"Plan": {"Node Type": "Hash Join", "Plan Rows": 1200, "Total Cost": 4521.3, "Plans": [
        {"Node Type": "Seq Scan", "Relation Name": "events", "Schema": "public", "Plan Rows": 100000},
        {"Node Type": "Index Scan", "Relation Name": "users", "Plan Rows": 50, "Plan Width": 40},
    ]}}]
    est = estimate_from_plan(plan, lambda schema, rel: 8_000_000 if rel == "events" else None)
    assert est.rows == 1200
    assert est.bytes == 8_000_000 + 50 * 40
    assert est.accuracy == "heuristic"


def test_snowflake_explain_estimate():
    est = estimate_from_explain({"GlobalStats": {"partitionsTotal": 100, "partitionsAssigned": 5,
                                                 "bytesAssigned": 123456}})
    assert est.bytes == 123456 and est.accuracy == "upper_bound" and est.cost_usd is None
    assert any("95%" in n for n in est.notes)


def test_snowflake_cost_model():
    eng = SnowflakeEngine(Connection("sf", "snowflake", {"credits_per_hour": 2, "credit_usd": 3}), _conn=object())
    assert eng.cost_for(None, 3600) == pytest.approx(6.0)
    assert eng.cost_for(None, None) is None
    assert eng.sample_clause(0.01, 7, "system") == "SAMPLE SYSTEM (1) SEED (7)"


class FakeJob:
    def __init__(self, processed, tables=1, rows=None):
        self.total_bytes_processed = processed
        self.total_bytes_billed = processed
        self.referenced_tables = [object()] * tables
        self._rows = rows or []

    def result(self, timeout=None, page_size=None):
        return FakeResult(self._rows)


class FakeResult(list):
    schema = [SimpleNamespace(name="n")]


class FakeClient:
    def __init__(self):
        self.calls = []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        if job_config.get("dry_run"):
            return FakeJob(2 * TIB)
        return FakeJob(TIB // 2, rows=[(1,), (2,), (3,)])


def test_bigquery_dry_run_cost_and_cap():
    client = FakeClient()
    eng = BigQueryEngine(Connection("bq", "bigquery", {"project": "p"}), _client=client)
    est = eng.estimate("select 1")
    assert est.accuracy == "exact"
    assert est.cost_usd == pytest.approx(12.5)
    assert eng.max_bytes_for_cost(6.25) == TIB
    res = eng.execute("select n from t", preview_rows=2, max_bytes_billed=123)
    assert res.rows == 3 and len(res.preview) == 2 and res.truncated
    assert client.calls[-1][1]["maximum_bytes_billed"] >= 10 * 1024**2
    assert eng.sample_clause(0.03, 1, "system") == "TABLESAMPLE SYSTEM (3 PERCENT)"


def test_missing_drivers_have_install_hint():
    for engine, extra in (("postgres", "postgres"), ("bigquery", "bigquery"), ("snowflake", "snowflake")):
        params = {"dsn": "postgresql://x@localhost/db"} if engine == "postgres" else {}
        try:
            get_engine(Connection("x", engine, params)).close()
        except MissingDriver as exc:
            assert f"gulliver-mcp[{extra}]" in str(exc)
        except EngineError:
            pass  # driver installed but nothing to connect to: also fine here


def test_unknown_engine():
    with pytest.raises(EngineError):
        get_engine(Connection("x", "oracle"))
