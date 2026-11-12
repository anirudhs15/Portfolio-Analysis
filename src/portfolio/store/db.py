"""DuckDB access: connection, schema creation and simple upsert helpers."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA.read_text())
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE rows by the table's primary key. Columns must match table column names."""
    if df is None or df.empty:
        return 0
    cols = ", ".join(df.columns)
    con.register("_upsert_df", df)
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _upsert_df")
    finally:
        con.unregister("_upsert_df")
    return len(df)


def query(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()
