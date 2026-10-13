# 0001. Record architecture decisions

Date: 2026-09-30
Status: accepted

## Context

This lake follows the design of its sibling, ercot-pit-lake, and differs from it where weather
differs from market data. Someone reading or deploying it needs both: what is inherited, and
why the differences exist.

## Decision

Use lightweight ADRs in `docs/adr/`, one per decision, numbered sequentially, as ercot-pit-lake
does. An inherited decision is cited from
[ercot-pit-lake's ADRs](https://github.com/edunca01/ercot-pit-lake/tree/main/docs/adr), not
repeated. `docs/CONTRACT.md` states the interface the decisions produce.

## Consequences

- A change that constrains future work links an ADR.
- ADRs are immutable once accepted. Write a new ADR that supersedes the old one; don't edit it.
