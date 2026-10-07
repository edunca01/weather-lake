from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ingest.config import Settings
from ingest.lake import Lake
from ingest.run import poll
from weather_lake.contract import manifest_key, raw_key

from .conftest import PRODUCT

T0 = datetime(2026, 9, 30, 20, 25, tzinfo=UTC)


def _fetch(body: list[dict[str, Any]]) -> Any:
    data = json.dumps(body).encode()
    return lambda: data


def test_first_poll_is_a_posting_with_raw_first(
    settings: Settings, lake: Lake, sample: list[dict[str, Any]]
) -> None:
    s = poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    assert s.new_posting and s.posted_at == T0 and s.rows == 432
    assert json.loads(gzip.decompress(lake.read_bytes(raw_key(PRODUCT, T0)))) == sample
    part = lake.list_keys(f"curated/{PRODUCT}/")
    assert len(part) == len(s.partitions) == 1
    assert lake.read_table(part[0]).num_rows == 432
    m = lake.read_json(manifest_key(PRODUCT))
    assert m["last_posted_at"] == m["last_checked_at"] == T0.isoformat()


def test_unchanged_content_is_not_a_new_posting(
    settings: Settings, lake: Lake, sample: list[dict[str, Any]]
) -> None:
    poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    t1 = T0 + timedelta(hours=1)
    s = poll(settings, PRODUCT, lake, _fetch(sample), now=t1)
    assert not s.new_posting and s.posted_at == T0
    assert s.age_minutes(t1) == 60
    assert len(lake.list_keys(f"curated/{PRODUCT}/")) == 1
    assert lake.exists(raw_key(PRODUCT, t1))  # every response is kept
    m = lake.read_json(manifest_key(PRODUCT))
    assert (m["last_posted_at"], m["last_checked_at"]) == (T0.isoformat(), t1.isoformat())


def test_changed_content_is_a_new_posting(
    settings: Settings, lake: Lake, sample: list[dict[str, Any]]
) -> None:
    poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    sample[0]["hourly"]["temperature_2m"][2] += 1.0
    t1 = T0 + timedelta(hours=1)
    s = poll(settings, PRODUCT, lake, _fetch(sample), now=t1)
    assert s.new_posting and s.posted_at == t1
    assert len(lake.list_keys(f"curated/{PRODUCT}/")) == 2


def test_rerunning_a_poll_overwrites_the_same_keys(
    settings: Settings, lake: Lake, sample: list[dict[str, Any]]
) -> None:
    poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    lake.delete(lake.list_keys(f"curated/{PRODUCT}/")[0])
    lake.write_json(manifest_key(PRODUCT), {})  # as if the first run died after raw
    poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    assert len(lake.list_keys(f"curated/{PRODUCT}/")) == 1
    assert len(lake.list_keys(f"raw/{PRODUCT}/")) == 1


def test_a_failing_fetch_writes_nothing(settings: Settings, lake: Lake) -> None:
    def boom() -> bytes:
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="down"):
        poll(settings, PRODUCT, lake, boom, now=T0)
    assert lake.list_keys("") == []


def test_lake_refuses_to_delete_outside_curated(lake: Lake) -> None:
    lake.write_bytes("raw/x/y", b"1")
    with pytest.raises(PermissionError):
        lake.delete("raw/x/y")


def test_the_poll_round_trips_through_the_reader(
    settings: Settings, lake: Lake, sample: list[dict[str, Any]]
) -> None:
    from ingest.catalog import publish_catalog  # noqa: PLC0415
    from weather_lake import WeatherReader  # noqa: PLC0415

    assert publish_catalog(settings, lake, T0)
    assert not publish_catalog(settings, lake, T0 + timedelta(hours=1))  # unchanged
    poll(settings, PRODUCT, lake, _fetch(sample), now=T0)
    first = datetime.fromtimestamp(sample[0]["hourly"]["time"][0], UTC)
    with WeatherReader(settings.lake.root) as r:
        got = r.snapshot(PRODUCT, first, first + timedelta(hours=6), as_of=T0)
        assert r.products() == [PRODUCT]
    assert got.num_rows == 432


def test_read_json_retries_a_torn_read(lake: Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    lake.write_json("manifests/p/latest.json", {"a": 1})
    real = lake.read_bytes
    torn = iter([b'{"a": \x9d', None])

    def flaky(key: str) -> bytes:
        bad = next(torn)
        return bad if bad is not None else real(key)

    monkeypatch.setattr(lake, "read_bytes", flaky)
    assert lake.read_json("manifests/p/latest.json") == {"a": 1}
