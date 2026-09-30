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
from datetime import UTC, datetime
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


def _check_entry(entry: dict[str, Any], point: Point, product: Product) -> dict[str, Any]:
    """The entry's ``hourly`` block, after checking it is the point and variables we asked for."""
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
    extra = set(hourly) - {"time", *product.variables}
    if extra:
        msg = f"undeclared variables in the response: {sorted(extra)}"
        raise SchemaDriftError(msg)
    for var, unit in product.variables.items():
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


def to_table(  # noqa: PLR0913  (keyword-only after the inputs)
    body: bytes | Sequence[Any],
    product: Product,
    points: Sequence[tuple[str, Point]],
    *,
    posted_at: datetime,
    ingested_at: datetime,
    source: str,
) -> Transformed:
    entries = _entries(body)
    if len(entries) != len(points):
        msg = f"{len(entries)} points in the response, {len(points)} requested"
        raise SchemaDriftError(msg)

    times: list[int] | None = None
    by_zone: dict[str, list[dict[str, list[float | None]]]] = {}
    for entry, (zone, point) in zip(entries, points, strict=True):
        hourly = _check_entry(entry, point, product)
        if times is None:
            times = list(hourly["time"])
        elif list(hourly["time"]) != times:
            msg = f"{point.name} has different valid times from the first point"
            raise SchemaDriftError(msg)
        by_zone.setdefault(zone, []).append({v: hourly[v] for v in product.variables})
    assert times is not None  # points is non-empty (the settings require it)

    rows: dict[str, list[Any]] = {name: [] for name in FORECAST_SCHEMA.names}
    dropped = 0
    for zone, members in by_zone.items():
        for var in product.variables:
            name = series_name(var, zone)
            for i, t in enumerate(times):
                values = [v for m in members if (v := m[var][i]) is not None and math.isfinite(v)]
                if len(values) < len(members):
                    dropped += 1
                    continue
                rows["interval_start"].append(datetime.fromtimestamp(t, UTC))
                rows["series"].append(name)
                rows["value"].append(sum(values) / len(values))
    n = len(rows["series"])
    rows["interval_minutes"] = [60] * n
    rows["posted_at"] = [posted_at] * n
    rows["ingested_at"] = [ingested_at] * n
    rows["source"] = [source] * n
    rows["schema_version"] = [SCHEMA_VERSION] * n
    return Transformed(pa.Table.from_pydict(rows, schema=FORECAST_SCHEMA), dropped)
