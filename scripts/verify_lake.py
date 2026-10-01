"""Check a weather lake against its contract with DuckDB.

    LAKE_ROOT=s3://<bucket> uv run python -m scripts.verify_lake     (or a local mirror)

Per product: the catalog is readable, every curated file has the contract's columns, no
required value is null, a business key appears once per posting, series are the catalog's,
schema versions are known, and no row was posted after it was ingested.
"""

from __future__ import annotations

import sys
from typing import Any

import duckdb

from ingest.config import aws_region, load_settings
from weather_lake import WeatherReader
from weather_lake.contract import (
    BUSINESS_KEY,
    CURATED_PREFIX,
    FORECAST_SCHEMA,
    SUPPORTED_SCHEMA_VERSIONS,
)
from weather_lake.reader import s3_setup_sql

# Every SQL string here is built from contract identifiers and this script's own constants;
# the lake root is the operator's own setting.
# ruff: noqa: S608


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> Any:
    row = con.execute(sql, params).fetchone()
    return row[0] if row else None


def verify(root: str, region: str | None) -> list[str]:
    problems: list[str] = []
    with WeatherReader(root, region=region) as reader:
        catalog = reader.catalog
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC';")
    if root.startswith("s3://"):
        for sql in s3_setup_sql(region):
            con.execute(sql)
    for key, product in catalog.products.items():
        files = f"{root.rstrip('/')}/{CURATED_PREFIX}/{key}/date=*/*.parquet"
        src = f"read_parquet('{files}', union_by_name=true, hive_partitioning=false)"
        n_files = _one(con, "SELECT count(*) FROM glob(?)", [files])
        print(f"{key}: {n_files} curated files")
        if not n_files:
            problems.append(f"{key}: no curated files")
            continue
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
        missing = set(FORECAST_SCHEMA.names) - cols
        if missing:
            problems.append(f"{key}: missing columns {sorted(missing)}")
            continue
        nulls = " OR ".join(f"{c} IS NULL" for c in FORECAST_SCHEMA.names)
        if n := _one(con, f"SELECT count(*) FROM {src} WHERE {nulls}", []):
            problems.append(f"{key}: {n} rows with a null in a required column")
        group = ", ".join((*BUSINESS_KEY, "posted_at"))
        dup = (
            f"SELECT count(*) FROM (SELECT {group} FROM {src} GROUP BY {group} HAVING count(*) > 1)"
        )
        if n := _one(con, dup, []):
            problems.append(f"{key}: {n} business keys repeated within a posting")
        known = set(product.series())
        series = {r[0] for r in con.execute(f"SELECT DISTINCT series FROM {src}").fetchall()}
        if unknown := series - known:
            problems.append(f"{key}: series not in the catalog: {sorted(unknown)[:5]}")
        versions = {
            r[0] for r in con.execute(f"SELECT DISTINCT schema_version FROM {src}").fetchall()
        }
        if versions - SUPPORTED_SCHEMA_VERSIONS:
            problems.append(f"{key}: unknown schema versions {sorted(versions)}")
        late = f"SELECT count(*) FROM {src} WHERE posted_at > ingested_at"
        if n := _one(con, late, []):
            problems.append(f"{key}: {n} rows posted after they were ingested")
        postings = _one(
            con, f"SELECT count(DISTINCT posted_at) FROM {src} WHERE source = 'live'", []
        )
        print(f"{key}: {postings} live postings, {len(series)} series")
    return problems


def main() -> int:
    settings = load_settings()
    problems = verify(settings.lake.root, aws_region())
    for p in problems:
        print(f"PROBLEM: {p}")
    print("OK: no problems" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
