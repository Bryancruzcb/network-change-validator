"""Shared fixtures: repository paths, the demo intent/snapshots, and a fake pyATS lab."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from ncv.intent import Intent, load_intent
from ncv.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def demo_intent() -> Intent:
    return load_intent(ROOT / "intents/demo.yaml")


@pytest.fixture
def pre_snapshot() -> dict[str, Any]:
    return load_snapshot(ROOT / "fixtures/pre")


@pytest.fixture
def post_snapshot() -> dict[str, Any]:
    return load_snapshot(ROOT / "fixtures/post")


@pytest.fixture
def fake_lab(monkeypatch):
    """One Genie-shaped device behind a fake testbed; never touches a real lab."""
    device = Mock()
    device.connections = {"cli": {"arguments": {"init_config_commands": ["hostname unwanted"]}}}
    device.learn.side_effect = lambda feature: SimpleNamespace(info={
        "ospf": {"neighbors": {}},
        "routing": {"vrf": {"default": {"address_family": {"ipv4": {"routes": {}}}}}},
        "interface": {
            "interfaces": {"Gi1": {"oper_status": "up", "counters": {"in_errors": 0, "in_crc_errors": 0}}}
        },
    }[feature])
    device.execute.return_value = "hostname r1\n"
    module = ModuleType("genie.testbed")
    module.load = Mock(return_value=SimpleNamespace(devices={"r1": device}))
    monkeypatch.setitem(sys.modules, "genie", ModuleType("genie"))
    monkeypatch.setitem(sys.modules, "genie.testbed", module)
    return device, module.load
