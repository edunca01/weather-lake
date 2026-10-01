"""``ingest``: poll every product (or one) into $LAKE_ROOT; ``--offline`` uses the samples."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ingest.backfill import backfill
from ingest.catalog import publish_catalog
from ingest.compact import compact
from ingest.config import Settings, aws_region, load_settings
from ingest.lake import Lake
from ingest.openmeteo import OpenMeteoClient
from ingest.run import PollSummary, poll
from weather_lake.contract import CONTRACT_VERSION

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "openmeteo"

log = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )
    for noisy in ("httpx", "httpcore", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def sample_body(product: str) -> bytes:
    path = SAMPLES / f"{product}.json"
    if not path.exists():
        msg = f"no sample for {product}: {path}"
        raise FileNotFoundError(msg)
    return path.read_bytes()


def run_products(settings: Settings, product: str, *, offline: bool) -> list[PollSummary]:
    """Poll each requested product; a failure in one does not stop the others, and is raised
    at the end so the invocation still fails."""
    keys = list(settings.products) if product == "all" else [settings.product(product).key]
    lake = Lake(settings.lake, region=aws_region())
    publish_catalog(settings, lake, datetime.now(UTC).replace(microsecond=0))
    summaries, failures = [], []
    with OpenMeteoClient(settings.openmeteo) as client:
        for key in keys:
            now = datetime.now(UTC).replace(microsecond=0)

            def fetch(key: str = key) -> bytes:
                if offline:
                    return sample_body(key)
                points = [pt for _, pt in settings.points()]
                return client.forecast(settings.product(key), points)

            try:
                summaries.append(poll(settings, key, lake, fetch, now=now))
            except Exception as exc:
                log.exception("%s: poll failed", key)
                failures.append(f"{key}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return summaries


def main_ingest(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ingest", description="Poll Open-Meteo into the lake.")
    ap.add_argument("--product", default="all", help="product key from config.yaml, or 'all'")
    ap.add_argument("--offline", action="store_true", help="use samples/ instead of the API")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    configure_logging(args.log_level)
    settings = load_settings()
    log.info("contract %s, lake %s", CONTRACT_VERSION, settings.lake.root)
    for s in run_products(settings, args.product, offline=args.offline):
        print(json.dumps(s.as_dict()))
    return 0


def main_backfill(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="backfill", description="Backfill past vintages from Open-Meteo's Previous Runs API."
    )
    ap.add_argument("--product", required=True)
    ap.add_argument("--from", dest="first", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="last", required=True, type=date.fromisoformat)
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between windows")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    configure_logging(args.log_level)
    settings = load_settings()
    product = settings.product(args.product)
    lake = Lake(settings.lake, region=aws_region())
    publish_catalog(settings, lake, datetime.now(UTC).replace(microsecond=0))
    points = [pt for _, pt in settings.points()]
    lead_days = product.backfill.lead_days if product.backfill else []
    with OpenMeteoClient(settings.openmeteo) as client:
        summary = backfill(
            settings,
            product.key,
            lake,
            lambda f, t: client.previous_runs(product, points, lead_days, f, t),
            args.first,
            args.last,
            now=lambda: datetime.now(UTC).replace(microsecond=0),
            pause_s=args.pause,
        )
    print(json.dumps(summary.as_dict()))
    return 0


def main_compact(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compact", description="Merge old small curated files.")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    configure_logging(args.log_level)
    settings = load_settings()
    for s in compact(settings, Lake(settings.lake, region=aws_region())):
        print(json.dumps(s.as_dict()))
    return 0


if __name__ == "__main__":
    sys.exit(main_ingest())
