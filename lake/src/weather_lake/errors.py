"""Errors the reader raises. All derive from ``LakeError``."""

from __future__ import annotations


class LakeError(Exception):
    """Base class for everything this library raises about a lake's contents."""


class CatalogNotFoundError(LakeError):
    """The root has no ``manifests/_catalog.json``: not a weather lake, or never polled."""


class IncompatibleContractError(LakeError):
    """The lake is written under a contract this library version cannot read."""


class UnknownProductError(LakeError):
    """The product is not in the lake's catalog."""


class UnsupportedSchemaVersionError(LakeError):
    """Rows are at a schema version this library does not know; upgrade weather-lake."""
