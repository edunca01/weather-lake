from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ingest.config import LakeConfig, Settings, load_settings
from ingest.lake import Lake

SAMPLE = Path(__file__).resolve().parents[1] / "samples/openmeteo/openmeteo-gfs-seamless.json"
PRODUCT = "openmeteo-gfs-seamless"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = load_settings()
    return s.model_copy(update={"lake": LakeConfig(root=str(tmp_path / "lake"))})


@pytest.fixture
def lake(settings: Settings) -> Lake:
    return Lake(settings.lake)


@pytest.fixture
def sample() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(SAMPLE.read_text())
    return copy.deepcopy(data)
