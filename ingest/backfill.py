"""Backfill past vintages from Open-Meteo's Previous Runs API, window by window.

Each window is one request: the response is kept raw, then each valid day's rows are written to
that day's ``previous-runs.parquet`` (windows never share a valid day, so a re-run overwrites
the same files). ``manifests/<product>/previous_runs.json`` records the windows done.
The live manifest is not touched: freshness measures live polling, not history.
"""

from __future__ import annotations

import gzip
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from ingest.config import Settings
from ingest.lake import Lake
from ingest.transform import to_previous_runs_table
from weather_lake.contract import (
    BUSINESS_KEY,
    MANIFESTS_PREFIX,
    previous_runs_key,
    raw_previous_runs_key,
)

log = logging.getLogger(__name__)

FetchWindow = Callable[[date, date], bytes]


@dataclass
class BackfillSummary:
    product: str
    first: date
    last: date
    windows: int = 0
    rows: int = 0
    dropped: int = 0
    days: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "first": self.first.isoformat(),
            "last": self.last.isoformat(),
            "windows": self.windows,
            "rows": self.rows,
            "dropped": self.dropped,
            "days": len(self.days),
        }


def windows(first: date, last: date, size: int) -> list[tuple[date, date]]:
    """Consecutive, non-overlapping valid-day windows covering ``first..last``."""
    out, start = [], first
    while start <= last:
        end = min(start + timedelta(days=size - 1), last)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def coverage_key(product: str) -> str:
    return f"{MANIFESTS_PREFIX}/{product}/previous_runs.json"


def backfill(  # noqa: PLR0913, PLR0917  (the range is positional, like the CLI's)
    settings: Settings,
    product_key: str,
    lake: Lake,
    fetch: FetchWindow,
    first: date,
    last: date,
    *,
    now: Callable[[], datetime],
    pause_s: float = 0.0,
) -> BackfillSummary:
    product = settings.product(product_key)
    if product.backfill is None:
        msg = f"{product.key} declares no backfill"
        raise ValueError(msg)
    cfg = product.backfill
    if first < cfg.earliest or last < first:
        msg = f"backfill {first}..{last} is empty or before {cfg.earliest}"
        raise ValueError(msg)
    summary = BackfillSummary(product.key, first, last)
    for i, (w_first, w_last) in enumerate(windows(first, last, cfg.window_days)):
        if i and pause_s:
            time.sleep(pause_s)  # stay well inside Open-Meteo's per-minute limit
        fetched = now()
        body = fetch(w_first, w_last)
        raw = raw_previous_runs_key(product.key, fetched, w_first, w_last)
        lake.write_bytes(raw, gzip.compress(body, mtime=0))
        result = to_previous_runs_table(
            body,
            product,
            settings.points(),
            lead_days=cfg.lead_days,
            publication_lag=timedelta(minutes=cfg.publication_lag_min),
            ingested_at=fetched,
        )
        table = result.table
        if table.group_by([*BUSINESS_KEY, "posted_at"]).aggregate([([], "count_all")]).num_rows != (
            table.num_rows
        ):
            msg = "a business key repeats within one posting"
            raise ValueError(msg)
        valid_days = pc.cast(table.column("interval_start"), pa.date32())
        for day in sorted(d for d in pc.unique(valid_days).to_pylist() if d is not None):
            mask = pc.equal(valid_days, pa.scalar(day, pa.date32()))
            lake.write_table(previous_runs_key(product.key, day), table.filter(mask))
            summary.days.append(day.isoformat())
        summary.windows += 1
        summary.rows += table.num_rows
        summary.dropped += result.dropped
        _record(
            lake,
            product.key,
            w_first,
            w_last,
            at=fetched,
            rows=table.num_rows,
            dropped=result.dropped,
        )
        log.info(
            "%s: previous runs %s..%s, %d rows (%d zone-hours missing in the archive)",
            product.key,
            w_first,
            w_last,
            table.num_rows,
            result.dropped,
        )
    return summary


def _record(  # noqa: PLR0913
    lake: Lake, product: str, first: date, last: date, *, at: datetime, rows: int, dropped: int
) -> None:
    key = coverage_key(product)
    done: dict[str, Any] = lake.read_json(key) if lake.exists(key) else {"windows": {}}
    done["windows"][f"{first.isoformat()}_{last.isoformat()}"] = {
        "fetched_at": at,
        "rows": rows,
        "dropped": dropped,
    }
    lake.write_json(key, done)
