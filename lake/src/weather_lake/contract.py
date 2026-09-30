"""The lake contract as code: layout, key formats, the curated schema and its business key.

The pipeline builds every key with these functions and readers dedupe on this business key,
so writer and reader cannot drift apart. Any change here is a contract change: bump
``SCHEMA_VERSION`` when the table's columns change, and ``CONTRACT_VERSION`` (SemVer) always.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Final

import pyarrow as pa

CONTRACT_VERSION: Final = "0.1.0"

# Stored on every curated row. Readers accept the versions they know how to read and refuse
# anything newer rather than guess at its columns.
SCHEMA_VERSION: Final = 1
SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({1})

# Partitions are UTC dates: weather has no settlement day, and UTC has no DST to get wrong.
RAW_PREFIX: Final = "raw"
CURATED_PREFIX: Final = "curated"
MANIFESTS_PREFIX: Final = "manifests"
CATALOG_KEY: Final = f"{MANIFESTS_PREFIX}/_catalog.json"

# `live`: polled forecasts, posted_at = fetch time. `previous_runs`: backfilled vintages,
# posted_at = the latest moment the forecast could have been known.
SOURCES: Final = frozenset({"live", "previous_runs"})

_TS = pa.timestamp("us", tz="UTC")

# One row per valid hour and series. ``series`` is ``<variable>:<Zone>``, e.g.
# ``temperature_2m:NorthCentral``, with the zone names of the ERCOT lake's load series so the
# two join on (interval_start, zone) with no mapping.
_FIELDS: Final[list[pa.Field[pa.DataType]]] = [
    pa.field("interval_start", _TS, nullable=False),
    pa.field("interval_minutes", pa.int32(), nullable=False),
    pa.field("posted_at", _TS, nullable=False),
    pa.field("ingested_at", _TS, nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("schema_version", pa.int32(), nullable=False),
    pa.field("series", pa.string(), nullable=False),
    pa.field("value", pa.float64(), nullable=False),
]
FORECAST_SCHEMA: Final = pa.schema(_FIELDS)

# Readers keep, per business key, the row with the greatest posted_at <= as_of.
BUSINESS_KEY: Final = ("interval_start", "series")

# Product keys become path segments: lower-case words joined by hyphens.
_PRODUCT = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _product(product: str) -> str:
    if not _PRODUCT.fullmatch(product):
        msg = f"not a lower-case, hyphenated product key: {product!r}"
        raise ValueError(msg)
    return product


def stamp(ts_utc: datetime) -> str:
    """Basic ISO 8601 for object keys, ``20260930T202500Z``: sortable and free of colons."""
    if ts_utc.tzinfo is None or ts_utc.utcoffset() != timedelta(0):
        msg = "stamp() expects a UTC datetime"
        raise ValueError(msg)
    return ts_utc.strftime("%Y%m%dT%H%M%SZ")


def utc_date(ts_utc: datetime) -> date:
    return ts_utc.astimezone(UTC).date()


def raw_key(product: str, fetched_at: datetime) -> str:
    """The response exactly as received, gzipped, keyed by fetch time."""
    return (
        f"{RAW_PREFIX}/{_product(product)}/date={utc_date(fetched_at).isoformat()}"
        f"/fetched={stamp(fetched_at)}.json.gz"
    )


def curated_partition(product: str, valid_date: date) -> str:
    """The prefix of one curated partition, with a trailing slash. Readers list one per day
    instead of globbing ``date=*``, which on S3 lists the whole product."""
    return f"{CURATED_PREFIX}/{_product(product)}/date={valid_date.isoformat()}/"


def curated_key(product: str, valid_date: date, posted_at: datetime) -> str:
    """One posting's rows for one valid day. Same posting, same key: re-runs overwrite."""
    return f"{curated_partition(product, valid_date)}part-{stamp(posted_at)}.parquet"


def merged_key(product: str, valid_date: date, compacted_at: datetime) -> str:
    """Compaction output: replaces a partition's ``part-`` files without changing a row."""
    return f"{curated_partition(product, valid_date)}merged-{stamp(compacted_at)}.parquet"


def manifest_key(product: str) -> str:
    return f"{MANIFESTS_PREFIX}/{_product(product)}/latest.json"


def series_name(variable: str, zone: str) -> str:
    return f"{variable}:{zone}"
