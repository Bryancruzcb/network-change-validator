"""Genie-shaped learn output is adapted, or rejected when ambiguous."""

from __future__ import annotations

import pytest

from ncv.normalize import normalize_learn


def test_ospf_preserves_parent_interface():
    data = {
        "info": {
            "vrf": {
                "default": {
                    "address_family": {
                        "ipv4": {
                            "instance": {
                                "1": {
                                    "areas": {
                                        "0.0.0.0": {
                                            "interfaces": {
                                                "Gi1": {
                                                    "neighbors": {
                                                        "10.0.0.2": {"state": "FULL", "address": "10.0.0.2"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    neighbor = normalize_learn("r1", "ospf", data)["r1"]["neighbors"]["10.0.0.2"]
    assert neighbor == {"state": "FULL", "interface": "Gi1"}


def test_ospf_duplicate_neighbor_is_rejected():
    data = {
        "vrf": {
            "default": {
                "interfaces": {
                    name: {"neighbors": {"10.0.0.2": {"state": "FULL"}}} for name in ("Gi1", "Gi2")
                }
            }
        }
    }
    with pytest.raises(ValueError, match="ambiguous OSPF"):
        normalize_learn("r1", "ospf", data)


def test_routing_uses_source_protocol_not_route_preference():
    data = {
        "vrf": {
            "default": {
                "address_family": {
                    "ipv4": {
                        "routes": {
                            "10.0.0.0/24": {"source_protocol": "ospf", "route_preference": 110},
                            "10.1.0.0/24": {"route_preference": 110},
                        }
                    }
                }
            }
        }
    }
    routes = normalize_learn("r1", "routing", data)["r1"]["vrfs"]["default"]["routes"]
    assert routes["10.0.0.0/24"]["protocol"] == "ospf"
    assert routes["10.1.0.0/24"]["protocol"] is None


def test_interface_missing_counters_remain_unknown():
    data = {"info": {"interfaces": {"Gi1": {"oper_status": "up", "counters": {"in_errors": "0"}}}}}
    rec = normalize_learn("r1", "interface", data)["r1"]["interfaces"]["Gi1"]
    assert rec == {"oper_status": "up", "in_errors": 0, "crc": None}


@pytest.mark.parametrize("feature", ["ospf", "routing", "interface", "unknown"])
def test_unsupported_learn_shapes_rejected(feature):
    with pytest.raises(ValueError, match="unsupported"):
        normalize_learn("r1", feature, {"unexpected": {}})
