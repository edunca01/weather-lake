from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ingest import cli
from ingest.backfill import backfill, coverage_key, windows
from ingest.config import Settings
from ingest.lake import Lake
from weather_lake.contract import previous_runs_key

from .conftest import PRODUCT

NOW = datetime(2026, 10, 1, 19, tzinfo=UTC)


def _body(settings: Settings, first: date, last: date, *, hole: bool = False) -> bytes:
    """A synthetic Previous Runs response: value = lead days * 10 + point index."""
    product = settings.product(PRODUCT)
    assert product.backfill is not None
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    hours = ((last - first).days + 1) * 24
    times = [int((start + timedelta(hours=h)).timestamp()) for h in range(hours)]
    entries = []
    for i, (_, p) in enumerate(settings.points()):
        units, hourly = {"time": "unixtime"}, {"time": times}
        for n in product.backfill.lead_days:
            for var, unit in product.variables.items():
                col = f"{var}_previous_day{n}"
                units[col] = unit
                hourly[col] = [float(n * 10 + i)] * hours
        entry = {"latitude": p.lat, "longitude": p.lon, "hourly_units": units, "hourly": hourly}
        entries.append(entry)
    if hole:
        entries[0]["hourly"]["temperature_2m_previous_day1"][0] = None
    return json.dumps(entries).encode()


def test_windows_cover_the_range_without_overlap() -> None:
    w = windows(date(2024, 1, 1), date(2024, 1, 31), 14)
    assert w == [
        (date(2024, 1, 1), date(2024, 1, 14)),
        (date(2024, 1, 15), date(2024, 1, 28)),
        (date(2024, 1, 29), date(2024, 1, 31)),
    ]


def test_backfill_posted_at_is_valid_time_minus_lead_plus_lag(
    settings: Settings, lake: Lake
) -> None:
    first = last = date(2024, 3, 2)
    s = backfill(
        settings, PRODUCT, lake, lambda f, t: _body(settings, f, t), first, last, now=lambda: NOW
    )
    assert (s.windows, s.dropped, s.rows) == (1, 0, 24 * 9 * 8 * 7)
    rows = lake.read_table(previous_runs_key(PRODUCT, first)).to_pylist()
    row = next(
        r
        for r in rows
        if r["series"] == "temperature_2m:Coast"
        and r["interval_start"] == datetime(2024, 3, 2, 12, tzinfo=UTC)
        and r["value"] == 30.0 + 1.0  # lead 3, mean of Coast's points 0, 1, 2
    )
    assert row["posted_at"] == datetime(2024, 2, 28, 13, tzinfo=UTC)  # 3 days early, +1 h lag
    assert row["source"] == "previous_runs" and row["ingested_at"] == NOW
    assert all(r["posted_at"] < r["interval_start"] for r in rows)
    assert lake.list_keys("raw/")  # the response is kept
    assert "2024-03-02_2024-03-02" in lake.read_json(coverage_key(PRODUCT))["windows"]


def test_rerunning_a_window_overwrites_its_days(settings: Settings, lake: Lake) -> None:
    d = date(2024, 3, 2)
    for _ in range(2):
        backfill(settings, PRODUCT, lake, lambda f, t: _body(settings, f, t), d, d, now=lambda: NOW)
    assert lake.list_keys(f"curated/{PRODUCT}/") == [previous_runs_key(PRODUCT, d)]


def test_archive_gaps_are_dropped_and_counted(settings: Settings, lake: Lake) -> None:
    d = date(2024, 3, 2)
    holed = lambda f, t: _body(settings, f, t, hole=True)  # noqa: E731
    s = backfill(settings, PRODUCT, lake, holed, d, d, now=lambda: NOW)
    assert s.dropped == 1


def test_bad_ranges(settings: Settings, lake: Lake) -> None:
    with pytest.raises(ValueError, match="before 2024-01-01"):
        backfill(
            settings,
            PRODUCT,
            lake,
            lambda f, t: b"",
            date(2023, 1, 1),
            date(2023, 1, 2),
            now=lambda: NOW,
        )
    with pytest.raises(ValueError, match="empty"):
        backfill(
            settings,
            PRODUCT,
            lake,
            lambda f, t: b"",
            date(2024, 2, 2),
            date(2024, 2, 1),
            now=lambda: NOW,
        )


def test_the_cli(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[Any, ...]] = []

    class Client:
        def __init__(self, cfg: Any) -> None: ...
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *exc: object) -> None: ...
        def previous_runs(self, product: Any, points: Any, leads: Any, f: date, t: date) -> bytes:
            calls.append((f, t, tuple(leads)))
            return _body(settings, f, t)

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "OpenMeteoClient", Client)
    assert (
        cli.main_backfill(
            ["--product", PRODUCT, "--from", "2024-03-01", "--to", "2024-03-02", "--pause", "0"]
        )
        == 0
    )
    assert calls == [(date(2024, 3, 1), date(2024, 3, 2), (1, 2, 3, 4, 5, 6, 7))]
    assert json.loads(capsys.readouterr().out)["days"] == 2
    assert gzip.decompress(Lake(settings.lake).read_bytes(Lake(settings.lake).list_keys("raw/")[0]))
