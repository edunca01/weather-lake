"""Point-in-time reads over the weather lake with DuckDB.

Two primitives, both with an explicit knowledge time:

- ``snapshot(..., as_of=t)``: what was forecast for each hour as known at ``t`` (rows posted
  after ``t`` are invisible; of the rest the latest posting per business key wins);
- ``postings(..., as_of=t)``: every version posted by ``t``, not deduplicated, for building
  training sets with an as-of join (one pass instead of one snapshot per decision time).

There is deliberately no method without ``as_of``: a read that ignores it uses the future.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Final, cast

import duckdb
import pyarrow as pa
import pyarrow.compute as pc

from weather_lake.catalog import Catalog
from weather_lake.contract import (
    BUSINESS_KEY,
    CATALOG_KEY,
    FORECAST_SCHEMA,
    SUPPORTED_SCHEMA_VERSIONS,
    curated_partition,
)
from weather_lake.errors import CatalogNotFoundError, UnsupportedSchemaVersionError

COLUMNS: Final = ("interval_start", "interval_minutes", "series", "value", "posted_at")
# Postings keep every version, so they also carry the second clock: a replay of "what this
# system had at T" filters ingested_at <= T on top of posted_at <= as_of.
POSTING_COLUMNS: Final = ("ingested_at", "source")

_REGION = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d+$")


class WeatherReader:
    """Read one weather lake, local (``./data``, a training mirror) or on S3 (``s3://bucket``).

    S3 credentials come from the standard AWS chain through DuckDB's ``aws`` extension. One
    DuckDB connection per reader, serialized with a lock (connections are not thread-safe).
    """

    def __init__(
        self,
        root: str | Path,
        *,
        region: str | None = None,
        threads: int | None = None,
        max_days: int = 62,
    ) -> None:
        text = str(root)
        self.is_s3 = text.startswith("s3://")
        self.root = text.rstrip("/") if self.is_s3 else Path(text).expanduser().resolve().as_posix()
        if region is not None and not _REGION.fullmatch(region):
            msg = f"not an AWS region: {region!r}"
            raise ValueError(msg)
        # Longest valid-date range one query may span. Each day is one listing plus its files,
        # so this bounds a call's cost on S3; a local mirror can afford a larger value.
        self.max_days = max_days
        self._region = region
        self._threads = threads
        self._catalog: Catalog | None = None
        self._lock = threading.Lock()
        self._con = self._connect()

    # -- connection ------------------------------------------------------------------------

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute("SET TimeZone='UTC';")
        if self._threads is not None:
            con.execute(f"SET threads={int(self._threads)};")
        if self.is_s3:
            for sql in s3_setup_sql(self._region):
                con.execute(sql)
        return con

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> WeatherReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- catalog ---------------------------------------------------------------------------

    @property
    def catalog(self) -> Catalog:
        """The lake's catalog, read once per reader."""
        if self._catalog is None:
            uri = f"{self.root}/{CATALOG_KEY}"
            try:
                with self._lock:
                    row = self._con.execute("SELECT content FROM read_text(?)", [uri]).fetchone()
            except duckdb.IOException as exc:
                msg = f"no catalog at {uri}"
                raise CatalogNotFoundError(msg) from exc
            if row is None:
                msg = f"no catalog at {uri}"
                raise CatalogNotFoundError(msg)
            self._catalog = Catalog.parse(cast(str, row[0]))
        return self._catalog

    def products(self) -> list[str]:
        return sorted(self.catalog.products)

    # -- reads -----------------------------------------------------------------------------

    def snapshot(
        self,
        product: str,
        start: datetime,
        end: datetime,
        *,
        as_of: datetime,
        series: Sequence[str] | None = None,
    ) -> pa.Table:
        """The forecast for valid hours in ``[start, end)`` as known at ``as_of``: per
        (interval_start, series), the latest posting with ``posted_at <= as_of``.

        ``series`` filters by name; ``*`` matches anything (``"temperature_2m:*"``)."""
        files, where, params = self._prepare(product, start, end, as_of, series)
        if not files:
            return _empty(COLUMNS)
        key = ", ".join(BUSINESS_KEY)
        sql = f"""
            SELECT {", ".join(COLUMNS)}, schema_version
            FROM read_parquet(?, union_by_name=true)
            WHERE posted_at <= ? AND interval_start >= ? AND interval_start < ? {where}
            QUALIFY row_number() OVER (
                PARTITION BY {key} ORDER BY posted_at DESC, ingested_at DESC
            ) = 1
            ORDER BY {key}
        """  # noqa: S608  (identifiers come from the contract; values are bound)
        return self._run(sql, [files, as_of, start, end, *params])

    def postings(
        self,
        product: str,
        start: datetime,
        end: datetime,
        *,
        as_of: datetime,
        series: Sequence[str] | None = None,
    ) -> pa.Table:
        """Every version for valid hours in ``[start, end)`` posted by ``as_of``, oldest first
        and not deduplicated, with ``ingested_at`` and ``source``. Feed this to an as-of join
        (``posted_at <= decision time``) to build many decision times in one pass."""
        files, where, params = self._prepare(product, start, end, as_of, series)
        columns = (*COLUMNS, *POSTING_COLUMNS)
        if not files:
            return _empty(columns)
        order = ", ".join((*BUSINESS_KEY, "posted_at"))
        sql = f"""
            SELECT {", ".join(columns)}, schema_version
            FROM read_parquet(?, union_by_name=true)
            WHERE posted_at <= ? AND interval_start >= ? AND interval_start < ? {where}
            ORDER BY {order}
        """  # noqa: S608  (identifiers come from the contract; values are bound)
        return self._run(sql, [files, as_of, start, end, *params])

    # -- helpers ---------------------------------------------------------------------------

    def _prepare(
        self,
        product: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        series: Sequence[str] | None,
    ) -> tuple[list[str], str, list[Any]]:
        _require_aware(start=start, end=end, as_of=as_of)
        self.catalog.product(product)
        if end <= start:
            msg = f"empty interval range {start} .. {end}"
            raise ValueError(msg)
        d_from = start.astimezone(UTC).date()
        d_to = (end - timedelta(microseconds=1)).astimezone(UTC).date()
        if (d_to - d_from).days >= self.max_days:
            msg = f"valid days {d_from}..{d_to} longer than {self.max_days} days; loop over windows"
            raise ValueError(msg)
        where, params = _series_filter(series)
        return self._files(product, d_from, d_to), where, params

    def _files(self, product: str, d_from: date, d_to: date) -> list[str]:
        """Parquet files of the requested valid days, one listing per day. A ``date=*`` glob
        would make DuckDB list every object of the product on S3 on every query."""
        out: list[str] = []
        with self._lock:
            for i in range((d_to - d_from).days + 1):
                partition = curated_partition(product, d_from + timedelta(days=i))
                pattern = f"{self.root}/{partition}*.parquet"
                rows = self._con.execute("SELECT file FROM glob(?)", [pattern]).fetchall()
                out.extend(sorted(cast(str, r[0]) for r in rows))
        return out

    def _run(self, sql: str, params: list[Any]) -> pa.Table:
        # Through Arrow, not fetchall(): timestamps come back as aware UTC without pytz.
        with self._lock:
            result = self._con.execute(sql, params).to_arrow_table()
        versions = set(cast(list[int], pc.unique(result.column("schema_version")).to_pylist()))
        unknown = versions - SUPPORTED_SCHEMA_VERSIONS
        if unknown:
            msg = f"rows at schema_version {sorted(unknown)}; upgrade weather-lake"
            raise UnsupportedSchemaVersionError(msg)
        return result.drop_columns(["schema_version"])


def s3_setup_sql(region: str | None) -> list[str]:
    """DuckDB statements that make ``s3://`` readable with the standard AWS credential chain;
    ``REFRESH auto`` outlives a rotated SSO or role session."""
    region_opt = f", REGION '{region}'" if region else ""
    return [
        "INSTALL httpfs; LOAD httpfs;",
        "INSTALL aws; LOAD aws;",
        "CREATE SECRET IF NOT EXISTS weather_lake "
        f"(TYPE s3, PROVIDER credential_chain, REFRESH auto{region_opt});",
    ]


def _require_aware(**stamps: datetime) -> None:
    for name, ts in stamps.items():
        if ts.tzinfo is None or ts.utcoffset() is None:
            msg = f"{name} must be timezone-aware (UTC recommended), got {ts!r}"
            raise ValueError(msg)


def _series_filter(series: Sequence[str] | None) -> tuple[str, list[Any]]:
    if not series:
        return "", []
    exact = [s for s in series if "*" not in s]
    patterns = [s.replace("%", r"\%").replace("_", r"\_").replace("*", "%") for s in series]
    patterns = [p for p, s in zip(patterns, series, strict=True) if "*" in s]
    clauses = []
    if exact:
        clauses.append(f"series IN ({', '.join('?' for _ in exact)})")
    clauses += ["series LIKE ? ESCAPE '\\'" for _ in patterns]
    return f"AND ({' OR '.join(clauses)})", [*exact, *patterns]


def _empty(columns: tuple[str, ...]) -> pa.Table:
    fields = {f.name: f for f in FORECAST_SCHEMA}
    return pa.schema([fields[c] for c in columns]).empty_table()
