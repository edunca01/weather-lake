"""The one freshness metric, published by every poll.

``PostingAgeMinutes`` is the minutes since the newest posting, the maximum over the products
polled. One metric and one alarm however many products: a stopped poller publishes nothing,
and the alarm treats missing data as breaching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch import CloudWatchClient

NAMESPACE = "WeatherLake"
METRIC = "PostingAgeMinutes"


def publish_age(cloudwatch: CloudWatchClient, age_minutes: float) -> None:
    cloudwatch.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{"MetricName": METRIC, "Value": age_minutes, "Unit": "None"}],
    )
