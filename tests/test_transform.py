from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from ingest.config import Settings
from ingest.transform import SchemaDriftError, to_table
from weather_lake.contract import FORECAST_SCHEMA

from .conftest import PRODUCT

T = datetime(2026, 9, 30, 20, 25, tzinfo=UTC)


def _run(settings: Settings, body: Any) -> Any:
    product = settings.product(PRODUCT)
    return to_table(body, product, settings.points(), posted_at=T, ingested_at=T, source="live")


def test_zone_means_from_the_sample(settings: Settings, sample: list[dict[str, Any]]) -> None:
    out = _run(settings, json.dumps(sample).encode())
    product = settings.product(PRODUCT)
    hours = len(sample[0]["hourly"]["time"])
    assert out.table.schema == FORECAST_SCHEMA
    assert out.table.num_rows == hours * len(product.variables) * len(settings.zones)
    assert out.dropped == 0
    # Coast is the mean of its three points, first hour, first variable.
    rows = out.table.to_pylist()
    first = next(r for r in rows if r["series"] == "temperature_2m:Coast")
    coast = [sample[i]["hourly"]["temperature_2m"][0] for i in range(3)]
    assert first["value"] == pytest.approx(sum(coast) / 3)
    assert first["interval_start"] == datetime.fromtimestamp(sample[0]["hourly"]["time"][0], UTC)
    assert {r["posted_at"] for r in rows} == {T}
    zones = {r["series"].split(":")[1] for r in rows}
    assert zones == {
        "Coast",
        "East",
        "FarWest",
        "North",
        "NorthCentral",
        "SouthCentral",
        "Southern",
        "West",
    }  # the ERCOT lake's load-series zone names


def test_a_missing_point_value_drops_the_zone_hour(
    settings: Settings, sample: list[dict[str, Any]]
) -> None:
    sample[1]["hourly"]["temperature_2m"][0] = None  # Galveston, a Coast point
    out = _run(settings, sample)
    series = [(r["series"], r["interval_start"]) for r in out.table.to_pylist()]
    first = datetime.fromtimestamp(sample[0]["hourly"]["time"][0], UTC)
    assert ("temperature_2m:Coast", first) not in series
    assert out.dropped == 1


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s.pop(), "points in the response"),
        (lambda s: s[0].update(latitude=40.0), "not \\("),
        (lambda s: s[0]["hourly"].pop("cloud_cover"), "cloud_cover missing"),
        (lambda s: s[0]["hourly"].update(snowfall=[0.0] * 6), "undeclared variables"),
        (lambda s: s[0]["hourly_units"].update(wind_speed_10m="km/h"), "declared"),
        (lambda s: s[0]["hourly_units"].update(time="iso8601"), "unixtime"),
        (lambda s: s[3]["hourly"].update(time=s[3]["hourly"]["time"][1:]), "different valid"),
    ],
)
def test_drift_fails_loudly(
    settings: Settings, sample: list[dict[str, Any]], mutate: Any, match: str
) -> None:
    mutate(sample)
    with pytest.raises(SchemaDriftError, match=match):
        _run(settings, sample)


def test_a_single_object_response_is_a_one_point_list(settings: Settings) -> None:
    with pytest.raises(SchemaDriftError, match="points in the response"):
        _run(settings, b'{"latitude": 1}')
    with pytest.raises(SchemaDriftError, match="neither"):
        _run(settings, b'"text"')
