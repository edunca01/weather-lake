# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Versioning: SemVer on the lake contract
(`weather-lake-vX.Y.Z`, docs/CONTRACT.md §1). Curated-schema changes always go under **Schema**.

## [Unreleased]

## [1.0.0] - 2026-10-13

The first public release: the lake contract 1.0.0 (`docs/CONTRACT.md`) and the `weather-lake`
read library, tagged `weather-lake-v1.0.0`.

### Schema
- One curated table, `forecast`, schema version 1: hourly Open-Meteo `gfs_seamless` forecasts
  of nine variables, aggregated to ERCOT's eight weather zones, as `<variable>:<Zone>` series.
- Every row carries `interval_start`, `posted_at` and `ingested_at`. `posted_at` is the fetch
  time for live polls and `valid − N days + 1 h` for Previous Runs vintages (ADR 0005). A
  business key appears at most once per posting, so the point-in-time read is deterministic.
- `manifests/<product>/latest.json`, `manifests/<product>/previous_runs.json` and
  `manifests/_catalog.json`, which lists units, zones and the points behind each zone.
- SSM parameters under `/weather-lake/` for consumers in the same account.

### Added
- `weather-lake`: `WeatherReader` (`snapshot` and `postings`, `as_of` required, `*` series
  wildcards, pyarrow results, local or S3 through DuckDB), the contract module and the catalog
  model.
- Hourly live polling of every zone point in one request, raw responses kept gzipped, and
  curated written only when the forecast changed.
- Backfill from Open-Meteo's Previous Runs API (lead days 1–7) through the same writer.
- Compaction, `make verify`, one freshness alarm, Terraform modules with a mocked-provider
  test suite, and CI.

### Notes
- Pre-release contract versions 0.1.x had the same shape. A 1.0.0 reader refuses a lake still
  publishing a 0.x catalog; the catalog is republished at 1.0.0 by the first poll after the
  pipeline is upgraded.
