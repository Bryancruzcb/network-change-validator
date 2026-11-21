"""Genie-shaped learn output is adapted, or rejected when ambiguous."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ncv.normalize import learned_to_mapping, normalize_learn


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


def test_bgp_session_state_vrf_and_remote_as_are_normalized():
    data = {
        "info": {
            "instance": {
                "default": {
                    "vrf": {
                        "default": {
                            "neighbor": {
                                "203.0.113.1": {"session_state": "Established", "remote_as": "65100"}
                            }
                        }
                    }
                }
            }
        }
    }
    rec = normalize_learn("r1", "bgp", data)["r1"]["vrfs"]["default"]["neighbors"]["203.0.113.1"]
    assert rec == {"state": "Established", "remote_as": 65100}


def test_bgp_same_address_in_two_vrfs_is_two_records():
    data = {
        "instance": {
            "default": {
                "vrf": {
                    name: {"neighbor": {"203.0.113.1": {"session_state": "established"}}}
                    for name in ("default", "mgmt")
                }
            }
        }
    }
    vrfs = normalize_learn("r1", "bgp", data)["r1"]["vrfs"]
    assert vrfs == {
        name: {"neighbors": {"203.0.113.1": {"state": "established", "remote_as": None}}}
        for name in ("default", "mgmt")
    }


def test_bgp_same_address_twice_in_one_vrf_across_instances_is_rejected():
    data = {
        "instance": {
            name: {"vrf": {"default": {"neighbor": {"203.0.113.1": {"session_state": "Established"}}}}}
            for name in ("default", "second")
        }
    }
    with pytest.raises(
        ValueError, match="ambiguous BGP neighbor 203.0.113.1 in vrf default: multiple instances"
    ):
        normalize_learn("r1", "bgp", data)


@pytest.mark.parametrize(
    "data",
    [
        {"neighbor": {"203.0.113.1": {"session_state": "Established"}}},
        {"instance": {"default": {"neighbors": {"203.0.113.1": {"session_state": "Established"}}}}},
    ],
)
def test_bgp_neighbor_outside_any_vrf_is_rejected_not_guessed(data):
    with pytest.raises(ValueError, match="BGP neighbor 203.0.113.1 is not under a vrf"):
        normalize_learn("r1", "bgp", data)


def test_bgp_two_vrf_input_shaped_like_genie_test_data_normalizes_to_two_vrfs():
    # Shaped like Genie 26.8's IOS XE BGP Ops test data (`bgp_info`): the same peers in `default`
    # and `VRF1`, remote AS 65000, one IPv4 and one IPv6 peer each. Built here, not a capture.
    peers = {
        "2.2.2.2": {"remote_as": 65000, "session_state": "Established", "bgp_version": 4, "shutdown": False},
        "2001:2:2:2::2": {"remote_as": 65000, "session_state": "Established", "shutdown": False},
    }
    data = {
        "instance": {
            "default": {"bgp_id": 65000, "vrf": {"default": {"neighbor": peers}, "VRF1": {"neighbor": peers}}}
        }
    }
    vrfs = normalize_learn("R1", "bgp", data)["R1"]["vrfs"]
    expected = {address: {"state": "Established", "remote_as": 65000} for address in peers}
    assert vrfs == {"default": {"neighbors": expected}, "VRF1": {"neighbors": expected}}


def test_bgp_shape_without_neighbors_normalizes_to_none():
    data = {"instance": {"default": {"bgp_id": 65001, "vrf": {"default": {}}}}}
    assert normalize_learn("r1", "bgp", data) == {"r1": {"vrfs": {}}}


def test_a_learn_that_returned_no_info_is_a_failed_capture():
    # Genie's ops object for a feature the device does not run: internals, but no `info`.
    learned_nothing = SimpleNamespace(to_dict=lambda: {"attributes": None, "commands": None})
    with pytest.raises(ValueError, match="no info.*leave it out of --features"):
        learned_to_mapping(learned_nothing)


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


def test_interface_accepts_genie_ops_shape():
    data = {
        "Ethernet0/1": {
            "oper_status": "up",
            "enabled": True,
            "counters": {"in_errors": 0, "in_crc_errors": 2},
        },
        "Ethernet0/3": {"oper_status": "down", "enabled": False},
        "vrf": {"Mgmt-intf": {"interfaces": ["Ethernet0/2"]}},
    }
    interfaces = normalize_learn("r1", "interface", data)["r1"]["interfaces"]
    assert interfaces == {
        "Ethernet0/1": {"oper_status": "up", "in_errors": 0, "crc": 2},
        "Ethernet0/3": {"oper_status": "down", "in_errors": None, "crc": None},
    }


def test_interface_genie_shape_rejects_non_interface_records():
    data = {"Ethernet0/1": {"oper_status": "up"}, "summary": {"total": 4}}
    with pytest.raises(ValueError, match="unsupported"):
        normalize_learn("r1", "interface", data)


@pytest.mark.parametrize("data", [{"unexpected": {}}, {}])
@pytest.mark.parametrize("feature", ["ospf", "bgp", "routing", "interface", "unknown"])
def test_unsupported_learn_shapes_rejected(feature, data):
    with pytest.raises(ValueError, match="unsupported"):
        normalize_learn("r1", feature, data)
