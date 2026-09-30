"""Fetch one live response per product and keep its first hours as the committed sample.

    uv run python -m scripts.fetch_sample [--hours 6]

The sample is Open-Meteo data (CC BY 4.0); samples/README.md carries the attribution.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from ingest.cli import SAMPLES
from ingest.config import load_settings
from ingest.openmeteo import OpenMeteoClient


def trim(entries: list[dict[str, Any]], hours: int) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        hourly = {k: v[:hours] for k, v in e["hourly"].items()}
        out.append({**{k: v for k, v in e.items() if k != "generationtime_ms"}, "hourly": hourly})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    args = ap.parse_args()
    settings = load_settings()
    points = [p for _, p in settings.points()]
    SAMPLES.mkdir(parents=True, exist_ok=True)
    with OpenMeteoClient(settings.openmeteo) as client:
        for key, product in settings.products.items():
            entries = json.loads(client.forecast(product, points))
            path = SAMPLES / f"{key}.json"
            path.write_text(json.dumps(trim(entries, args.hours), indent=1) + "\n")
            print(f"{path}: {len(entries)} points, {args.hours} hours")


if __name__ == "__main__":
    main()
