"""Intent loading rejects malformed declarations with field context."""

from __future__ import annotations

import pytest
import yaml

from ncv.intent import load_intent


@pytest.mark.parametrize(
    "change,match",
    [
        ({"devices": "r1"}, "expected a list"),
        ({"version": 2}, "only version 1"),
        ({"rouets": []}, "unknown field"),
        ({"interfaces": [{"device": "r1", "name": "Gi1", "max_crc": -1}]}, "non-negative"),
        ({"interfaces": [{"device": "r1", "name": "Gi1", "max_crc": True}]}, "non-negative"),
        ({"routes": [{"device": "r3", "prefix": "10.0.0.0/24"}]}, "not declared"),
        ({"routes": [{"device": "r1", "prefix": "bad"}]}, "invalid network"),
        ({"adjacencies": [{"device": "r1", "protocol": "isis", "neighbor": "1.1.1.1"}]}, "only bgp and ospf"),
        (
            {"adjacencies": [{"device": "r1", "protocol": "bgp", "neighbor": "1.1.1.1", "interface": "Gi1"}]},
            "bgp adjacencies have no interface",
        ),
        (
            {"adjacencies": [{"device": "r1", "neighbor": "1.1.1.1", "remote_as": 65000}]},
            "ospf adjacencies have no remote_as",
        ),
        (
            {"adjacencies": [{"device": "r1", "protocol": "bgp", "neighbor": "1.1.1.1", "remote_as": -1}]},
            "non-negative",
        ),
    ],
)
def test_invalid_intent_has_field_context(tmp_path, change, match):
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump({"intent_id": "test", "devices": ["r1"], **change}))
    with pytest.raises(ValueError, match=match) as error:
        load_intent(path)
    assert str(path) in str(error.value)


def test_bgp_adjacency_keeps_its_discriminators(tmp_path):
    path = tmp_path / "intent.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "intent_id": "test",
                "devices": ["r1"],
                "adjacencies": [
                    {
                        "device": "r1",
                        "protocol": "BGP",
                        "neighbor": "203.0.113.1",
                        "vrf": "default",
                        "remote_as": 65100,
                    }
                ],
            }
        )
    )
    (adjacency,) = load_intent(path).adjacencies
    assert (adjacency.protocol, adjacency.vrf, adjacency.remote_as) == ("bgp", "default", 65100)
    assert adjacency.interface == ""
