"""Auto-fix: rewrite SQL so it is cheaper on big data, and say exactly what each rewrite changes.

Agents get lint findings, but small models often fail to rewrite the SQL themselves. `gulliver_fix`
does the rewrite and labels every change with a guarantee:

  same     the rewritten query returns exactly the same rows (always applied)
  nulls    same rows, unless a NOT IN subquery returns NULL (then the original returns nothing,
           which is almost never what was meant)                       -> only with mode="all"
  changes  the result changes on purpose (LIMIT, approximate count, UNION ALL)
                                                                       -> only with mode="all"

With a connection it also estimates the original and the fixed query (free: dry run / EXPLAIN),
so the agent and the human see the saving instead of trusting it.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlglot import exp

from .lint import _has_aggregation, _outer_select, lint, summarize
from .sqlsafety import Statement, classify

SAME = "same"
NULLS = "nulls"
CHANGES = "changes"
GUARANTEE_TEXT = {
    SAME: "returns exactly the same rows",
    NULLS: "same rows unless the subquery returns NULL",
    CHANGES: "changes the result on purpose",
}

DATE_TYPES = ("date", "time", "datetime")  # matches DATE, TIMESTAMP, TIMESTAMP_TZ, DATETIME, TIMESTAMPTZ ...
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Change:
    rule: str
    guarantee: str
    before: str
    after: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["meaning"] = GUARANTEE_TEXT[self.guarantee]
        return out


# -- date range filters (GV005) ----------------------------------------------------------
def _unit_of(node: exp.Expression | None) -> str | None:
    if node is None:
        return None
    text = node.name if isinstance(node, (exp.Var, exp.Literal)) else node.sql()
    text = text.strip("'\"").upper()
    return {"DAY": "day", "MONTH": "month", "YEAR": "year"}.get(text)


def _truncation(node: exp.Expression) -> tuple[exp.Column, str] | None:
    """`DATE(ts)`, `ts::date`, `TO_DATE(ts)`, `DATE_TRUNC('month', ts)`, `YEAR(ts)` ... -> (ts, unit)."""
    if isinstance(node, exp.Date) and isinstance(node.this, exp.Column) and not any(
            v for k, v in node.args.items() if k != "this"):
        return node.this, "day"
    if isinstance(node, exp.TsOrDsToDate) and isinstance(node.this, exp.Column) and not node.args.get("format"):
        return node.this, "day"
    if isinstance(node, exp.Cast) and not isinstance(node, exp.TryCast) and isinstance(node.this, exp.Column):
        to = node.args.get("to")
        if isinstance(to, exp.DataType) and to.this == exp.DataType.Type.DATE:
            return node.this, "day"
    if isinstance(node, (exp.TimestampTrunc, exp.DateTrunc, exp.DatetimeTrunc)) and isinstance(node.this, exp.Column):
        if node.args.get("zone"):
            return None
        unit = _unit_of(node.args.get("unit"))
        if unit:
            return node.this, unit
    if isinstance(node, exp.Year) and isinstance(node.this, exp.Column):
        return node.this, "year"
    if (isinstance(node, exp.Extract) and isinstance(node.expression, exp.Column)
            and _unit_of(node.this) == "year"):
        return node.expression, "year"
    return None


def _literal_start(node: exp.Expression | None, unit: str) -> date | None:
    """The first day of the period that the literal names, or None if it is not a clean literal."""
    if node is None:
        return None
    if isinstance(node, exp.Cast) and isinstance(node.this, exp.Literal):
        to = node.args.get("to")
        if not (isinstance(to, exp.DataType) and to.this == exp.DataType.Type.DATE):
            return None
        node = node.this
    if isinstance(node, exp.Date) and isinstance(node.this, exp.Literal):
        node = node.this
    if not isinstance(node, exp.Literal):
        return None
    if unit == "year" and not node.is_string:
        try:
            year = int(node.name)
        except ValueError:
            return None
        return date(year, 1, 1) if 1 <= year <= 9998 else None
    if not node.is_string or not _ISO_DAY.match(node.name):
        return None
    try:
        day = date.fromisoformat(node.name)
    except ValueError:
        return None
    if unit == "month" and day.day != 1:
        return None
    if unit == "year" and (day.month, day.day) != (1, 1):
        return None
    return day


def _next(start: date, unit: str) -> date:
    if unit == "day":
        return date.fromordinal(start.toordinal() + 1)
    if unit == "month":
        return date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return date(start.year + 1, 1, 1)


FLIP = {exp.GT: exp.LT, exp.GTE: exp.LTE, exp.LT: exp.GT, exp.LTE: exp.GTE, exp.EQ: exp.EQ}


def _column_type(col: exp.Column, column_types: dict[str, str]) -> str | None:
    return column_types.get(col.name.lower())


def _range(col: exp.Column, low: date | None, high: date | None) -> exp.Expression:
    parts: list[exp.Expression] = []
    if low is not None:
        parts.append(exp.GTE(this=col.copy(), expression=exp.Literal.string(low.isoformat())))
    if high is not None:
        parts.append(exp.LT(this=col.copy(), expression=exp.Literal.string(high.isoformat())))
    node = parts[0] if len(parts) == 1 else exp.And(this=parts[0], expression=parts[1])
    return exp.Paren(this=node) if len(parts) > 1 else node


def _rewrite_range(cmp: exp.Expression, column_types: dict[str, str]) -> tuple[exp.Expression, str] | None:
    """Return (replacement, note) for a comparison on a truncated date column, else None."""
    if isinstance(cmp, exp.Between):
        trunc = _truncation(cmp.this)
        if not trunc:
            return None
        col, unit = trunc
        low = _literal_start(cmp.args.get("low"), unit)
        high = _literal_start(cmp.args.get("high"), unit)
        if low is None or high is None:
            return None
        repl = _range(col, low, _next(high, unit))
    else:
        op = type(cmp)
        if op not in FLIP:
            return None
        left, right = cmp.this, cmp.args.get("expression")
        trunc = _truncation(left)
        literal = right
        if not trunc:
            trunc = _truncation(right) if right is not None else None
            literal = left
            op = FLIP[op]
        if not trunc:
            return None
        col, unit = trunc
        start = _literal_start(literal, unit)
        if start is None:
            return None
        bounds = {
            exp.EQ: (start, _next(start, unit)),
            exp.GTE: (start, None),
            exp.GT: (_next(start, unit), None),
            exp.LT: (None, start),
            exp.LTE: (None, _next(start, unit)),
        }[op]
        repl = _range(col, *bounds)
    ctype = _column_type(col, column_types)
    if ctype is not None and not any(t in ctype.lower() for t in DATE_TYPES):
        return None  # e.g. a VARCHAR holding dates: comparing text ranges would not be the same filter
    note = (f"Filters the raw column {col.sql()} by range, so partitions and min/max statistics can skip data.")
    if ctype is None:
        note += f" Assumes {col.sql()} is a DATE or TIMESTAMP column."
    return repl, note


def _fix_ranges(tree: exp.Expression, dialect: str, column_types: dict[str, str], changes: list[Change]) -> None:
    for select in list(tree.find_all(exp.Select)):
        where = select.args.get("where")
        if where is None:
            continue
        for cmp in list(where.find_all(exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)):
            if cmp.find_ancestor(exp.Select) is not select:
                continue  # belongs to a subquery; handled when we visit that select
            out = _rewrite_range(cmp, column_types)
            if out is None:
                continue
            repl, note = out
            if isinstance(repl, exp.Paren) and isinstance(cmp.parent, (exp.Where, exp.And)):
                repl = repl.this  # AND inside AND/WHERE needs no brackets
            before = cmp.sql(dialect=dialect)
            cmp.replace(repl)
            changes.append(Change("GV005", SAME, before, repl.sql(dialect=dialect), note))


# -- ORDER BY inside a subquery or CTE (GV006) ------------------------------------------
def _fix_inner_order(tree: exp.Expression, dialect: str, changes: list[Change]) -> None:
    outer = _outer_select(tree)
    for select in list(tree.find_all(exp.Select)):
        if select is outer or not select.args.get("order"):
            continue
        if select.args.get("limit") or select.args.get("offset") or select.args.get("fetch"):
            continue
        distinct = select.args.get("distinct")
        if distinct is not None and distinct.args.get("on"):
            continue  # DISTINCT ON depends on the order
        parent = select.parent
        source = isinstance(parent, exp.CTE) or (
            isinstance(parent, exp.Subquery) and isinstance(parent.parent, (exp.From, exp.Join)))
        if not source:
            continue  # e.g. ARRAY(SELECT ... ORDER BY ...) keeps its order on purpose
        before = select.args["order"].sql(dialect=dialect)
        select.set("order", None)
        changes.append(Change("GV006", SAME, before, "(removed)",
                              "SQL does not keep the order of a subquery or CTE, so this sort only costs time."))


# -- NOT IN (subquery) -> NOT EXISTS (GV012) ---------------------------------------------
def _from(select: exp.Select) -> exp.From | None:
    return select.args.get("from_") or select.args.get("from")  # the key is "from_" in newer sqlglot


def _fix_not_in(tree: exp.Expression, dialect: str, changes: list[Change]) -> None:
    for not_node in list(tree.find_all(exp.Not)):
        inner = not_node.this
        if not isinstance(inner, exp.In) or inner.args.get("query") is None:
            continue
        outer_col = inner.this
        query = inner.args["query"]
        sub = query.this if isinstance(query, exp.Subquery) else query
        if not (isinstance(outer_col, exp.Column) and outer_col.table and isinstance(sub, exp.Select)):
            continue
        if (len(sub.expressions) != 1 or sub.args.get("joins") or sub.args.get("group") or sub.args.get("having")
                or sub.args.get("limit") or sub.args.get("distinct") or _from(sub) is None):
            continue
        source = _from(sub).this
        projected = sub.expressions[0]
        if isinstance(projected, exp.Alias):
            projected = projected.this
        if not (isinstance(source, exp.Table) and isinstance(projected, exp.Column)):
            continue
        alias = source.alias_or_name if source.alias else "gv_sub"
        if alias.lower() == outer_col.table.lower():
            continue  # same name inside and outside: the rewrite could bind to the wrong table
        new_sub = sub.copy()
        new_source = _from(new_sub).this
        if not new_source.alias:
            new_source.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
        inner_col = exp.column(projected.name, table=alias)
        condition = exp.EQ(this=inner_col, expression=outer_col.copy())
        where = new_sub.args.get("where")
        new_sub.set("where", exp.Where(this=exp.and_(where.this, condition) if where is not None else condition))
        new_sub.set("expressions", [exp.Literal.number(1)])
        repl = exp.Not(this=exp.Exists(this=new_sub))
        before = not_node.sql(dialect=dialect)
        not_node.replace(repl)
        changes.append(Change("GV012", NULLS, before, repl.sql(dialect=dialect),
                              "NOT EXISTS plans as an anti-join. The only difference: when the subquery returns a "
                              "NULL, NOT IN returns no rows at all, NOT EXISTS ignores the NULL."))


# -- result-changing rewrites (opt-in) -----------------------------------------------------
def _fix_limit(tree: exp.Expression, dialect: str, limit: int, changes: list[Change]) -> None:
    outer = _outer_select(tree)
    if outer is None or outer.args.get("limit") or outer.args.get("fetch") or _has_aggregation(outer):
        return
    outer.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
    changes.append(Change("GV002", CHANGES, "(no LIMIT)", f"LIMIT {limit}",
                          f"Returns at most {limit} rows, for exploring. Note: on BigQuery a LIMIT does not lower "
                          "the bytes billed; filters and fewer columns do."))


def _fix_approx(tree: exp.Expression, dialect: str, changes: list[Change]) -> None:
    if dialect == "postgres":
        return  # no built-in approximate distinct count
    for count in list(tree.find_all(exp.Count)):
        distinct = count.this
        if not isinstance(distinct, exp.Distinct) or len(distinct.expressions) != 1:
            continue
        repl = exp.ApproxDistinct(this=distinct.expressions[0].copy())
        before = count.sql(dialect=dialect)
        count.replace(repl)
        changes.append(Change("GV007", CHANGES, before, repl.sql(dialect=dialect),
                              "Approximate distinct count (HyperLogLog): usually within about 1-2%, far less memory."))


def _fix_union(tree: exp.Expression, dialect: str, changes: list[Change]) -> None:
    for union in list(tree.find_all(exp.Union)):
        if union.args.get("distinct"):
            union.set("distinct", False)
            changes.append(Change("GV009", CHANGES, "UNION", "UNION ALL",
                                  "Keeps duplicate rows instead of sorting/hashing both sides to remove them. "
                                  "Same result only if the two sides cannot overlap."))


# -- driver -------------------------------------------------------------------------------
def column_types_from(table_info: dict[str, dict] | None) -> dict[str, str]:
    """Lower-case column name -> type, from engine metadata (ambiguous names are dropped)."""
    types: dict[str, str] = {}
    clash: set[str] = set()
    for info in (table_info or {}).values():
        for col in info.get("columns") or []:
            name = str(col.get("name", "")).lower()
            ctype = str(col.get("type", ""))
            if name in types and types[name] != ctype:
                clash.add(name)
            types[name] = ctype
    for name in clash:
        types.pop(name, None)
    return types


def rewrite(sql: str, dialect: str = "duckdb", mode: str = "safe", limit: int = 1000,
            table_info: dict[str, dict] | None = None) -> dict[str, Any]:
    """Rewrite one statement. Pure SQL work: no database needed."""
    if mode not in ("safe", "all"):
        raise ValueError("mode must be 'safe' or 'all'")
    statement: Statement = classify(sql, dialect)
    if statement.kind == "block" or statement.tree is None or statement.select is None:
        return {"status": "block", "statement": statement.public(), "changes": [],
                "next_step": "Send a single SELECT (or CREATE/INSERT ... SELECT). " + statement.reason}
    before_findings = lint(statement.select, dialect, table_info)
    changes: list[Change] = []
    tree = statement.tree
    column_types = column_types_from(table_info)
    _fix_ranges(statement.select, dialect, column_types, changes)
    _fix_inner_order(statement.select, dialect, changes)
    if mode == "all":
        _fix_not_in(statement.select, dialect, changes)
        _fix_approx(statement.select, dialect, changes)
        _fix_union(statement.select, dialect, changes)
        _fix_limit(statement.select, dialect, limit, changes)
    fixed_sql = tree.sql(dialect=dialect, pretty=True)
    after = classify(fixed_sql, dialect)
    after_findings = lint(after.select, dialect, table_info) if after.select is not None else []
    return {
        "statement": statement.public(),
        "fixed_sql": fixed_sql,
        "changes": [c.as_dict() for c in changes],
        "same_result": all(c.guarantee == SAME for c in changes),
        "lint_before": summarize(before_findings),
        "lint_after": summarize(after_findings),
        "remaining": [f.as_dict() for f in after_findings],
        "sql_hash_before": statement.sql_hash,
        "sql_hash_after": after.sql_hash,
    }


# -- with a connection: prove the saving --------------------------------------------------
def fix(settings: Any, sql: str, connection: str | None = None, dialect: str | None = None,
        mode: str = "safe", limit: int | None = None) -> dict[str, Any]:
    """Rewrite the SQL and, when a connection is available, estimate both versions (no data is read)."""
    from .core import _engine, _fmt_bytes, _fmt_usd, _table_infos
    from .engines import EngineError, dialect_for

    conn = None
    if settings is not None:
        conn = settings.connection(connection)
        dialect = dialect or dialect_for(conn.engine)
        if dialect != dialect_for(conn.engine):
            conn = None  # different dialect than the connection: rewrite offline only
    dialect = dialect or "duckdb"
    max_rows = limit or (settings.budget.max_output_rows if settings is not None else 1000)

    infos: dict[str, dict] = {}
    notes: list[str] = []
    with ExitStack() as stack:
        engine = None
        if conn is not None:
            try:
                _, engine = stack.enter_context(_engine(settings, conn.name))
                statement = classify(sql, dialect)
                if statement.kind != "block":
                    found, table_notes = _table_infos(engine, statement)
                    infos = {k: v.as_dict(with_columns=True) for k, v in found.items()}
                    notes.extend(table_notes)
            except EngineError as exc:
                notes.append(f"metadata unavailable: {exc}")
                engine = None

        result = rewrite(sql, dialect, mode=mode, limit=max_rows, table_info=infos or None)
        result = {"action": "fix", "dialect": dialect, **result}
        if result.get("status") == "block":
            return result
        if engine is not None and result["changes"]:
            estimates: dict[str, Any] = {}
            for label, text in (("before", sql), ("after", result["fixed_sql"])):
                st = classify(text, dialect)
                try:
                    estimates[label] = engine.estimate(st.select.sql(dialect=dialect)).as_dict()
                except EngineError as exc:
                    estimates[label] = {"error": str(exc)}
            result["estimate"] = estimates
            saving = _saving(estimates.get("before") or {}, estimates.get("after") or {})
            if saving:
                result["saving"] = saving
                if saving.get("bytes_pct") is not None:
                    saving["summary"] = (f"scan {_fmt_bytes(saving['bytes_before'])} -> "
                                         f"{_fmt_bytes(saving['bytes_after'])} ({saving['bytes_pct']:.0f}% less)")
                    if engine.billed and saving.get("usd_before") is not None and saving.get("usd_after") is not None:
                        saving["summary"] += (f", cost {_fmt_usd(saving['usd_before'])} -> "
                                              f"{_fmt_usd(saving['usd_after'])}")
                    if saving["bytes_pct"] <= 0:
                        saving["summary"] += (". The estimate does not change here (no partitions or the engine "
                                              "estimates before pruning); the rewrite still lets partitioned tables, "
                                              "Parquet files and clustered tables skip data.")
        if conn is not None:
            result["connection"] = conn.name

    if notes:
        result["notes"] = notes
    changes = result["changes"]
    remaining_errors = result["lint_after"]["error"]
    if not changes:
        result["status"] = "warn" if remaining_errors or result["lint_after"]["warn"] else "ok"
        result["next_step"] = ("Nothing could be rewritten automatically. "
                               + ("Fix the remaining lint findings by hand (they need a decision, e.g. which date "
                                  "range or which join key)." if result["remaining"] else
                                  "The SQL has no scale problems Gulliver can fix. Call gulliver_preflight."))
        if mode == "safe" and _opt_in_rules(result["remaining"]):
            result["next_step"] += " Call gulliver_fix with mode='all' for rewrites that change the result slightly."
        return result
    result["status"] = "warn" if remaining_errors else "ok"
    if result["same_result"]:
        result["next_step"] = ("Use fixed_sql: it returns exactly the same rows. Call gulliver_preflight with it.")
    else:
        result["next_step"] = ("Some rewrites change the result (see changes[].meaning). Tell the human what changed, "
                               "and check with gulliver_diff before relying on it. Then gulliver_preflight fixed_sql.")
    if remaining_errors:
        result["next_step"] += " Lint errors remain (see remaining); fix those by hand first."
    return result


def _opt_in_rules(findings: list[dict[str, Any]]) -> bool:
    return any(f.get("rule") in ("GV002", "GV007", "GV009", "GV012") for f in findings)


def _saving(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
    b_bytes, a_bytes = before.get("bytes"), after.get("bytes")
    b_usd, a_usd = before.get("cost_usd"), after.get("cost_usd")
    if b_bytes is None and b_usd is None:
        return None
    out: dict[str, Any] = {"bytes_before": b_bytes, "bytes_after": a_bytes, "usd_before": b_usd, "usd_after": a_usd,
                           "accuracy": after.get("accuracy") or before.get("accuracy")}
    if b_bytes and a_bytes is not None:
        out["bytes_pct"] = round(100.0 * (b_bytes - a_bytes) / b_bytes, 1)
    if b_usd and a_usd is not None:
        out["usd_pct"] = round(100.0 * (b_usd - a_usd) / b_usd, 1)
    return out
