"""scripts/lab/link_pcap.py, the OSPF and BGP timeline of a lab link, on captures built here.

No OSPF capture exists yet. The OSPF packets follow RFC 2328 appendix A.3 and the frames reuse
tests/test_bgp_pcap.py's builders, with checksums left at zero because nothing reads them. The
one real capture, the 2026-11-20 hold-timer run's BGP-only pcap, must read exactly as
bgp_pcap.py reads it.
"""

from __future__ import annotations

import importlib.util
import socket
import struct
import sys

import pytest
from test_bgp_pcap import KEEPALIVE, PSH_ACK, _frame, _pcap

R1, R2 = "1.1.1.1", "1.1.1.2"
ALL_SPF_ROUTERS = "224.0.0.5"
AREA0 = "0.0.0.0"


@pytest.fixture
def link_pcap(root, monkeypatch):
    path = root / "scripts" / "lab" / "link_pcap.py"
    # the script puts its own directory on sys.path to import bgp_pcap; keep that to this test
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("link_pcap", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "link_pcap", module)
    spec.loader.exec_module(module)
    return module


def _ospf(kind, router_id, body, version=2):
    header = struct.pack(
        "!BBH4s4sHH8s",
        version,
        kind,
        24 + len(body),
        socket.inet_aton(router_id),
        socket.inet_aton(AREA0),
        0,
        0,
        b"",
    )
    return header + body


def _hello(router_id, dr, bdr, neighbors, hello=1, dead=4):
    body = struct.pack(
        "!4sHBBI4s4s",
        socket.inet_aton("255.255.255.0"),
        hello,
        0x12,
        1,
        dead,
        socket.inet_aton(dr),
        socket.inet_aton(bdr),
    )
    return _ospf(1, router_id, body + b"".join(socket.inet_aton(n) for n in neighbors))


def _ospf_frame(src, dst, payload, vlan=None):
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0xC0,
        20 + len(payload),
        0,
        0,
        1,
        89,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    ethernet = b"\x01\x00\x5e\x00\x00\x05" + b"\x52\x54\x00\x00\x00\x01"
    if vlan is not None:
        ethernet += struct.pack("!HH", 0x8100, vlan)
    frame = ethernet + struct.pack("!H", 0x0800) + ip + payload
    return frame + b"\x00" * max(0, 60 - len(frame))  # Ethernet pads short frames to 60 bytes


def test_hellos_show_their_timers_dr_bdr_and_neighbors(link_pcap):
    capture = _pcap(
        [
            (10.0, _ospf_frame(R1, ALL_SPF_ROUTERS, _hello("1.1.1.1", R2, R1, ["2.2.2.2"]))),
            (14.5, _ospf_frame(R1, ALL_SPF_ROUTERS, _hello("1.1.1.1", R1, "0.0.0.0", []))),
        ]
    )
    assert link_pcap.summarize(capture) == [
        "   0.000  1.1.1.1 -> 224.0.0.5  OSPF Hello rid 1.1.1.1 area 0.0.0.0 hello 1 dead 4"
        " dr 1.1.1.2 bdr 1.1.1.1 neighbors 2.2.2.2",
        "   4.500  1.1.1.1 -> 224.0.0.5  OSPF Hello rid 1.1.1.1 area 0.0.0.0 hello 1 dead 4"
        " dr 1.1.1.1 bdr 0.0.0.0 neighbors none",
    ]


def test_a_hello_with_two_neighbors_lists_both(link_pcap):
    hello = _hello("2.2.2.2", R2, R1, ["1.1.1.1", "3.3.3.3"], hello=10, dead=40)
    assert link_pcap.describe_ospf(hello) == (
        "OSPF Hello rid 2.2.2.2 area 0.0.0.0 hello 10 dead 40 dr 1.1.1.2 bdr 1.1.1.1"
        " neighbors 1.1.1.1,3.3.3.3"
    )


