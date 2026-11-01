"""gulliver_fix: every 'same' rewrite must really return the same rows."""

from __future__ import annotations

import asyncio
import json

import duckdb
import pytest

from gulliver import core
from gulliver.cli import main
from gulliver.fixer import fix, rewrite
from gulliver.mcp_server import build_server


def flat(sql: str) -> str:
    return " ".join(sql.split())


# -- rewrites per dialect ---------------------------------------------------------------
@pytest.mark.parametrize("dialect, sql, expect", [
    ("duckdb", "select a from t where date(ts) = '2024-01-01'", "ts >= '2024-01-01' AND ts < '2024-01-02'"),
    ("duckdb", "select a from t where ts::date = '2024-01-01'", "ts >= '2024-01-01' AND ts < '2024-01-02'"),
    ("duckdb", "select a from t where '2024-01-01' = date(ts)", "ts >= '2024-01-01' AND ts < '2024-01-02'"),
    ("duckdb", "select a from t where year(ts) = 2024", "ts >= '2024-01-01' AND ts < '2025-01-01'"),
    ("duckdb", "select a from t where date_trunc('month', ts) = '2024-12-01'", "ts >= '2024-12-01' AND ts < '2025-01-01'"),
    ("duckdb", "select a from t where date(ts) > '2024-01-01'", "ts >= '2024-01-02'"),
    ("duckdb", "select a from t where date(ts) <= '2024-02-29'", "ts < '2024-03-01'"),
    ("duckdb", "select a from t where date(ts) < '2024-01-01'", "ts < '2024-01-01'"),
    ("bigquery", "SELECT a FROM t WHERE DATE(ts) BETWEEN '2024-01-01' AND '2024-01-31'",
     "ts >= '2024-01-01' AND ts < '2024-02-01'"),
    ("bigquery", "SELECT a FROM t WHERE EXTRACT(YEAR FROM ts) = 2023", "ts >= '2023-01-01' AND ts < '2024-01-01'"),
    ("bigquery", "SELECT a FROM t WHERE DATE(ts) >= DATE '2024-01-01'", "ts >= '2024-01-01'"),
    ("snowflake", "select a from t where to_date(ts) = '2024-01-01'", "ts >= '2024-01-01' AND ts < '2024-01-02'"),
    ("postgres", "select a from t where date_trunc('day', ts) = '2024-01-01'", "ts >= '2024-01-01' AND ts < '2024-01-02'"),
])
def test_range_rewrites(dialect, sql, expect):
    out = rewrite(sql, dialect)
    assert expect in flat(out["fixed_sql"])
    assert out["same_result"] is True
    assert [c["rule"] for c in out["changes"]] == ["GV005"]


@pytest.mark.parametrize("sql, dialect", [
    ("select a from t where date_trunc('month', ts) = '2024-03-15'", "duckdb"),   # never true: leave it
    ("select a from t where date(ts) = something_else", "duckdb"),                # not a literal
    ("SELECT a FROM t WHERE DATE(ts, 'Europe/Amsterdam') = '2024-01-01'", "bigquery"),  # time zone argument
    ("select a from t where date(ts) = '2024-01-01 10:00'", "duckdb"),             # not a clean day literal
    ("select a from t where date(a) = date(b)", "duckdb"),
])
def test_range_rewrites_left_alone(sql, dialect):
    assert rewrite(sql, dialect)["changes"] == []


def test_range_rewrite_skips_text_columns():
    info = {"t": {"columns": [{"name": "s", "type": "VARCHAR"}]}}
    assert rewrite("select a from t where cast(s as date) = '2024-01-01'", "duckdb", table_info=info)["changes"] == []
    typed = {"t": {"columns": [{"name": "s", "type": "TIMESTAMP"}]}}
    out = rewrite("select a from t where cast(s as date) = '2024-01-01'", "duckdb", table_info=typed)
    assert out["changes"] and "Assumes" not in out["changes"][0]["note"]


def test_inner_order_removed_only_where_it_does_nothing():
    out = rewrite("with x as (select a from t order by a) select a from x order by a limit 5", "duckdb")
    assert [c["rule"] for c in out["changes"]] == ["GV006"]
    assert "ORDER BY a LIMIT 5" in flat(out["fixed_sql"])  # the outer sort stays
    for sql in ("select array(select x from y order by x) from z",
                "select * from (select a from t order by a limit 3) s",
                "select * from (select distinct on (a) a, b from t order by a, b) s"):
        assert rewrite(sql, "duckdb")["changes"] == [], sql


def test_opt_in_rewrites_only_in_mode_all():
    sql = ("select e.id, count(distinct e.user_id) from events e where e.user_id not in "
           "(select user_id from banned) group by 1 union select 1, 2")
    assert rewrite(sql, "duckdb")["changes"] == []
    out = rewrite(sql, "duckdb", mode="all")
    rules = {c["rule"]: c["guarantee"] for c in out["changes"]}
    assert rules == {"GV012": "nulls", "GV007": "changes", "GV009": "changes"}
    assert out["same_result"] is False
    assert "NOT EXISTS" in out["fixed_sql"] and "UNION ALL" in out["fixed_sql"]


def test_not_in_needs_a_qualified_outer_column():
    out = rewrite("select id from events where user_id not in (select user_id from banned)", "duckdb", mode="all")
    assert "GV012" not in [c["rule"] for c in out["changes"]]


def test_limit_added_in_mode_all():
    out = rewrite("select * from events", "duckdb", mode="all", limit=50)
    assert flat(out["fixed_sql"]).endswith("LIMIT 50")
    assert rewrite("select count(*) from events", "duckdb", mode="all")["changes"] == []


