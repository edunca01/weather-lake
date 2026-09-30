from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingest.config import CONFIG_PATH, Settings, load_settings


def test_the_repo_config_loads() -> None:
    s = load_settings()
    assert "openmeteo-gfs-seamless" in s.products
    assert len(s.zones) == 8 and len(s.points()) == 22
    assert s.points()[0][0] == "Coast"


def test_lake_root_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKE_ROOT", "s3://bucket")
    s = load_settings()
    assert s.lake.root == "s3://bucket" and s.lake.is_s3


def test_unknown_keys_and_empty_zones_are_rejected(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    raw["surprise"] = 1
    with pytest.raises(ValueError, match="surprise"):
        Settings.model_validate(raw)
    raw.pop("surprise")
    raw["zones"]["Coast"] = []
    with pytest.raises(ValueError, match="at least one point"):
        Settings.model_validate(raw)


def test_unknown_product(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="unknown product"):
        load_settings().product("nope")
