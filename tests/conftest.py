from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterator
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


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Entry points configure the root logger; drop what a test added, so later tests do not
    write to a captured stream that is already closed."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    for h in root.handlers[:]:
        if h not in before:
            root.removeHandler(h)
