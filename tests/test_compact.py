from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from ingest import handler
from ingest.compact import compact, compact_product
from ingest.config import Settings
from ingest.lake import Lake
from weather_lake import WeatherReader
from weather_lake.contract import FORECAST_SCHEMA, curated_key, merged_key, previous_runs_key

from .conftest import PRODUCT

DAY = date(2026, 10, 1)
H = datetime(2026, 10, 1, 12, tzinfo=UTC)
NOW = datetime(2026, 10, 3, tzinfo=UTC)
OLD = NOW - timedelta(hours=3)


def _rows(posted: datetime, values: list[float], source: str = "live") -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "interval_start": H + timedelta(hours=i),
                "interval_minutes": 60,
                "posted_at": posted,
                "ingested_at": posted,
                "source": source,
                "schema_version": 1,
                "series": "temperature_2m:Coast",
                "value": v,
            }
            for i, v in enumerate(values)
        ],
        schema=FORECAST_SCHEMA,
    )


def _write(lake: Lake, key: str, table: pa.Table, written: datetime = OLD) -> None:
    lake.write_table(key, table)
    ts = written.timestamp()
    os.utime(Path(lake.root) / key, (ts, ts))


def _files(lake: Lake) -> list[str]:
    return [k.rsplit("/", 1)[1] for k in lake.list_keys(f"curated/{PRODUCT}/")]


@pytest.fixture
def three_postings(lake: Lake) -> list[datetime]:
    posts = [H - timedelta(hours=6), H - timedelta(hours=3)]
    _write(lake, curated_key(PRODUCT, DAY, posts[0]), _rows(posts[0], [1.0, 2.0]))
    _write(lake, curated_key(PRODUCT, DAY, posts[1]), _rows(posts[1], [1.5]))
    backfilled = _rows(H - timedelta(days=2), [0.5], "previous_runs")
    _write(lake, previous_runs_key(PRODUCT, DAY), backfilled)
    return posts


def test_merges_every_file_kind_without_changing_answers(
    settings: Settings, lake: Lake, three_postings: list[datetime]
) -> None:
    from ingest.catalog import publish_catalog  # noqa: PLC0415

    publish_catalog(settings, lake, NOW)
    as_ofs = [H - timedelta(days=3), H - timedelta(days=1), H - timedelta(hours=4), NOW]

    def answers() -> list[Any]:
        with WeatherReader(settings.lake.root) as r:
            return [
                r.snapshot(PRODUCT, H, H + timedelta(hours=3), as_of=a).to_pylist() for a in as_ofs
            ]

    before = answers()
    s = compact_product(settings.product(PRODUCT), lake, now=NOW)
    assert (s.partitions_merged, s.files_in, s.rows) == (1, 3, 4)
    assert _files(lake) == [merged_key(PRODUCT, DAY, NOW).rsplit("/", 1)[1]]
    assert answers() == before


def test_young_files_and_single_files_are_left_alone(settings: Settings, lake: Lake) -> None:
    _write(lake, curated_key(PRODUCT, DAY, H), _rows(H, [1.0]), written=NOW)
    _write(lake, curated_key(PRODUCT, DAY, OLD), _rows(OLD, [2.0]))
    assert compact_product(settings.product(PRODUCT), lake, now=NOW).partitions_merged == 0


def test_a_rerun_backfill_after_compaction_is_folded_back_in(
    settings: Settings, lake: Lake, three_postings: list[datetime]
) -> None:
    compact_product(settings.product(PRODUCT), lake, now=NOW)
    # the same window backfilled again: identical rows, already in the merged file
    backfilled = _rows(H - timedelta(days=2), [0.5], "previous_runs")
    _write(lake, previous_runs_key(PRODUCT, DAY), backfilled)
    later = NOW + timedelta(hours=2)
    os.utime(Path(lake.root) / merged_key(PRODUCT, DAY, NOW), (OLD.timestamp(), OLD.timestamp()))
    s = compact_product(settings.product(PRODUCT), lake, now=later)
    assert s.leftovers_removed == 1 and s.rows == 4


def test_stops_between_partitions_and_the_handler_keeps_a_margin(
    settings: Settings, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    for day in (DAY, DAY + timedelta(days=1)):
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        for p in (start - timedelta(hours=5), start - timedelta(hours=4)):
            _write(lake, curated_key(PRODUCT, day, p), _rows(p, [1.0]))
    checks = iter([False, True])
    s = compact_product(settings.product(PRODUCT), lake, now=NOW, stop=lambda: next(checks))
    assert (s.partitions_merged, s.stopped) == (1, True)
    assert len(compact(settings, lake, now=NOW, stop=lambda: True)) == 1

    class Ctx:
        def get_remaining_time_in_millis(self) -> int:
            return 500_000

    # The handler runs on the real clock: age the remaining partition's files to the real past.
    past = (datetime.now(UTC) - timedelta(hours=3)).timestamp()
    for key in lake.list_keys(f"curated/{PRODUCT}/"):
        os.utime(Path(lake.root) / key, (past, past))
    monkeypatch.setattr(handler, "load_settings", lambda: settings)
    out = handler.compact({}, Ctx())
    assert out["products"][0]["partitions_merged"] == 1 and not out["products"][0]["stopped"]


def test_verify_a_lake(settings: Settings, lake: Lake, three_postings: list[datetime]) -> None:
    from ingest.catalog import publish_catalog  # noqa: PLC0415
    from scripts.verify_lake import verify  # noqa: PLC0415

    publish_catalog(settings, lake, NOW)
    assert verify(settings.lake.root, None) == []
    bad = _rows(H, [1.0]).set_column(
        3, "ingested_at", pa.array([H - timedelta(hours=1)], pa.timestamp("us", tz="UTC"))
    )
    _write(lake, curated_key(PRODUCT, DAY, H), bad)
    late = verify(settings.lake.root, None)
    assert any("posted after they were ingested" in p for p in late)
