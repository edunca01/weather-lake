"""docs/CONTRACT.md matches weather_lake.contract.

Parses the column tables in §3-§4, the business-key line, the layout and the version header,
and compares them to the code, so the published contract cannot drift from what the library
enforces.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from ingest.config import load_settings
from weather_lake import contract as c

DOC = Path(__file__).resolve().parents[1] / "docs" / "CONTRACT.md"

TYPES = {
    "timestamp[us, UTC]": pa.timestamp("us", tz="UTC"),
    "int32": pa.int32(),
    "string": pa.string(),
    "float64": pa.float64(),
}
ROW = re.compile(r"^\|\s*`(?P<name>[a-z_]+)`\s*\|\s*(?P<type>[^|]+?)\s*\|\s*(?P<null>yes|no)\s*\|")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^#{2,3} ", text[start + len(heading) :], re.M)
    return text[start : start + len(heading) + (nxt.start() if nxt else len(text))]


def _columns(section: str) -> list[tuple[str, pa.DataType, bool]]:
    out = []
    for line in section.splitlines():
        m = ROW.match(line)
        if m:
            out.append((m["name"], TYPES[m["type"]], m["null"] == "yes"))
    return out


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text()


def test_versions(doc: str) -> None:
    assert f"Contract version: **{c.CONTRACT_VERSION}**" in doc
    assert f"Curated schema version:\n**{c.SCHEMA_VERSION}**" in doc


def test_forecast_columns_and_business_key(doc: str) -> None:
    common = _columns(_section(doc, "## 3. Common columns"))
    table = _section(doc, "### `forecast`")
    expected = [(f.name, f.type, f.nullable) for f in c.FORECAST_SCHEMA]
    assert common + _columns(table) == expected
    key = re.search(r"Business key: \(([^)]*)\)", table)
    assert key, "no business key line under forecast"
    assert tuple(re.findall(r"`([a-z_]+)`", key[1])) == c.BUSINESS_KEY


def test_every_product_is_listed_under_its_table(doc: str) -> None:
    heading = re.search(r"^### `forecast`: (.+)$", doc, re.M)
    assert heading
    assert set(re.findall(r"`([a-z0-9-]+)`", heading[1])) == set(load_settings().products)


def test_sources_and_zones(doc: str) -> None:
    common = _section(doc, "## 3. Common columns")
    assert set(re.findall(r"`(live|previous_runs)`", common)) == c.SOURCES
    for zone in load_settings().zones:
        assert f"`{zone}`" in _section(doc, "### `forecast`"), zone


def test_layout_keys(doc: str) -> None:
    layout = _section(doc, "## 2. Layout")
    t, d = datetime(2026, 9, 30, 20, 25, tzinfo=UTC), date(2026, 9, 30)
    p = "p"
    examples = {
        "raw/<product>/date=<fetch date, UTC>/fetched=<stamp>.json.gz": c.raw_key(p, t),
        "curated/<product>/date=<valid date, UTC>/part-<stamp>.parquet": c.curated_key(p, d, t),
        "curated/<product>/date=<valid date, UTC>/previous-runs.parquet": c.previous_runs_key(p, d),
        "curated/<product>/date=<valid date, UTC>/merged-<stamp>.parquet": c.merged_key(p, d, t),
        "manifests/<product>/latest.json": c.manifest_key(p),
    }
    for documented, key in examples.items():
        assert documented in layout, documented
        pattern = (
            re.escape(documented)
            .replace(re.escape("<product>"), p)
            .replace(re.escape("<fetch date, UTC>"), d.isoformat())
            .replace(re.escape("<valid date, UTC>"), d.isoformat())
            .replace(re.escape("<stamp>"), c.stamp(t))
        )
        assert re.fullmatch(pattern, key), (documented, key)
    assert c.CATALOG_KEY in layout


def test_ssm_parameters(doc: str) -> None:
    tf = (DOC.parents[1] / "infra" / "modules" / "storage" / "main.tf").read_text()
    published = re.search(r"published = \{(.*?)\n  \}", tf, re.S)
    assert published
    names = re.findall(r"^\s*([a-z_]+)\s*=", published[1], re.M)
    section = _section(doc, "## 8. Cross-repository outputs")
    assert sorted(re.findall(r"`/weather-lake/([a-z_]+)`", section)) == sorted(names)
