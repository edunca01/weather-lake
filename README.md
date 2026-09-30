# weather-lake

A point-in-time lake of weather **forecasts** for the ERCOT region, kept by the time each
forecast was known, and aggregated to ERCOT's eight weather zones.

> **Status: early development.** Live collection runs; the reader library, the backfill of
> past forecast runs and compaction follow.

## Why point-in-time weather

A model that predicts tomorrow's load or wind output from weather must be trained on the
forecasts that existed when each prediction would have been made, not on the weather that
actually happened, and not on a forecast issued an hour before the fact. Weather APIs usually
serve the latest forecast. This lake polls one every hour and keeps every version it sees,
so a reader can ask **what the forecast said at any past moment**:

```
posted_at <= as_of, then the latest posting per (interval_start, series)
```

It is the same contract as the sibling
[ercot-pit-lake](https://github.com/edunca01/ercot-pit-lake) (see its
[contract](https://github.com/edunca01/ercot-pit-lake/blob/main/docs/CONTRACT.md) and
[ADR 0009](https://github.com/edunca01/ercot-pit-lake/blob/main/docs/adr/0009-a-family-of-point-in-time-lakes.md)),
and uses the same zone names as its load series, so the two join on
(`interval_start`, zone) with no mapping.

## What is collected

- **Source:** [Open-Meteo](https://open-meteo.com/) forecast API, model `gfs_seamless`
  (HRRR blended with GFS), hourly, 8 days ahead. A fixed model, so vintages stay comparable.
- **Variables:** temperature, relative humidity, dew point, apparent temperature, wind at 10 m
  and 100 m, shortwave radiation, cloud cover, precipitation (`config.yaml` lists units).
- **Zones:** `Coast`, `East`, `FarWest`, `North`, `NorthCentral`, `SouthCentral`, `Southern`,
  `West`, each the equal-weight mean of two or three representative cities.
- **Postings:** a poll whose forecast equals the previous one is not a new posting: nothing new
  was known. Every response is still kept, gzipped, in `raw/`.

Curated rows: `interval_start`, `interval_minutes`, `posted_at`, `ingested_at`, `source`,
`schema_version`, `series` (`<variable>:<Zone>`, e.g. `temperature_2m:NorthCentral`), `value`.

## Try it offline

```
make setup
make ingest OFFLINE=1     # the committed sample -> ./data (raw, curated Parquet, manifest)
make check                # lint, mypy strict, tests; no network, no credentials
```

## Deploy

`infra/` holds the Terraform modules and an example root: a private bucket, the poller Lambda
on an hourly schedule, one freshness alarm, a consumer read policy and SSM parameters under
`/weather-lake/`. This repository deploys nothing itself.

## Contributions

This is a portfolio project and does not take pull requests. You are welcome to fork it.
Report security issues privately: [SECURITY.md](SECURITY.md).

## License and attribution

MIT for the code ([LICENSE](LICENSE)). Weather data by [Open-Meteo.com](https://open-meteo.com/),
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); Open-Meteo's free API
is for non-commercial use. The sample in `samples/` is Open-Meteo data under the same licence.
