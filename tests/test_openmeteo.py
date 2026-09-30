from __future__ import annotations

from typing import Any

import httpx
import pytest

from ingest.config import Settings
from ingest.openmeteo import OpenMeteoClient, RetriesExhaustedError, forecast_params

from .conftest import PRODUCT


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    out: list[float] = []
    monkeypatch.setattr("ingest.openmeteo.time.sleep", out.append)
    return out


def _client(settings: Settings, handler: Any, **cfg: Any) -> OpenMeteoClient:
    c = settings.openmeteo.model_copy(update=cfg)
    return OpenMeteoClient(c, transport=httpx.MockTransport(handler))


def test_one_request_for_every_point(settings: Settings, sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []

    def api(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=b"[]")

    points = [p for _, p in settings.points()]
    with _client(settings, api) as c:
        assert c.forecast(settings.product(PRODUCT), points) == b"[]"
    q = seen[0].url.params
    assert len(q["latitude"].split(",")) == len(points) == 22
    assert q["models"] == "gfs_seamless" and q["timeformat"] == "unixtime"
    assert q["wind_speed_unit"] == "ms" and q["timezone"] == "GMT"
    assert q["hourly"].split(",") == list(settings.product(PRODUCT).variables)
    assert sleeps == []


def test_retries_then_succeeds(settings: Settings, sleeps: list[float]) -> None:
    replies = iter([httpx.Response(503), httpx.Response(200, content=b"ok")])
    with _client(settings, lambda _: next(replies)) as c:
        assert c.forecast(settings.product(PRODUCT), []) == b"ok"
    assert sleeps == [1.0]


def test_gives_up_after_max_retries(settings: Settings, sleeps: list[float]) -> None:
    def api(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with (
        _client(settings, api, max_retries=2) as c,
        pytest.raises(RetriesExhaustedError, match="after 3 attempts"),
    ):
        c.forecast(settings.product(PRODUCT), [])
    assert sleeps == [1.0, 2.0]


def test_stops_at_the_time_budget(
    settings: Settings, sleeps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = {"t": 0.0}
    monkeypatch.setattr("ingest.openmeteo.time.monotonic", lambda: now["t"])

    def api(req: httpx.Request) -> httpx.Response:
        now["t"] += 100.0
        return httpx.Response(429)

    with (
        _client(settings, api, max_retries=5, request_budget_s=120.0) as c,
        pytest.raises(RetriesExhaustedError, match=r"after 2 attempts .*out of time"),
    ):
        c.forecast(settings.product(PRODUCT), [])


def test_a_client_error_is_not_retried(settings: Settings, sleeps: list[float]) -> None:
    with (
        _client(settings, lambda _: httpx.Response(400)) as c,
        pytest.raises(httpx.HTTPStatusError),
    ):
        c.forecast(settings.product(PRODUCT), [])
    assert sleeps == []


def test_params_format(settings: Settings) -> None:
    p = forecast_params(settings.product(PRODUCT), [settings.points()[0][1]])
    assert p["latitude"] == "29.7604" and p["forecast_days"] == 8
