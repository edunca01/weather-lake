# 0005. When a forecast was known, and UTC partitions

Date: 2026-10-01
Status: accepted

## Context

ERCOT stamps each document with its posting time. Open-Meteo stamps nothing: a response is
simply the latest forecast at the moment of the request. The lake has to decide what
`posted_at` means, for both live polls and backfilled vintages, so that a reader at `as_of`
never sees a forecast that did not exist yet.

ERCOT data is partitioned by the Central-time delivery day because settlement works that way.
Weather has no settlement day.

## Decision

- **Live:** `posted_at` is the **fetch time**. The forecast certainly existed then.
  - A poll whose curated rows equal the newest posting's is not a new posting: nothing new was
    known. It is kept in `raw/` and recorded in the manifest (`last_checked_at`), so freshness
    measures polling, not whether the weather model changed its mind.
- **Backfill:** for `<variable>_previous_dayN` at valid time `t`, Open-Meteo's value forecast
  N × 24 h before `t`, `posted_at` is `t − N days + 1 h`. The added hour errs late: a
  backfilled vintage is never visible earlier than a live poll could have seen it. Rows are
  marked `source = previous_runs`.
- Live rows and backfilled rows share the table and the read rule. A reader that wants only
  polled vintages filters on `source`.
- **Partitions are UTC dates**, by valid time in curated and by fetch time in raw. UTC has no
  daylight-saving transitions, and consumers filter on `interval_start`, never on a partition
  name.

## Consequences

- Live vintages are exact to the hour of polling. Backfilled ones are approximate, and late
  rather than early, which costs a little accuracy and never leaks.
- Skipping unchanged polls keeps an hourly poller from multiplying identical postings.
- A reader joining weather to ERCOT works in UTC timestamps; the different partition calendars
  of the two lakes never meet.
