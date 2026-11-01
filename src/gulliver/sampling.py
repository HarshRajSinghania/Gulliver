"""Rewrite a query so it reads a sample of its tables instead of the full tables.

Every chosen table reference `t AS x` becomes `(SELECT * FROM t <sample clause>) AS x`, so
the rest of the query (joins, filters, column references) stays exactly the same.
"""

from __future__ import annotations

import re

from sqlglot import exp

from .sqlsafety import base_tables, table_ref


def percent_text(fraction: float) -> str:
    pct = fraction * 100
    text = f"{pct:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def sample_query(tree: exp.Expression, dialect: str, clause_for, only: set[str] | None = None) -> tuple[str, list[str]]:
    """Return (sql, sampled_table_refs).

    clause_for(ref) -> the engine's sample clause for that table, e.g. "TABLESAMPLE 1% (system, 42)".
    only: lower-case table refs to sample; None samples every base table.
    """
    work = tree.copy()
    replacements: dict[str, str] = {}
    sampled: list[str] = []
    for index, table in enumerate(base_tables(work, dialect)):
        ref = table_ref(table, dialect)
        if only is not None and ref.lower() not in only:
            continue
        if isinstance(table.this, exp.Identifier):
            alias = table.alias or table.name
        else:
            alias = table.alias or f"gv_t{index}"
        placeholder = f"gvsampleplaceholder{index}"
        replacement = exp.Table(
            this=exp.to_identifier(placeholder),
            alias=exp.TableAlias(this=exp.to_identifier(alias)),
        )
        table.replace(replacement)
        replacements[placeholder] = f"(SELECT * FROM {ref} {clause_for(ref)})"
        if ref not in sampled:
            sampled.append(ref)
    sql = work.sql(dialect=dialect)
    for placeholder, subquery in replacements.items():
        sql = re.sub(rf"[`\"\[]?{placeholder}[`\"\]]?", lambda _m, s=subquery: s, sql)
    return sql, sampled
