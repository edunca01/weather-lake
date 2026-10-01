"""Lambda entry points. The image runs ``ingest.handler.ingest`` hourly."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ingest import compact as _compact
from ingest.cli import configure_logging, run_products
from ingest.config import aws_region, load_settings
from ingest.lake import Lake
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


# A partition merge takes seconds: stop starting new ones with this much time left, rather than
# be killed mid-merge by the Lambda timeout. The next hourly run continues.
_COMPACT_MARGIN_MS = 90_000


def compact(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """Merge old small curated files, every product (hourly schedule)."""
    configure_logging(str(event.get("log_level", "INFO")))
    settings = load_settings()
    remaining = getattr(context, "get_remaining_time_in_millis", None)

    def stop() -> bool:
        return remaining is not None and remaining() < _COMPACT_MARGIN_MS

    lake = Lake(settings.lake, region=aws_region())
    summaries = _compact.compact(settings, lake, stop=stop)
    return {"products": [s.as_dict() for s in summaries]}
