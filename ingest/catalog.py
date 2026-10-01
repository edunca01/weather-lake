"""Publish ``manifests/_catalog.json`` from the configuration: products, units, zones and the
points behind each zone. Rewritten only when something other than its timestamp changed."""

from __future__ import annotations

import logging
from datetime import datetime

from ingest.config import Settings
from ingest.lake import Lake
from weather_lake.catalog import Catalog, CatalogPoint, CatalogProduct
from weather_lake.contract import CATALOG_KEY, CONTRACT_VERSION, SCHEMA_VERSION

log = logging.getLogger(__name__)


def build_catalog(settings: Settings, now: datetime) -> Catalog:
    zones = {
        zone: [CatalogPoint(name=p.name, lat=p.lat, lon=p.lon) for p in points]
        for zone, points in settings.zones.items()
    }
    return Catalog(
        contract_version=CONTRACT_VERSION,
        generated_at=now,
        products={
            key: CatalogProduct(
                name=p.name,
                source="open-meteo",
                model=p.model,
                interval_minutes=60,
                schema_version=SCHEMA_VERSION,
                variables=dict(p.variables),
                zones=zones,
                live=True,
            )
            for key, p in settings.products.items()
        },
    )


def publish_catalog(settings: Settings, lake: Lake, now: datetime) -> bool:
    """Write the catalog if it changed; True when written."""
    new = build_catalog(settings, now)
    if lake.exists(CATALOG_KEY):
        old = Catalog.model_validate_json(lake.read_bytes(CATALOG_KEY))
        if old.model_copy(update={"generated_at": now}) == new:
            return False
    lake.write_bytes(CATALOG_KEY, new.to_json().encode())
    log.info("catalog published: %s", sorted(new.products))
    return True
