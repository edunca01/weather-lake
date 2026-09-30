from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from ingest import cli, handler
from ingest.config import Settings
from ingest.metrics import METRIC, NAMESPACE

from .conftest import PRODUCT


def test_cli_offline(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main_ingest(["--offline"]) == 0
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out[0]["product"] == PRODUCT and out[0]["new_posting"] and out[0]["rows"] == 432


def test_a_failing_product_fails_the_run_after_the_others(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(product: str) -> bytes:
        raise FileNotFoundError(product)

    monkeypatch.setattr(cli, "sample_body", missing)
    with pytest.raises(RuntimeError, match=f"{PRODUCT}: FileNotFoundError"):
        cli.run_products(settings, "all", offline=True)


def test_handler_polls_and_publishes_the_age(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCloudWatch:
        def put_metric_data(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    fake_boto3 = types.SimpleNamespace(client=lambda name: FakeCloudWatch())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(handler, "load_settings", lambda: settings)
    monkeypatch.setattr(
        handler, "run_products", lambda s, p, offline: cli.run_products(s, p, offline=True)
    )
    out = handler.ingest({})
    assert out["polls"][0]["new_posting"]
    [call] = calls
    assert call["Namespace"] == NAMESPACE
    [datum] = call["MetricData"]
    assert datum["MetricName"] == METRIC and 0 <= datum["Value"] < 1
