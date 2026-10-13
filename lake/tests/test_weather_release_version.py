"""The released package names the contract version it implements: a `weather-lake-vX.Y.Z` tag,
the package version and ``CONTRACT_VERSION`` are one number."""

from __future__ import annotations

import importlib.metadata

import weather_lake


def test_package_version_is_the_contract_version() -> None:
    assert importlib.metadata.version("weather-lake") == weather_lake.CONTRACT_VERSION
