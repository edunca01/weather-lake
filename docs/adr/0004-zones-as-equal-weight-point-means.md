# 0004. ERCOT weather zones as equal-weight means of declared points

Date: 2026-09-30
Status: accepted

## Context

ERCOT reports load by eight weather zones, and its load forecasts are built from weather at
stations within them. The forecaster needs weather on the same zones, joined on time and zone
with nothing in between. ERCOT does not publish its station weights in a form that can be
used directly. Storing grids would multiply storage and leave every consumer to aggregate.

## Decision

- Curated data holds **zones, not points or grids.** Each of the eight zones (`Coast`, `East`,
  `FarWest`, `North`, `NorthCentral`, `SouthCentral`, `Southern`, `West`, spelled as
  ercot-pit-lake's load series spell them) is represented by two or three major cities
  declared in `config.yaml`.
- A zone value is the **equal-weight mean** of its points, per variable and hour.
- If any point lacks a value for an hour, that **zone-hour is dropped and counted**, never
  averaged over fewer points: a mean over a different set of cities is a different quantity.
- `raw/` keeps every point as received, and the catalog publishes the points behind each zone,
  so a consumer can see exactly what a zone value means and a different weighting can be
  replayed later.
- Changing a zone's points changes what the zone means: a minor contract release with a
  CHANGELOG note.

## Consequences

- The join to ERCOT needs no mapping table.
- Equal weights are a simplification. A forecaster can learn how each zone's load responds to
  its weather; it cannot recover a city the lake did not declare.
- Dropped zone-hours are rare and visible (`dropped` in the manifest), not silent gaps.