def test_blocked_statement():
    assert rewrite("delete from t", "duckdb")["status"] == "block"


def test_write_statement_keeps_its_target():
    out = rewrite("create table x as select a from t where date(ts) = '2024-01-01'", "duckdb")
    assert flat(out["fixed_sql"]).startswith("CREATE TABLE x AS SELECT a FROM t WHERE ts >= '2024-01-01'")


# -- the guarantee, checked on real data ---------------------------------------------------
@pytest.fixture(scope="module")
def edge_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("fix") / "edge.duckdb")
    con = duckdb.connect(path)
    con.execute("SET TimeZone = 'Europe/Amsterdam'")
    con.execute("create table t (id int, ts timestamp, d date, tz timestamptz)")
    stamps = ["2023-12-31 23:59:59.999999", "2024-01-01 00:00:00", "2024-01-01 12:00:00", "2024-01-01 23:59:59.999999",
              "2024-01-02 00:00:00", "2024-02-29 13:00:00", "2024-03-01 00:00:00", "2024-12-31 23:59:59",
              "2025-01-01 00:00:00", None]
    for i, s in enumerate(stamps):
        con.execute("insert into t values (?, ?::timestamp, ?::timestamp::date, ?::timestamptz)", [i, s, s, s])
    con.close()
    return path


PREDICATES = [
    "date({c}) = '2024-01-01'", "{c}::date = '2024-01-01'", "date({c}) >= '2024-01-01'", "date({c}) > '2024-01-01'",
    "date({c}) < '2024-01-02'", "date({c}) <= '2024-01-01'", "date({c}) between '2024-01-01' and '2024-02-29'",
    "year({c}) = 2024", "extract(year from {c}) = 2024", "date_trunc('month', {c}) = '2024-02-01'",
    "date_trunc('year', {c}) = '2024-01-01'", "not (date({c}) = '2024-01-01')", "date({c}) = '2024-01-01' or id = 9",
]


@pytest.mark.parametrize("column", ["ts", "d", "tz"])
@pytest.mark.parametrize("predicate", PREDICATES)
def test_same_rows_on_real_data(edge_db, column, predicate):
    sql = f"select id from t where {predicate.format(c=column)} order by id"
    out = rewrite(sql, "duckdb")
    assert out["changes"], sql
    assert out["same_result"]
    con = duckdb.connect(edge_db, read_only=True)
    con.execute("SET TimeZone = 'Europe/Amsterdam'")
    before = con.execute(sql).fetchall()
    after = con.execute(out["fixed_sql"]).fetchall()
    con.close()
    assert before == after, (sql, out["fixed_sql"])


def test_not_exists_matches_not_in_without_nulls(tmp_path):
    con = duckdb.connect()
    con.execute("create table e as select range as id, range % 7 as user_id from range(100)")
    con.execute("create table banned as select * from (values (1), (3)) v(user_id)")
    sql = "select e.id from e where e.user_id not in (select user_id from banned) order by 1"
    out = rewrite(sql, "duckdb", mode="all")
    assert con.execute(sql).fetchall() == con.execute(out["fixed_sql"]).fetchall()
    con.execute("insert into banned values (null)")  # the documented difference
    assert con.execute(sql).fetchall() == []
    assert con.execute(out["fixed_sql"]).fetchall() != []


# -- integration --------------------------------------------------------------------------
def test_fix_with_connection_reports_estimates(settings):
    out = fix(settings, "select event_type, count(*) from events where date(ts) = '2025-01-02' group by 1")
    assert out["status"] == "ok" and out["same_result"]
    assert out["estimate"]["before"]["bytes"] and out["estimate"]["after"]["bytes"]
    assert "saving" in out and "summary" in out["saving"]
    assert out["connection"] == "default"


def test_fix_nothing_to_do(settings):
    out = fix(settings, "select count(*) from events")
    assert out["changes"] == [] and out["status"] == "ok"


def test_fix_other_dialect_works_offline(settings):
    out = fix(settings, "SELECT a FROM t WHERE DATE(ts) = '2024-01-01'", dialect="bigquery")
    assert out["changes"] and "estimate" not in out and "connection" not in out


def test_preflight_and_lint_hand_over_the_fixed_sql(settings):
    pre = core.preflight(settings, "select event_type, count(*) from events where date(ts) = '2025-01-02' group by 1")
    assert pre["autofix"]["same_result"] and "ts >= '2025-01-02'" in flat(pre["autofix"]["fixed_sql"])
    assert "autofix.fixed_sql" in pre["next_step"]
    lint = core.lint_sql("select a from t where year(ts) = 2024", "duckdb")
    assert lint["autofix"]["rules"] == ["GV005"]
    assert "autofix" not in core.lint_sql("select count(*) from t", "duckdb")


def test_cli_fix(demo_db, state, capsys):
    assert main(["--dsn", demo_db, "fix", "select count(*) from events where date(ts) = '2025-01-02'"]) == 0
    text = capsys.readouterr().out
    assert "returns exactly the same rows" in text and "ts >= '2025-01-02'" in text
    assert main(["fix", "--json", "--dialect", "bigquery", "--mode", "all", "SELECT * FROM t"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["changes"][0]["rule"] == "GV002"


def test_mcp_fix_tool(demo_db, state, monkeypatch):
    monkeypatch.setenv("GULLIVER_DSN", demo_db)
    server = build_server()
    result = asyncio.run(server.call_tool("gulliver_fix", {"sql": "select count(*) from events where year(ts) = 2025"}))
    text = json.dumps(result if isinstance(result, (dict, list)) else
                      (result.model_dump() if hasattr(result, "model_dump") else str(result)), default=str)
    assert "GV005" in text and "same" in text
