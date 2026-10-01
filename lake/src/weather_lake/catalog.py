"""``manifests/_catalog.json``: what a lake holds (products, units, zones and their points), so
consumers need no copy of the pipeline's configuration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from weather_lake.contract import BUSINESS_KEY, CONTRACT_VERSION, SUPPORTED_SCHEMA_VERSIONS
from weather_lake.errors import (
    IncompatibleContractError,
    UnknownProductError,
    UnsupportedSchemaVersionError,
)


class CatalogPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    lat: float
    lon: float


class CatalogProduct(BaseModel):
    # Unknown fields are ignored: the pipeline may add fields in a minor release.
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    source: str
    model: str
    interval_minutes: int
    schema_version: int
    variables: dict[str, str]  # variable -> unit
    zones: dict[str, list[CatalogPoint]]
    live: bool  # False: no longer collected; its data stays readable

    def series(self) -> list[str]:
        return [f"{v}:{z}" for v in self.variables for z in self.zones]


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    contract_version: str
    generated_at: datetime
    business_key: tuple[str, ...] = BUSINESS_KEY
    products: dict[str, CatalogProduct]

    @classmethod
    def parse(cls, text: str | bytes) -> Catalog:
        catalog = cls.model_validate_json(text)
        catalog.check_compatible()
        return catalog

    def check_compatible(self) -> None:
        """Releases within one compatibility line only add. Before 1.0 a minor release may
        change shape, so 0.x lines are major.minor."""
        if _line(self.contract_version) != _line(CONTRACT_VERSION):
            msg = (
                f"lake is contract {self.contract_version}, this weather-lake reads "
                f"{'.'.join(map(str, _line(CONTRACT_VERSION)))}.x"
            )
            raise IncompatibleContractError(msg)

    def product(self, key: str) -> CatalogProduct:
        try:
            p = self.products[key]
        except KeyError:
            known = ", ".join(sorted(self.products)) or "none"
            msg = f"{key!r} is not in this lake (products: {known})"
            raise UnknownProductError(msg) from None
        if p.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            msg = f"{key} is written at schema_version {p.schema_version}; upgrade weather-lake"
            raise UnsupportedSchemaVersionError(msg)
        return p

    def to_json(self) -> str:
        return self.model_dump_json(indent=2) + "\n"


def _line(version: str) -> tuple[int, ...]:
    major, minor, *_ = (int(x) for x in version.split("."))
    return (major,) if major else (major, minor)
