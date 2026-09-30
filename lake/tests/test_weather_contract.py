from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from weather_lake import contract as c

T = datetime(2026, 9, 30, 20, 25, 3, tzinfo=UTC)


def test_keys() -> None:
    p = "openmeteo-gfs-seamless"
    assert c.raw_key(p, T) == (
        "raw/openmeteo-gfs-seamless/date=2026-09-30/fetched=20260930T202503Z.json.gz"
    )
    assert c.curated_key(p, date(2026, 10, 1), T) == (
        "curated/openmeteo-gfs-seamless/date=2026-10-01/part-20260930T202503Z.parquet"
    )
    assert c.merged_key(p, date(2026, 10, 1), T).endswith("/merged-20260930T202503Z.parquet")
    assert c.manifest_key(p) == "manifests/openmeteo-gfs-seamless/latest.json"
    assert c.series_name("temperature_2m", "NorthCentral") == "temperature_2m:NorthCentral"


def test_raw_is_partitioned_by_utc_fetch_date() -> None:
    late = datetime(2026, 9, 30, 23, 30, tzinfo=timezone(timedelta(hours=-5))).astimezone(UTC)
    assert "/date=2026-10-01/" in c.raw_key("x", late)


@pytest.mark.parametrize("bad", ["Upper", "under_score", "trailing-", "a b", ""])
def test_product_keys_are_checked(bad: str) -> None:
    with pytest.raises(ValueError, match="product key"):
        c.manifest_key(bad)


def test_stamp_needs_utc() -> None:
    with pytest.raises(ValueError, match="UTC"):
        c.stamp(datetime(2026, 9, 30, 12))


def test_schema_and_key() -> None:
    assert c.BUSINESS_KEY == ("interval_start", "series")
    assert all(not f.nullable for f in c.FORECAST_SCHEMA)
    assert set(c.BUSINESS_KEY) <= set(c.FORECAST_SCHEMA.names)
