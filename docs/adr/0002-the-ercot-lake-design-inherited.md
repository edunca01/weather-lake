# 0002. The ERCOT lake's design, inherited

Date: 2026-09-30
Status: accepted

## Context

This lake exists for the same reason as ercot-pit-lake: a model must be trained and judged on
only what was known at the time. Its first consumer, a forecaster, reads both lakes and joins
them. Two lakes with different read rules, layouts or operational shapes would make that join
a source of leaks and of work. ercot-pit-lake's
[ADR 0009](https://github.com/edunca01/ercot-pit-lake/blob/main/docs/adr/0009-a-family-of-point-in-time-lakes.md)
decides that the lakes form a family with one contract shape.

## Decision

Inherit, unchanged, from ercot-pit-lake:

- **The stack** (its ADR 0002): EventBridge Scheduler, Lambda, S3 and DuckDB; no orchestrator,
  warehouse or database; one freshness alarm.
- **Immutable raw, point-in-time curated** (its ADR 0003): every response is stored under
  `raw/` before it is parsed and never changed; curated Parquet carries `interval_start`,
  `posted_at` and `ingested_at`; readers apply `posted_at <= as_of`, then the latest posting
  per business key, and the read library has no method without `as_of`.
- **Public code, private deployment** (its ADR 0007): this repository holds code, modules and
  docs; a deployment is its own Terraform root, kept elsewhere.
- **The contract shape**: manifests, a catalog that carries the business key, compaction that
  never drops a row, a `verify` command, and SSM outputs under the lake's own prefix.

Each lake versions its own contract and ships its own read library (`weather-lake` here).
Code is copied from ercot-pit-lake rather than shared, until both lakes have run long enough
to show which parts are truly common.

## Consequences

- A consumer that reads one lake can read the other the same way.
- Copied code can drift. The duplication is deliberate and temporary; extracting a shared core
  is a later decision, made from two working lakes.
