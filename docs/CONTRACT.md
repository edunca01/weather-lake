# Lake contract

Contract version: **1.0.0** (`weather_lake.contract.CONTRACT_VERSION`). Curated schema version:
**1** (`SCHEMA_VERSION`, stored on every row).

This is the only interface between this repository and its consumers. Anything not written
here (module names, raw response internals, log formats) is private and may change without
notice. The shape is shared with the sibling
[ercot-pit-lake](https://github.com/edunca01/ercot-pit-lake/blob/main/docs/CONTRACT.md)
([its ADR 0009](https://github.com/edunca01/ercot-pit-lake/blob/main/docs/adr/0009-a-family-of-point-in-time-lakes.md)).

`tests/test_contract_doc.py` parses the tables in §3–§4 and compares them to the code.
Keep their format: one row per column, backticked names.

## 1. Versioning

- **Contract version** (SemVer, released as `weather-lake-vX.Y.Z`):
  - **major**: a column removed, renamed or retyped; a key format changed; the business key
    changed; a variable's unit changed.
  - **minor**: a product, a variable, a zone or a nullable column added; a zone's points
    changed (it changes what the zone value means, so CHANGELOG says so).
  - **patch**: documentation only.
- **`schema_version`** (integer, per row) goes up whenever the table's columns change. The
  reader library reads every version it knows and refuses unknown ones.
- The reader accepts a lake whose contract shares its major version (§6).
- A major bump is announced in CHANGELOG under **Schema**, with a migration note.

## 2. Layout

```
<root>/
  raw/<product>/date=<fetch date, UTC>/fetched=<stamp>.json.gz
  raw/<product>/date=<fetch date, UTC>/previous-runs-<first>_<last>-<stamp>.json.gz
  curated/<product>/date=<valid date, UTC>/part-<stamp>.parquet
  curated/<product>/date=<valid date, UTC>/previous-runs.parquet
  curated/<product>/date=<valid date, UTC>/merged-<stamp>.parquet
  manifests/<product>/latest.json
  manifests/<product>/previous_runs.json
  manifests/_catalog.json
```

- `<root>` is `s3://<bucket>` deployed, or any local directory.
- `<product>` is `<source>-<model>`, lower-case and hyphenated, e.g. `openmeteo-gfs-seamless`.
  One product per weather model: vintages are only comparable within a fixed model.
- `<stamp>` is a UTC basic ISO 8601 time, `YYYYMMDDTHHMMSSZ` (e.g. `20260930T202500Z`).
  - On `fetched=` and `part-` files it is the fetch time, which is the posting time (§5).
  - On `merged-` files it is the compaction time.
- A `date=` value is `YYYY-MM-DD` in **UTC**. Weather has no settlement day, and UTC has no
  daylight-saving transitions.
  - Raw is partitioned by fetch date, because raw lands before parsing.
  - Curated is partitioned by **valid** date. A posting covers eight valid days and writes
    one `part-` file into each.
  - `previous-runs.parquet` holds a valid day's backfilled vintages (§5). Re-running a
    backfill overwrites it.
- Consumers must treat the set of files in a curated partition as unordered and changing:
  compaction replaces `part-` and `previous-runs` files with a `merged-` file. Rows are never
  changed or dropped, so a point-in-time read (§7) gives the same answer before and after.
- `raw/` is readable only by the pipeline. It is not part of the consumer IAM policy.

## 3. Common columns

| column | type | nullable | meaning |
|---|---|---|---|
| `interval_start` | timestamp[us, UTC] | no | valid time, as Open-Meteo stamps it (§4: the instant, or the end of an hourly sum or mean) |
| `interval_minutes` | int32 | no | 60 |
| `posted_at` | timestamp[us, UTC] | no | when the forecast was known (§5) |
| `ingested_at` | timestamp[us, UTC] | no | when this pipeline wrote the row |
| `source` | string | no | `live` (polled) or `previous_runs` (backfilled) |
| `schema_version` | int32 | no | curated schema version of the row |

## 4. Tables

### `forecast`: `openmeteo-gfs-seamless`

One row per valid hour and series. Grids and individual points are not stored in curated;
`raw/` keeps the points.

| column | type | nullable | meaning |
|---|---|---|---|
| `series` | string | no | `<variable>:<Zone>`, e.g. `temperature_2m:NorthCentral` |
| `value` | float64 | no | in the variable's unit, as the catalog lists it (§6) |

Business key: (`interval_start`, `series`).

- Within one posting a business key appears at most once. Ingestion refuses a posting that
  repeats one, so a single `posted_at` never holds two values for the same key.
- **Zones** are the eight ERCOT weather zones, named exactly as the ERCOT lake's load series
  name them: `Coast`, `East`, `FarWest`, `North`, `NorthCentral`, `SouthCentral`, `Southern`,
  `West`. The two lakes join on (`interval_start`, zone) with no mapping.
- A zone value is the **equal-weight mean of the zone's points** (the catalog lists them). If
  any point has no value for that hour, the zone value is dropped, never averaged over fewer
  points: `value` is never null, and a missing row means "not available".
- **Variables** are hourly Open-Meteo variables in Open-Meteo's units, with wind in m/s.
  `interval_start` is Open-Meteo's own timestamp. Instantaneous variables (temperature,
  humidity, dew point, apparent temperature, wind, cloud cover) are the value at that instant.
  `precipitation` (a sum) and `shortwave_radiation` (a mean) describe the **preceding** hour,
  as Open-Meteo defines them: the row at 14:00 covers 13:00–14:00. A consumer aligning them
  with an hour-starting series shifts them back one hour.

## 5. `posted_at`: when a forecast was known

`posted_at` is never earlier than the forecast could have been known.

- **`live`**: the fetch time of an hourly poll. A poll whose forecast equals the latest
  posting's (same rows, same values) is **not** a new posting, because nothing new was known.
  Its response is kept in `raw/` and the manifest records the check (`last_checked_at`).
- **`previous_runs`**: backfilled from Open-Meteo's Previous Runs API, where
  `<variable>_previous_dayN` at valid time `t` is the value forecast N × 24 h before `t`.
  The row's `posted_at` is `t − N days + 1 h`, the hour erring late. Lead days 1–7 are
  collected, so each valid hour has up to seven backfilled vintages.
- The two sources can hold the same business key at different `posted_at`s. The read rule
  (§7) treats them alike. A consumer that wants only true polled vintages filters
  `source = 'live'`.

## 6. Manifests and the catalog

### `manifests/<product>/latest.json`

Written by every poll.

| field | type | meaning |
|---|---|---|
| `product` | string | product key |
| `last_posted_at` | ISO 8601 UTC | newest live posting in the lake |
| `last_checked_at` | ISO 8601 UTC | last poll, whether or not it found a new posting |
| `valid_from`, `valid_to` | ISO 8601 UTC | first and last valid hour of the newest posting |
| `partitions` | string[] | valid dates the newest posting wrote |
| `schema_version` | int | curated schema version the pipeline writes now |
| `rows`, `dropped` | int | rows of the newest posting, and zone-hours dropped for a missing point |

### `manifests/<product>/previous_runs.json`

The backfill's coverage: one entry per valid-day window fetched, keyed `<first>_<last>`, with
`fetched_at`, `rows` and `dropped`.

Other fields may appear in either manifest; consumers must ignore unknown fields.

### `manifests/_catalog.json`

```json
{
  "contract_version": "1.0.0",
  "generated_at": "2026-10-13T00:00:00Z",
  "business_key": ["interval_start", "series"],
  "products": {
    "openmeteo-gfs-seamless": {
      "name": "Open-Meteo GFS seamless (HRRR + GFS), hourly",
      "source": "open-meteo",
      "model": "gfs_seamless",
      "interval_minutes": 60,
      "schema_version": 1,
      "variables": {"temperature_2m": "°C", "wind_speed_100m": "m/s"},
      "zones": {"Coast": [{"name": "Houston", "lat": 29.7604, "lon": -95.3698}]},
      "live": true
    }
  }
}
```

(Trimmed: the catalog lists every variable and every zone's points.)

- The catalog is the list of what this lake holds, and the units and zone definitions
  consumers should use, so they need no copy of the pipeline's configuration.
- `live: false`: the product is no longer collected. Its data stays readable.
- A product missing from the catalog is not in this lake.
- `weather_lake.WeatherReader` reads the catalog first and refuses a lake whose contract major
  version differs from its own (`IncompatibleContractError`).

## 7. The point-in-time read rule

The answer to "what was forecast at `as_of`" for a product and a valid-time range is:

1. Read every curated file of the valid-date partitions covering the range.
2. Keep only rows where `posted_at <= as_of`.
3. Within each business key, keep the row with the greatest `posted_at` (ties, which only a
   live and a backfilled row could produce, go to the greatest `ingested_at`).

```sql
SELECT *
FROM read_parquet(<files>, union_by_name = true)
WHERE posted_at <= $as_of
QUALIFY row_number() OVER (
  PARTITION BY interval_start, series ORDER BY posted_at DESC, ingested_at DESC
) = 1
```

- A read without an `as_of` is looking at the future. `WeatherReader` has no method that
  omits it: `snapshot(..., as_of=)` applies this rule, and `postings(..., as_of=)` returns
  every version posted by `as_of` for an as-of join.
- `ingested_at` is the second clock. A replay that needs "what *this system* had at T" filters
  on `ingested_at <= T` as well. Backfilled rows have `ingested_at` much later than
  `posted_at`.
- List files per valid day. A `date=*` glob over S3 lists the whole product prefix.

## 8. Cross-repository outputs (SSM Parameter Store)

| parameter | value |
|---|---|
| `/weather-lake/lake_bucket` | bucket name |
| `/weather-lake/lake_bucket_arn` | bucket ARN |
| `/weather-lake/lake_read_policy_arn` | managed policy: GetObject/ListBucket on `curated/*`, `manifests/*` |
| `/weather-lake/region` | region |
| `/weather-lake/contract_version` | e.g. `1.0.0` |

Consumers attach `lake_read_policy_arn` to their roles. They never receive write access.

## 9. Attribution

Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Anything derived from this lake and
shown to others carries that credit.
