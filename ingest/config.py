"""Settings from ``config.yaml`` and the environment. The only module that reads either."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenMeteoConfig(_Strict):
    forecast_url: str
    previous_runs_url: str
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    request_budget_s: float = Field(gt=0)


class LakeConfig(_Strict):
    root: str

    @property
    def is_s3(self) -> bool:
        return self.root.startswith("s3://")


class Point(_Strict):
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Backfill(_Strict):
    """Previous Runs: ``<variable>_previous_dayN`` is the value predicted N x 24 h before the
    valid time, so it was known at ``valid time - N days``; ``publication_lag_min`` is added
    so a backfilled row is never earlier than a live poll could have seen it."""

    lead_days: list[int] = Field(min_length=1)
    publication_lag_min: int = Field(ge=0)
    window_days: int = Field(ge=1, le=31)
    earliest: date


class Product(_Strict):
    key: str
    name: str
    model: str
    forecast_days: int = Field(ge=1, le=16)
    schedule: str
    stale_after_min: int = Field(gt=0)
    variables: dict[str, str] = Field(min_length=1)  # variable -> expected unit
    backfill: Backfill | None = None


class Settings(_Strict):
    openmeteo: OpenMeteoConfig
    lake: LakeConfig
    products: dict[str, Product]
    zones: dict[str, list[Point]]

    @model_validator(mode="before")
    @classmethod
    def _keys_into_products(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("products"), dict):
            data = {**data, "products": {k: {"key": k, **v} for k, v in data["products"].items()}}
        return data

    @model_validator(mode="after")
    def _zones_have_points(self) -> Settings:
        empty = [z for z, pts in self.zones.items() if not pts]
        if empty or not self.zones:
            msg = f"every zone needs at least one point: {empty or 'no zones'}"
            raise ValueError(msg)
        return self

    def product(self, key: str) -> Product:
        if key not in self.products:
            msg = f"unknown product {key!r}; configured: {sorted(self.products)}"
            raise KeyError(msg)
        return self.products[key]

    def points(self) -> list[tuple[str, Point]]:
        """(zone, point) in a fixed order: the order of the request and of the response."""
        return [(zone, p) for zone, pts in self.zones.items() for p in pts]


def load_settings(path: Path | None = None) -> Settings:
    raw = yaml.safe_load((path or CONFIG_PATH).read_text())
    root = os.environ.get("LAKE_ROOT")
    if root:
        raw["lake"] = {**raw.get("lake", {}), "root": root}
    return Settings.model_validate(raw)


def aws_region() -> str | None:
    return os.environ.get("AWS_REGION")
