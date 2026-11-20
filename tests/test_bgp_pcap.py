"""scripts/lab/bgp_pcap.py, the packet summary for a lab run, on captures built here byte by byte.

No real capture exists yet. These frames follow the layouts in RFC 791 (IPv4), RFC 9293 (TCP),
and RFC 4271 (BGP), with checksums left at zero because the summary does not read them.
"""

from __future__ import annotations

import importlib.util
import socket
import struct
import sys

import pytest

R1, R2 = "1.1.1.1", "1.1.1.2"
ACK, PSH_ACK, SYN = 0x10, 0x18, 0x02


@pytest.fixture
def bgp_pcap(root, monkeypatch):
    path = root / "scripts" / "lab" / "bgp_pcap.py"
    spec = importlib.util.spec_from_file_location("bgp_pcap", path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks the defining module up in sys.modules while building Segment
    monkeypatch.setitem(sys.modules, "bgp_pcap", module)
    spec.loader.exec_module(module)
    return module


def _bgp(msg_type, body=b""):
    return b"\xff" * 16 + struct.pack("!HB", 19 + len(body), msg_type) + body


KEEPALIVE = _bgp(4)
HOLD_TIMER_EXPIRED = _bgp(3, bytes([4, 0]))
ADMIN_SHUTDOWN = _bgp(3, bytes([6, 2]))
OPEN_R1 = _bgp(1, struct.pack("!BHH4sB", 4, 65001, 9, socket.inet_aton(R1), 0))


def _frame(src, sport, dst, dport, seq, flags, payload=b"", vlan=None, protocol=6):
    tcp = struct.pack("!HHIIBBHHH", sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + payload
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(tcp),
        0,
        0,
        64,
        protocol,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    ethernet = b"\x52\x54\x00\x00\x00\x02" + b"\x52\x54\x00\x00\x00\x01"
    if vlan is not None:
        ethernet += struct.pack("!HH", 0x8100, vlan)
    frame = ethernet + struct.pack("!H", 0x0800) + ip + tcp
    return frame + b"\x00" * max(0, 60 - len(frame))  # Ethernet pads short frames to 60 bytes


def _pcap(records, order="<", magic=0xA1B2C3D4, tick=1_000_000, linktype=1):
    out = struct.pack(order + "IHHiIII", magic, 2, 4, 0, 0, 65535, linktype)
    for time, frame in records:
        seconds = int(time)
        out += struct.pack(order + "IIII", seconds, round((time - seconds) * tick), len(frame), len(frame))
        out += frame
    return out


def test_hold_timer_expiry_reads_as_layers(bgp_pcap):
    capture = _pcap(
        [
            (100.0, _frame(R1, 11000, R2, 179, 500, PSH_ACK, KEEPALIVE)),
            (100.5, _frame(R2, 179, R1, 11000, 900, PSH_ACK, KEEPALIVE)),
            (100.6, _frame(R1, 11000, R2, 179, 519, ACK)),  # a bare ACK, padded to 60 bytes
            (101.0, _frame(R1, 22, R2, 40000, 1, PSH_ACK, b"ssh")),  # not BGP
            (103.5, _frame(R2, 179, R1, 11000, 919, PSH_ACK, KEEPALIVE)),
            (104.1, _frame(R2, 179, R1, 11000, 919, PSH_ACK, KEEPALIVE)),
            (109.0, _frame(R1, 11000, R2, 179, 519, PSH_ACK, HOLD_TIMER_EXPIRED)),
            (111.0, _frame(R1, 11001, R2, 179, 7000, SYN)),
        ]
    )
    assert bgp_pcap.summarize(capture) == [
        "   0.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  KEEPALIVE",
        "   0.500  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  KEEPALIVE",
        "   0.600  1.1.1.1:11000 -> 1.1.1.2:179  [ACK]",
        "   3.500  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  KEEPALIVE",
        "   4.100  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  KEEPALIVE  (retransmission)",
        "   9.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  NOTIFICATION 4/0 Hold Timer Expired",
        "  11.000  1.1.1.1:11001 -> 1.1.1.2:179  [SYN]",
    ]


def test_open_cease_and_several_messages_in_one_segment(bgp_pcap):
    capture = _pcap(
        [
            (1.0, _frame(R1, 11000, R2, 179, 1, PSH_ACK, OPEN_R1 + KEEPALIVE)),
            (2.0, _frame(R1, 11000, R2, 179, 50, PSH_ACK, ADMIN_SHUTDOWN, vlan=10)),
            (3.0, _frame(R2, 179, R1, 11000, 9, PSH_ACK, _bgp(2, b"\x00" * 30))),
        ]
    )
    assert bgp_pcap.summarize(capture) == [
        "   0.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  OPEN AS 65001 hold 9 id 1.1.1.1, KEEPALIVE",
        "   1.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  NOTIFICATION 6/2 Cease: Administrative Shutdown",
        "   2.000  1.1.1.2:179 -> 1.1.1.1:11000  [PSH,ACK]  UPDATE (49 bytes)",
    ]


def test_a_message_split_across_segments(bgp_pcap):
    update = _bgp(2, b"\x00" * 40)
    capture = _pcap(
        [
            (1.0, _frame(R2, 179, R1, 11000, 1, PSH_ACK, KEEPALIVE + update[:30])),
            (1.1, _frame(R2, 179, R1, 11000, 50, PSH_ACK, update[30:])),
            (1.2, _frame(R2, 179, R1, 11000, 69, PSH_ACK, KEEPALIVE + b"\xff" * 5)),
        ]
    )
    assert [line.split("]  ", 1)[1] for line in bgp_pcap.summarize(capture)] == [
        "KEEPALIVE, UPDATE (59 bytes) (continues in the next segment)",
        "continuation of an earlier message",
        "KEEPALIVE, partial message",
    ]


def test_big_endian_nanosecond_pcap_reads_the_same(bgp_pcap):
    records = [(5.25, _frame(R1, 11000, R2, 179, 1, PSH_ACK, KEEPALIVE))]
    [(little_time, little_frame)] = bgp_pcap.pcap_frames(_pcap(records))
    [(big_time, big_frame)] = bgp_pcap.pcap_frames(
        _pcap(records, order=">", magic=0xA1B23C4D, tick=1_000_000_000)
    )
    assert big_frame == little_frame == records[0][1]
    assert big_time == pytest.approx(5.25) and little_time == pytest.approx(5.25)


def test_refuses_what_it_cannot_read(bgp_pcap):
    with pytest.raises(ValueError, match="editcap"):
        bgp_pcap.pcap_frames(b"\x0a\x0d\x0d\x0a" + b"\x00" * 40)
    with pytest.raises(ValueError, match="not a pcap file"):
        bgp_pcap.pcap_frames(b"hello")
    with pytest.raises(ValueError, match="link type 113"):
        bgp_pcap.pcap_frames(_pcap([], linktype=113))
    with pytest.raises(ValueError, match="truncated frame"):
        bgp_pcap.pcap_frames(_pcap([(1.0, _frame(R1, 11000, R2, 179, 1, ACK))])[:-10])


def test_cli_prints_the_summary_and_reports_bad_input(bgp_pcap, tmp_path, capsys):
    good, bad = tmp_path / "link.pcap", tmp_path / "link.pcapng"
    good.write_bytes(_pcap([(1.0, _frame(R1, 11000, R2, 179, 1, PSH_ACK, KEEPALIVE))]))
    bad.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 40)
    assert bgp_pcap.main(["bgp_pcap.py", str(good)]) == 0
    assert capsys.readouterr().out == "   0.000  1.1.1.1:11000 -> 1.1.1.2:179  [PSH,ACK]  KEEPALIVE\n"
    assert bgp_pcap.main(["bgp_pcap.py", str(bad)]) == 2
    assert "editcap" in capsys.readouterr().out
    assert bgp_pcap.summarize(_pcap([])) == ["no TCP segments to or from port 179"]
