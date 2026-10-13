# 0003. Open-Meteo, one fixed model per product

Date: 2026-09-30
Status: accepted

## Context

The lake needs hourly weather forecasts for Texas, several days ahead, at no cost, with a way
to recover past forecast runs. Open-Meteo offers this without an API key (free for
non-commercial use, data under CC BY 4.0) through three APIs that differ in what they can
honestly provide:

- the **forecast** API returns the latest forecast; polled on a schedule, it builds true
  vintages from the day polling starts;
- the **Previous Runs** API returns, per valid time, what was forecast one, two, … days
  earlier: vintages by lead day, usable for backfill;
- the **Historical Forecast** API stitches the first hours of successive runs into one
  series: a very-short-lead forecast everywhere, which leaks the future into any feature
  meant for a longer lead.

Open-Meteo's default `best_match` picks a model per location and can change it over time, so
two vintages of `best_match` may come from different models.

## Decision

- Collect from **Open-Meteo**: the forecast API live, the Previous Runs API for backfill.
  The Historical Forecast API is never a source of forecast features.
- **One product per model**, named `<source>-<model>`. The first is
  `openmeteo-gfs-seamless`: NOAA's HRRR (hourly runs, about 3 km) blended into GFS, the
  longest Previous Runs history for the US and a forecast that changes about hourly.
  `best_match` is never used.
- Poll **hourly at :25**, 8 days ahead: each HRRR run is caught, Open-Meteo asks clients to
  avoid the top of the hour, and 8 days in UTC covers ERCOT's seven-day load forecast in
  Central time. All points go in one request, which keeps the poll well inside the free tier.
- Declared variables and units are exhaustive. A response that lacks one or changes a unit
  fails (`SchemaDriftError`); nothing is coerced.

## Consequences

- A second model (for example ECMWF IFS) is a second product, not a change to this one.
- Weather history for honest training is what Previous Runs covers (most variables from
  January 2024) plus live polling. Deeper history would need another source or leaky
  features: a new ADR, never a quiet change.
- Open-Meteo is credited wherever its data or samples appear.
