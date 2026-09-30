"""Open-Meteo forecast client: one request for every point of every zone.

Retries are bounded by a time budget as well as a count: a scheduled poll must finish before
the next one starts, or slow responses pile runs up until the account's Lambda concurrency is
exhausted. The next poll is the retry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx

from ingest.config import OpenMeteoConfig, Point, Product

log = logging.getLogger(__name__)

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class RetriesExhaustedError(RuntimeError):
    """Every attempt failed or the time budget ran out."""


def forecast_params(product: Product, points: Sequence[Point]) -> dict[str, Any]:
    return {
        "latitude": ",".join(f"{p.lat:.4f}" for p in points),
        "longitude": ",".join(f"{p.lon:.4f}" for p in points),
        "hourly": ",".join(product.variables),
        "models": product.model,
        "forecast_days": product.forecast_days,
        "timezone": "GMT",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }


class OpenMeteoClient:
    def __init__(self, cfg: OpenMeteoConfig, *, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._http = httpx.Client(timeout=cfg.timeout_s, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OpenMeteoClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def forecast(self, product: Product, points: Sequence[Point]) -> bytes:
        """The raw response body, exactly as received."""
        params = forecast_params(product, points)
        deadline = time.monotonic() + self.cfg.request_budget_s
        problem, made = "no attempt", 0
        for attempt in range(self.cfg.max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                problem = f"{problem}, then out of time"
                break
            made += 1
            try:
                resp = self._http.get(
                    self.cfg.forecast_url, params=params, timeout=min(self.cfg.timeout_s, remaining)
                )
            except httpx.TransportError as exc:
                problem = type(exc).__name__
            else:
                if resp.status_code not in _RETRY_STATUS:
                    resp.raise_for_status()
                    return resp.content
                problem = str(resp.status_code)
            if attempt < self.cfg.max_retries:
                wait = min(2.0**attempt, max(deadline - time.monotonic(), 0.0))
                log.warning("%s from Open-Meteo; retrying in %.1fs", problem, wait)
                time.sleep(wait)
        msg = f"gave up on Open-Meteo after {made} attempts (last: {problem})"
        raise RetriesExhaustedError(msg)
