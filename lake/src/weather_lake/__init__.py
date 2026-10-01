"""Read the weather-lake point-in-time: the contract, the catalog and a DuckDB reader."""

from weather_lake.catalog import Catalog, CatalogProduct
from weather_lake.contract import BUSINESS_KEY, CONTRACT_VERSION, FORECAST_SCHEMA, SCHEMA_VERSION
from weather_lake.errors import (
    CatalogNotFoundError,
    IncompatibleContractError,
    LakeError,
    UnknownProductError,
    UnsupportedSchemaVersionError,
)
from weather_lake.reader import WeatherReader

__all__ = [
    "BUSINESS_KEY",
    "CONTRACT_VERSION",
    "FORECAST_SCHEMA",
    "SCHEMA_VERSION",
    "Catalog",
    "CatalogNotFoundError",
    "CatalogProduct",
    "IncompatibleContractError",
    "LakeError",
    "UnknownProductError",
    "UnsupportedSchemaVersionError",
    "WeatherReader",
]
