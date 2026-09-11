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
        ({"adjacencies": [{"device": "r1", "protocol": "bgp", "neighbor": "1.1.1.1"}]}, "only ospf"),
    ],
)
def test_invalid_intent_has_field_context(tmp_path, change, match):
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump({"intent_id": "test", "devices": ["r1"], **change}))
    with pytest.raises(ValueError, match=match) as error:
        load_intent(path)
    assert str(path) in str(error.value)