def test_database_description_flags_and_update_lsa_counts(link_pcap):
    dd = _ospf(2, "2.2.2.2", struct.pack("!HBBI", 1500, 0x42, 0x07, 4660))
    dd_more = _ospf(2, "1.1.1.1", struct.pack("!HBBI", 1500, 0x42, 0x02, 4661))
    update = _ospf(4, "2.2.2.2", struct.pack("!I", 2) + b"\x00" * 40)
    single = _ospf(4, "1.1.1.1", struct.pack("!I", 1) + b"\x00" * 20)
    capture = _pcap(
        [
            (1.0, _ospf_frame(R2, R1, dd)),
            (1.1, _ospf_frame(R1, R2, dd_more)),
            (1.2, _ospf_frame(R2, R1, _ospf(3, "2.2.2.2", b"\x00" * 12))),
            (1.3, _ospf_frame(R2, R1, update)),
            (1.4, _ospf_frame(R1, "224.0.0.6", single)),
            (1.5, _ospf_frame(R1, "224.0.0.6", _ospf(5, "1.1.1.1", b"\x00" * 20))),
        ]
    )
    assert link_pcap.summarize(capture) == [
        "   0.000  1.1.1.2 -> 1.1.1.1  OSPF DB Description rid 2.2.2.2 area 0.0.0.0 [I,M,MS] seq 4660",
        "   0.100  1.1.1.1 -> 1.1.1.2  OSPF DB Description rid 1.1.1.1 area 0.0.0.0 [M] seq 4661",
        "   0.200  1.1.1.2 -> 1.1.1.1  OSPF LS Request rid 2.2.2.2 area 0.0.0.0",
        "   0.300  1.1.1.2 -> 1.1.1.1  OSPF LS Update rid 2.2.2.2 area 0.0.0.0 (2 LSAs)",
        "   0.400  1.1.1.1 -> 224.0.0.6  OSPF LS Update rid 1.1.1.1 area 0.0.0.0 (1 LSA)",
        "   0.500  1.1.1.1 -> 224.0.0.6  OSPF LS Acknowledgment rid 1.1.1.1 area 0.0.0.0",
    ]


def test_a_tagged_bgp_keepalive_names_its_vlan(link_pcap):
    capture = _pcap(
        [
            (5.0, _frame(R1, 11000, R2, 179, 1, PSH_ACK, KEEPALIVE)),
            (5.5, _frame(R1, 12000, R2, 179, 1, PSH_ACK, KEEPALIVE, vlan=100)),
        ]
    )
    assert link_pcap.summarize(capture) == [
        "   0.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  KEEPALIVE",
        "   0.500  vlan 100  1.1.1.1:12000 -> 1.1.1.2:179  [PSH,ACK]  KEEPALIVE",
    ]


