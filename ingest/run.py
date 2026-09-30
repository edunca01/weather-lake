"""One poll of one product: raw first, curated only when the forecast changed, then manifest.

A poll whose forecast content equals the latest posting's is not a new posting: nothing new was
known, so no curated rows are written and ``posted_at`` stays at the time the content first
appeared. The manifest records the check either way, which is what freshness measures.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from ingest.config import Settings
from ingest.lake import Lake
from ingest.transform import to_table
from weather_lake.contract import (
    BUSINESS_KEY,
    SCHEMA_VERSION,
    curated_key,
    manifest_key,
    raw_key,
)

log = logging.getLogger(__name__)

Fetch = Callable[[], bytes]


@dataclass
class PollSummary:
    product: str
    fetched_at: datetime
    new_posting: bool = False
    posted_at: datetime | None = None  # the newest posting after this poll
    rows: int = 0
    dropped: int = 0
    partitions: list[str] = field(default_factory=list)

    def age_minutes(self, now: datetime) -> float | None:
        return (now - self.posted_at).total_seconds() / 60 if self.posted_at else None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat()
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return d


def content_hash(table: pa.Table) -> str:
    """What was forecast, independent of when it was fetched or written."""
    ordered = table.select(["interval_start", "series", "value"]).sort_by(
        [(c, "ascending") for c in BUSINESS_KEY]
    )
    digest = hashlib.sha256()
    for col in ordered.columns:
        digest.update(repr(col.to_pylist()).encode())
    return digest.hexdigest()


def _check_unique_keys(table: pa.Table) -> None:
    keys = table.group_by(list(BUSINESS_KEY)).aggregate([([], "count_all")])
    if keys.num_rows != table.num_rows:
        msg = "a business key repeats within one posting"
        raise ValueError(msg)


def poll(
    settings: Settings, product_key: str, lake: Lake, fetch: Fetch, *, now: datetime
) -> PollSummary:
    product = settings.product(product_key)
    summary = PollSummary(product=product.key, fetched_at=now)

    body = fetch()
    lake.write_bytes(raw_key(product.key, now), gzip.compress(body, mtime=0))

    result = to_table(
        body, product, settings.points(), posted_at=now, ingested_at=now, source="live"
    )
    table = result.table
    _check_unique_keys(table)
    summary.rows, summary.dropped = table.num_rows, result.dropped
    digest = content_hash(table)

    key = manifest_key(product.key)
    prev = lake.read_json(key) if lake.exists(key) else {}
    if prev.get("content_hash") == digest:
        summary.posted_at = datetime.fromisoformat(prev["last_posted_at"])
        manifest = {**prev, "last_checked_at": now}
        log.info("%s: forecast unchanged since %s", product.key, prev["last_posted_at"])
    else:
        valid_days = pc.cast(table.column("interval_start"), pa.date32())
        days = sorted(d for d in pc.unique(valid_days).to_pylist() if d is not None)
        for day in days:
            mask = pc.equal(valid_days, pa.scalar(day, pa.date32()))
            lake.write_table(curated_key(product.key, day, now), table.filter(mask))
            summary.partitions.append(day.isoformat())
        summary.new_posting, summary.posted_at = True, now
        manifest = {
            "product": product.key,
            "model": product.model,
            "schema_version": SCHEMA_VERSION,
            "last_posted_at": now,
            "last_checked_at": now,
            "content_hash": digest,
            "rows": table.num_rows,
            "dropped": result.dropped,
            "valid_from": pc.min(table.column("interval_start")).as_py(),
            "valid_to": pc.max(table.column("interval_start")).as_py(),
            "partitions": summary.partitions,
            "raw_key": raw_key(product.key, now),
        }
        log.info(
            "%s: new posting, %d rows in %d partitions (%d zone-hours dropped)",
            product.key,
            table.num_rows,
            len(summary.partitions),
            result.dropped,
        )
    lake.write_json(key, manifest)
    return summary
