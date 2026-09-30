"""Lambda entry points. The image runs ``ingest.handler.ingest`` hourly."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ingest.cli import configure_logging, run_products
from ingest.config import load_settings
from ingest.metrics import publish_age

log = logging.getLogger(__name__)


def ingest(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """Poll every product (or ``event["product"]``) and publish the freshness metric."""
    import boto3  # noqa: PLC0415  (only the deployed path needs the AWS SDK)

    configure_logging(str(event.get("log_level", "INFO")))
    settings = load_settings()
    summaries = run_products(settings, str(event.get("product", "all")), offline=False)
    now = datetime.now(UTC)
    ages = [a for s in summaries if (a := s.age_minutes(now)) is not None]
    if ages:
        publish_age(boto3.client("cloudwatch"), max(ages))
    return {"polls": [s.as_dict() for s in summaries]}
