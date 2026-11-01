"""Live PostgreSQL tests. They run when GULLIVER_TEST_PG_DSN points at a database you may write to
(CI starts a postgres service container). Skipped otherwise."""

from __future__ import annotations

import os

import pytest

DSN = os.environ.get("GULLIVER_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set GULLIVER_TEST_PG_DSN to run live Postgres tests")

SETUP = """
DROP TABLE IF EXISTS gv_events CASCADE;
DROP TABLE IF EXISTS gv_users CASCADE;
CREATE TABLE gv_users AS
  SELECT i AS user_id, (ARRAY['NL','BE','DE','FR'])[1 + i % 4] AS country FROM generate_series(0, 19999) i;
CREATE TABLE gv_events (event_id bigint, user_id bigint, amount numeric, ts timestamp) PARTITION BY RANGE (ts);
CREATE TABLE gv_events_2025 PARTITION OF gv_events FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE gv_events_2026 PARTITION OF gv_events FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
INSERT INTO gv_events
  SELECT i, i % 20000, (i % 100)::numeric, timestamp '2025-01-01' + (i % 600) * interval '1 day'
  FROM generate_series(1, 200000) i;
ANALYZE gv_users; ANALYZE gv_events;
"""

GOOD = ("select u.country, count(*) from gv_events e join gv_users u on e.user_id = u.user_id "
        "where e.ts >= '2026-01-01' group by 1")


@pytest.fixture(scope="module")
def pg_db():
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(SETUP)
    yield DSN


@pytest.fixture
def pg(pg_db, state):
    from gulliver.config import load_settings

    return load_settings(dsn=pg_db)


def test_inspect_sees_partitions_and_sizes(pg):
    from gulliver import core

    tables = {t["name"]: t for t in core.inspect(pg, limit=200)["tables"]}
    assert tables["gv_events"]["partitioned_by"] == "ts"
    assert tables["gv_events"]["bytes"] > 0
    assert tables["gv_events"]["rows"] == pytest.approx(200_000, rel=0.05)
    cols = {c["name"] for c in core.inspect(pg, table="gv_events")["table"]["columns"]}
    assert cols == {"event_id", "user_id", "amount", "ts"}


def test_missing_partition_filter_blocks(pg):
    from gulliver import core

    res = core.preflight(pg, "select count(*) from gv_events")
    assert res["status"] == "block"
    assert any(f["rule"] == "GV004" for f in res["lint"])


def test_rehearse_and_run(pg):
    from gulliver import core

    pre = core.preflight(pg, GOOD)
    assert pre["status"] == "ok"
    assert pre["estimate"]["rows"] >= 1
    reh = core.rehearse(pg, GOOD)
    assert reh["status"] in ("ok", "warn")
    assert len(reh["rungs"]) == 3
    run = core.run(pg, GOOD)
    assert run["status"] == "ok"
    assert run["actual"]["rows"] == 4
    assert sum(r["count"] for r in run["preview"]) > 0


def test_engine_session_is_read_only(pg_db):
    from gulliver.config import Connection
    from gulliver.engines.base import EngineError
    from gulliver.engines.postgres import PostgresEngine

    eng = PostgresEngine(Connection("pg", "postgres", {"dsn": pg_db}), read_only=True)
    try:
        with pytest.raises(EngineError):
            eng.execute("create table gv_should_fail as select 1 as x", preview_rows=0)
    finally:
        eng.close()


def test_sample_clause_runs(pg_db):
    from gulliver.config import Connection
    from gulliver.engines.postgres import PostgresEngine

    eng = PostgresEngine(Connection("pg", "postgres", {"dsn": pg_db}))
    try:
        clause = eng.sample_clause(0.1, 42, "bernoulli")
        res = eng.execute(f"select count(*) as n from (select * from gv_users {clause}) s", preview_rows=1)
        assert 1000 < res.preview[0]["n"] < 3000
    finally:
        eng.close()


def test_diff_and_checks_on_postgres(pg):
    from gulliver import features

    left = "select event_id, amount from gv_events where ts >= '2026-01-01'"
    right = ("select event_id, case when event_id = 500 then amount + 1 else amount end as amount "
             "from gv_events where ts >= '2026-01-01' and event_id <> 501")
    r = features.diff(pg, left, right, ["event_id"])
    assert r["differences"]["only_in_left"]["sample"] == ["501"]
    assert r["differences"]["changed"]["sample"] == ["500"]
    ok = features.check(pg, "gv_users", unique=["user_id"], accepted=["country=NL|BE|DE|FR"])
    assert ok["status"] == "ok"
    blocked = features.check(pg, "gv_events", unique=["event_id"])
    assert blocked["status"] == "block"  # partitioned: needs a where filter
    assert features.check(pg, "gv_events", where="ts >= '2026-01-01'", unique=["event_id"])["status"] == "ok"


def test_incremental_savings_on_postgres(pg):
    from gulliver import features

    r = features.incremental(pg, "select user_id, sum(amount) from gv_events group by 1", time_column="ts")
    assert r["strategy"] == "merge_recompute"
    assert r["savings"]["status"] == "ok"
    assert r["savings"]["rows_per_incremental_run"] < r["savings"]["source_rows"]
