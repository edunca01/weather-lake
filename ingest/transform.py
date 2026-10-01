"""An Open-Meteo multi-point response -> zone means in the curated ``forecast`` schema.

Declared variables and units are exhaustive: anything unexpected raises ``SchemaDriftError``
instead of being coerced. A zone value is the equal-weight mean of all its points; if any
point is missing that hour, the zone value is dropped and counted, never averaged over fewer
points (that would quietly change what the value means).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa

from ingest.config import Point, Product
from weather_lake.contract import FORECAST_SCHEMA, SCHEMA_VERSION, series_name

# Open-Meteo snaps each point to its model grid; farther than this means the response is not
# for the point we asked about.
_MAX_SNAP_DEG = 0.25


class SchemaDriftError(RuntimeError):
    """The response does not match what the configuration declares."""


@dataclass(frozen=True)
class Transformed:
    table: pa.Table
    dropped: int  # zone-hours dropped because a point had no value


def _entries(body: bytes | Sequence[Any]) -> list[dict[str, Any]]:
    data = json.loads(body) if isinstance(body, bytes) else body
    if isinstance(data, dict):  # a single point comes back as an object, not a list
        data = [data]
    if not isinstance(data, list):
        msg = "response is neither an object nor a list"
        raise SchemaDriftError(msg)
    return data


def _check_entry(entry: dict[str, Any], point: Point, expected: dict[str, str]) -> dict[str, Any]:
    """The entry's ``hourly`` block, after checking it is the point and the variables (with
    their units) we asked for."""
    lat, lon = entry.get("latitude"), entry.get("longitude")
    if (
        not isinstance(lat, int | float)
        or not isinstance(lon, int | float)
        or abs(lat - point.lat) > _MAX_SNAP_DEG
        or abs(lon - point.lon) > _MAX_SNAP_DEG
    ):
        msg = f"response for {point.name} is at ({lat}, {lon}), not ({point.lat}, {point.lon})"
        raise SchemaDriftError(msg)
    units = entry.get("hourly_units", {})
    hourly: dict[str, Any] = entry.get("hourly", {})
    extra = set(hourly) - {"time", *expected}
    if extra:
        msg = f"undeclared variables in the response: {sorted(extra)}"
        raise SchemaDriftError(msg)
    for var, unit in expected.items():
        if var not in hourly:
            msg = f"{var} missing for {point.name}"
            raise SchemaDriftError(msg)
        if units.get(var) != unit:
            msg = f"{var} is in {units.get(var)!r}, declared {unit!r}"
            raise SchemaDriftError(msg)
    if units.get("time") != "unixtime":
        msg = f"time is {units.get('time')!r}, expected unixtime"
        raise SchemaDriftError(msg)
    return hourly


def _zone_members(
    body: bytes | Sequence[Any],
    points: Sequence[tuple[str, Point]],
    expected: dict[str, str],
) -> tuple[list[int], dict[str, list[dict[str, list[float | None]]]]]:
    """Valid times, and per zone the hourly values of each member point, after every check."""
    entries = _entries(body)
    if len(entries) != len(points):
        msg = f"{len(entries)} points in the response, {len(points)} requested"
        raise SchemaDriftError(msg)
    times: list[int] | None = None
    by_zone: dict[str, list[dict[str, list[float | None]]]] = {}
    for entry, (zone, point) in zip(entries, points, strict=True):
        hourly = _check_entry(entry, point, expected)
        if times is None:
            times = list(hourly["time"])
        elif list(hourly["time"]) != times:
            msg = f"{point.name} has different valid times from the first point"
            raise SchemaDriftError(msg)
        by_zone.setdefault(zone, []).append({v: hourly[v] for v in expected})
    assert times is not None  # points is non-empty (the settings require it)
    return times, by_zone


def _mean(members: list[dict[str, list[float | None]]], column: str, i: int) -> float | None:
    """The zone value, or None when any member point lacks one (never a mean of fewer)."""
    values = [v for m in members if (v := m[column][i]) is not None and math.isfinite(v)]
    return sum(values) / len(values) if len(values) == len(members) else None


def _table(rows: dict[str, list[Any]], *, ingested_at: datetime, source: str) -> pa.Table:
    n = len(rows["series"])
    rows["interval_minutes"] = [60] * n
    rows["ingested_at"] = [ingested_at] * n
    rows["source"] = [source] * n
    rows["schema_version"] = [SCHEMA_VERSION] * n
    return pa.Table.from_pydict(rows, schema=FORECAST_SCHEMA)


def to_table(  # noqa: PLR0913  (keyword-only after the inputs)
    body: bytes | Sequence[Any],
    product: Product,
    points: Sequence[tuple[str, Point]],
    *,
    posted_at: datetime,
    ingested_at: datetime,
    source: str,
) -> Transformed:
    """A live forecast: every row was known at ``posted_at`` (the fetch time)."""
    times, by_zone = _zone_members(body, points, product.variables)
    rows: dict[str, list[Any]] = {c: [] for c in ("interval_start", "posted_at", "series", "value")}
    dropped = 0
    for zone, members in by_zone.items():
        for var in product.variables:
            name = series_name(var, zone)
            for i, t in enumerate(times):
                value = _mean(members, var, i)
                if value is None:
                    dropped += 1
                    continue
                rows["interval_start"].append(datetime.fromtimestamp(t, UTC))
                rows["posted_at"].append(posted_at)
                rows["series"].append(name)
                rows["value"].append(value)
    return Transformed(_table(rows, ingested_at=ingested_at, source=source), dropped)


def to_previous_runs_table(  # noqa: PLR0913  (keyword-only after the inputs)
    body: bytes | Sequence[Any],
    product: Product,
    points: Sequence[tuple[str, Point]],
    *,
    lead_days: Sequence[int],
    publication_lag: timedelta,
    ingested_at: datetime,
) -> Transformed:
    """Past vintages: ``<variable>_previous_dayN`` at valid time t was predicted N x 24 h
    before t, so its ``posted_at`` is ``t - N days + publication_lag``. Gaps in the archive
    (nulls) are dropped and counted like a missing point."""
    expected = {
        f"{var}_previous_day{n}": unit for n in lead_days for var, unit in product.variables.items()
    }
    times, by_zone = _zone_members(body, points, expected)
    rows: dict[str, list[Any]] = {c: [] for c in ("interval_start", "posted_at", "series", "value")}
    dropped = 0
    for zone, members in by_zone.items():
        for n in lead_days:
            for var in product.variables:
                name, column = series_name(var, zone), f"{var}_previous_day{n}"
                for i, t in enumerate(times):
                    value = _mean(members, column, i)
                    if value is None:
                        dropped += 1
                        continue
                    valid = datetime.fromtimestamp(t, UTC)
                    rows["interval_start"].append(valid)
                    rows["posted_at"].append(valid - timedelta(days=n) + publication_lag)
                    rows["series"].append(name)
                    rows["value"].append(value)
    return Transformed(_table(rows, ingested_at=ingested_at, source="previous_runs"), dropped)