def test_ospf_and_bgp_interleave_in_capture_order_on_one_clock(link_pcap):
    capture = _pcap(
        [
            (20.0, _ospf_frame(R2, ALL_SPF_ROUTERS, _hello("2.2.2.2", R2, R1, ["1.1.1.1"]))),
            (20.4, _frame(R2, 179, R1, 11000, 900, PSH_ACK, KEEPALIVE)),
            (20.9, _ospf_frame(R1, ALL_SPF_ROUTERS, _hello("1.1.1.1", R2, R1, ["2.2.2.2"]), vlan=100)),
            (21.0, _frame(R1, 22, R2, 40000, 1, PSH_ACK, b"ssh")),  # neither protocol
            (21.4, _frame(R2, 179, R1, 11000, 900, PSH_ACK, KEEPALIVE)),
        ]
    )
    assert link_pcap.summarize(capture) == [
        "   0.000  1.1.1.2 -> 224.0.0.5  OSPF Hello rid 2.2.2.2 area 0.0.0.0 hello 1 dead 4"
        " dr 1.1.1.2 bdr 1.1.1.1 neighbors 1.1.1.1",
        "   0.400  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  KEEPALIVE",
        "   0.900  vlan 100  1.1.1.1 -> 224.0.0.5  OSPF Hello rid 1.1.1.1 area 0.0.0.0 hello 1 dead 4"
        " dr 1.1.1.2 bdr 1.1.1.1 neighbors 2.2.2.2",
        "   1.400  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  KEEPALIVE  (retransmission)",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        _hello("1.1.1.1", R2, R1, ["2.2.2.2"])[:30],  # cut inside the hello body
        _hello("1.1.1.1", R2, R1, [])[:20],  # cut inside the common header
        _ospf(2, "2.2.2.2", b"\x00" * 4),  # a database description without its sequence number
        _ospf(4, "2.2.2.2", b""),  # an update without its LSA count
        _ospf(1, "1.1.1.1", b"\x00" * 20, version=3),  # OSPFv3 is not decoded
        _ospf(9, "1.1.1.1", b""),  # no such OSPFv2 packet type
        _ospf(1, "1.1.1.1", b"\x00" * 10),  # a hello whose own length leaves no room for its body
    ],
    ids=["hello-cut", "header-cut", "dd-short", "update-short", "ospfv3", "unknown-type", "hello-short"],
)
def test_a_truncated_or_unknown_ospf_packet_is_shown_as_malformed(link_pcap, payload):
    capture = _pcap([(1.0, _ospf_frame(R1, ALL_SPF_ROUTERS, payload))])
    assert link_pcap.summarize(capture) == ["   0.000  1.1.1.1 -> 224.0.0.5  OSPF (malformed)"]


def test_a_hello_whose_length_field_claims_more_than_the_packet_holds_is_malformed(link_pcap):
    hello = bytearray(_hello("1.1.1.1", R2, R1, ["2.2.2.2"]))
    struct.pack_into("!H", hello, 2, len(hello) + 4)
    assert link_pcap.describe_ospf(bytes(hello)) == "OSPF (malformed)"


def test_a_capture_with_neither_protocol_says_so(link_pcap):
    capture = _pcap([(1.0, _frame(R1, 22, R2, 40000, 1, PSH_ACK, b"ssh"))])
    assert link_pcap.summarize(capture) == ["no OSPF packets or BGP segments"]
    assert link_pcap.summarize(_pcap([])) == ["no OSPF packets or BGP segments"]


def test_the_published_bgp_capture_reads_exactly_as_bgp_pcap_reads_it(root, link_pcap):
    pcap_dir = root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer-pcap"
    lines = link_pcap.summarize((pcap_dir / "link.pcap").read_bytes())
    assert lines == (pcap_dir / "summary.txt").read_text(encoding="utf-8").splitlines()
    assert lines == link_pcap.bgp_pcap.summarize((pcap_dir / "link.pcap").read_bytes())


def test_cli_prints_the_timeline_and_refuses_pcapng_and_non_pcap_input(link_pcap, tmp_path, capsys):
    good, pcapng, text = tmp_path / "link.pcap", tmp_path / "link.pcapng", tmp_path / "notes.txt"
    good.write_bytes(_pcap([(1.0, _ospf_frame(R1, ALL_SPF_ROUTERS, _hello("1.1.1.1", R1, "0.0.0.0", [])))]))
    pcapng.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 40)
    text.write_bytes(b"hello")
    assert link_pcap.main(["link_pcap.py", str(good)]) == 0
    assert capsys.readouterr().out == (
        "   0.000  1.1.1.1 -> 224.0.0.5  OSPF Hello rid 1.1.1.1 area 0.0.0.0 hello 1 dead 4"
        " dr 1.1.1.1 bdr 0.0.0.0 neighbors none\n"
    )
    assert link_pcap.main(["link_pcap.py", str(pcapng)]) == 2
    assert "editcap" in capsys.readouterr().out
    assert link_pcap.main(["link_pcap.py", str(text)]) == 2
    assert "not a pcap file" in capsys.readouterr().out
    assert link_pcap.main(["link_pcap.py"]) == 2
    assert capsys.readouterr().out == "usage: link_pcap.py <file.pcap>\n"
