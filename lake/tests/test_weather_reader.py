"""Golden point-in-time cases on a small hand-built lake."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from weather_lake import (
    CatalogNotFoundError,
    IncompatibleContractError,
    UnknownProductError,
    UnsupportedSchemaVersionError,
    WeatherReader,
)
from weather_lake.contract import CATALOG_KEY, FORECAST_SCHEMA, curated_key

P = "openmeteo-gfs-seamless"
H0 = datetime(2026, 10, 1, 12, tzinfo=UTC)  # a valid hour
T1 = datetime(2026, 10, 1, 6, tzinfo=UTC)  # first posting
T2 = datetime(2026, 10, 1, 9, tzinfo=UTC)  # revision


def _catalog(version: str = "0.1.0", schema_version: int = 1) -> dict[str, Any]:
    return {
        "contract_version": version,
        "generated_at": T1.isoformat(),
        "products": {
            P: {
                "name": "test",
                "source": "open-meteo",
                "model": "gfs_seamless",
                "interval_minutes": 60,
                "schema_version": schema_version,
                "variables": {"temperature_2m": "°C"},
                "zones": {"Coast": [{"name": "Houston", "lat": 29.76, "lon": -95.37}]},
                "live": True,
            }
        },
    }


def _posting(root: Path, posted: datetime, values: dict[tuple[datetime, str], float]) -> None:
    by_day: dict[date, list[dict[str, Any]]] = {}
    for (start, series), value in values.items():
        by_day.setdefault(start.date(), []).append(
            {
                "interval_start": start,
                "interval_minutes": 60,
                "posted_at": posted,
                "ingested_at": posted + timedelta(seconds=5),
                "source": "live",
                "schema_version": 1,
                "series": series,
                "value": value,
            }
        )
    for day, rows in by_day.items():
        path = root / curated_key(P, day, posted)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=FORECAST_SCHEMA), path)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / CATALOG_KEY).parent.mkdir(parents=True)
    (tmp_path / CATALOG_KEY).write_text(json.dumps(_catalog()))
    _posting(
        tmp_path,
        T1,
        {
            (H0, "temperature_2m:Coast"): 30.0,
            (H0, "wind_speed_10m:Coast"): 5.0,
            (H0 + timedelta(hours=13), "temperature_2m:Coast"): 20.0,  # next UTC day
        },
    )
    _posting(tmp_path, T2, {(H0, "temperature_2m:Coast"): 31.0})
    return tmp_path


def _values(t: pa.Table) -> list[tuple[Any, ...]]:
    return [(r["interval_start"], r["series"], r["value"]) for r in t.to_pylist()]


def test_nothing_is_known_before_the_first_posting(root: Path) -> None:
    with WeatherReader(root) as r:
        got = r.snapshot(P, H0, H0 + timedelta(days=1), as_of=T1 - timedelta(seconds=1))
    assert got.num_rows == 0


def test_a_revision_is_invisible_until_it_is_posted(root: Path) -> None:
    window = (H0, H0 + timedelta(days=1))
    with WeatherReader(root) as r:
        before = _values(r.snapshot(P, *window, as_of=T2 - timedelta(seconds=1)))
        after = _values(r.snapshot(P, *window, as_of=T2))
    assert (H0, "temperature_2m:Coast", 30.0) in before
    assert (H0, "temperature_2m:Coast", 31.0) in after
    assert (H0, "wind_speed_10m:Coast", 5.0) in after  # unrevised series still visible
    assert len(after) == 3  # one row per (interval_start, series)


def test_series_filter_with_wildcards(root: Path) -> None:
    with WeatherReader(root) as r:
        temps = r.snapshot(P, H0, H0 + timedelta(days=1), as_of=T2, series=["temperature_2m:*"])
        wind = ["wind_speed_10m:Coast"]
        exact = r.snapshot(P, H0, H0 + timedelta(hours=1), as_of=T2, series=wind)
    assert {s for _, s, _ in _values(temps)} == {"temperature_2m:Coast"}
    assert _values(exact) == [(H0, "wind_speed_10m:Coast", 5.0)]


def test_postings_keep_every_version_for_as_of_joins(root: Path) -> None:
    with WeatherReader(root) as r:
        got = r.postings(
            P, H0, H0 + timedelta(hours=1), as_of=T2, series=["temperature_2m:Coast"]
        ).to_pylist()
    assert [(g["posted_at"], g["value"]) for g in got] == [(T1, 30.0), (T2, 31.0)]
    assert {"ingested_at", "source"} <= set(got[0])


def test_end_is_exclusive_and_empty_ranges_have_the_schema(root: Path) -> None:
    with WeatherReader(root) as r:
        one = r.snapshot(P, H0, H0 + timedelta(hours=1), as_of=T2)
        none = r.snapshot(P, H0 + timedelta(days=5), H0 + timedelta(days=6), as_of=T2)
        none_p = r.postings(P, H0 + timedelta(days=5), H0 + timedelta(days=6), as_of=T2)
    assert {row["interval_start"] for row in one.to_pylist()} == {H0}
    assert none.num_rows == 0 and "value" in none.schema.names
    assert none_p.num_rows == 0 and "source" in none_p.schema.names


def test_guards(root: Path, tmp_path: Path) -> None:
    with WeatherReader(root, max_days=2) as r:
        assert r.products() == [P]
        with pytest.raises(ValueError, match="timezone-aware"):
            r.snapshot(P, H0, H0 + timedelta(hours=1), as_of=datetime(2026, 10, 1))
        with pytest.raises(ValueError, match="empty interval"):
            r.snapshot(P, H0, H0, as_of=T2)
        with pytest.raises(ValueError, match="longer than"):
            r.snapshot(P, H0, H0 + timedelta(days=5), as_of=T2)
        with pytest.raises(UnknownProductError):
            r.snapshot("nope", H0, H0 + timedelta(hours=1), as_of=T2)
    with pytest.raises(ValueError, match="region"):
        WeatherReader(root, region="nowhere")
    with WeatherReader(tmp_path / "empty") as r, pytest.raises(CatalogNotFoundError):
        r.products()


@pytest.mark.parametrize(
    ("catalog", "error"),
    [
        (_catalog(version="0.2.0"), IncompatibleContractError),
        (_catalog(version="1.0.0"), IncompatibleContractError),
        (_catalog(schema_version=9), UnsupportedSchemaVersionError),
    ],
)
def test_incompatible_lakes_are_refused(root: Path, catalog: dict[str, Any], error: type) -> None:
    (root / CATALOG_KEY).write_text(json.dumps(catalog))
    with WeatherReader(root) as r, pytest.raises(error):
        r.snapshot(P, H0, H0 + timedelta(hours=1), as_of=T2)


def test_unknown_row_schema_versions_are_refused(root: Path) -> None:
    rows = [
        {**r, "schema_version": 9}
        for r in pq.read_table(root / curated_key(P, H0.date(), T2)).to_pylist()
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=FORECAST_SCHEMA), root / curated_key(P, H0.date(), T2)
    )
    with WeatherReader(root) as r, pytest.raises(UnsupportedSchemaVersionError):
        r.snapshot(P, H0, H0 + timedelta(hours=1), as_of=T2)


def test_s3_setup_sql_names_the_region() -> None:
    from weather_lake.reader import s3_setup_sql  # noqa: PLC0415

    assert "REGION 'us-east-2'" in s3_setup_sql("us-east-2")[-1]
    assert "REGION" not in s3_setup_sql(None)[-1]
