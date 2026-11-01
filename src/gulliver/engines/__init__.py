"""Engine registry. Drivers are imported lazily so only the engines you use need to be installed."""

from __future__ import annotations

from ..config import Connection
from .base import Engine, EngineError, Estimate, ExecResult, MissingDriver, TableInfo

ENGINES = ("duckdb", "postgres", "bigquery", "snowflake")
DIALECTS = {"duckdb": "duckdb", "postgres": "postgres", "bigquery": "bigquery", "snowflake": "snowflake"}


def get_engine(connection: Connection, read_only: bool = True) -> Engine:
    name = connection.engine.lower()
    if name == "duckdb":
        from .duckdb_engine import DuckDBEngine

        return DuckDBEngine(connection, read_only=read_only)
    if name in ("postgres", "postgresql"):
        from .postgres import PostgresEngine

        return PostgresEngine(connection, read_only=read_only)
    if name == "bigquery":
        from .bigquery import BigQueryEngine

        return BigQueryEngine(connection, read_only=read_only)
    if name == "snowflake":
        from .snowflake import SnowflakeEngine

        return SnowflakeEngine(connection, read_only=read_only)
    raise EngineError(f"Unknown engine '{connection.engine}'. Supported: {', '.join(ENGINES)}")


def dialect_for(engine_name: str) -> str:
    return DIALECTS.get(engine_name.lower().replace("postgresql", "postgres"), engine_name.lower())


__all__ = ["Engine", "EngineError", "Estimate", "ExecResult", "MissingDriver", "TableInfo",
           "get_engine", "dialect_for", "ENGINES"]
