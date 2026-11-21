"""List the BGP messages in a packet capture of the lab link: packet evidence for a lab run.

Reads a classic libpcap file of Ethernet frames (what Wireshark calls "pcap", not "pcapng";
convert one with `editcap -F pcap in.pcapng out.pcap`, which ships with Wireshark) and prints
one line per TCP segment to or from port 179: seconds since the first such segment, the
endpoints, the TCP flags, and the BGP messages the segment carries. A NOTIFICATION shows its
error code and subcode by name, an OPEN its AS, hold time, and router ID, and a segment already
seen on the same flow is marked as a retransmission.

The decoding walks the layers the way Wireshark's packet pane does: Ethernet II (with an
optional 802.1Q tag), IPv4, TCP, then BGP. It reads only what that walk needs. IPv4 options
are skipped by header length, each frame is cut at the IPv4 total length so Ethernet padding is
never read as data, and a segment whose payload does not start with a BGP marker (the middle of
a message split across segments) is shown as a continuation instead of being reassembled.

Like the rest of scripts/lab this stays outside ncv, and it needs only the standard library.
Usage: bgp_pcap.py <file.pcap>
"""

from __future__ import annotations

import socket
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

BGP_PORT = 179
BGP_MARKER = b"\xff" * 16
BGP_HEADER_LEN = 19
BGP_MAX_LEN = 4096
MESSAGE_TYPES = {1: "OPEN", 2: "UPDATE", 3: "NOTIFICATION", 4: "KEEPALIVE", 5: "ROUTE-REFRESH"}
# RFC 4271 section 4.5
ERROR_CODES = {
    1: "Message Header Error",
    2: "OPEN Message Error",
    3: "UPDATE Message Error",
    4: "Hold Timer Expired",
    5: "Finite State Machine Error",
    6: "Cease",
}
# RFC 4486
CEASE_SUBCODES = {
    1: "Maximum Number of Prefixes Reached",
    2: "Administrative Shutdown",
    3: "Peer De-configured",
    4: "Administrative Reset",
    5: "Connection Rejected",
    6: "Other Configuration Change",
    7: "Connection Collision Resolution",
    8: "Out of Resources",
}
TCP_FLAGS = (("SYN", 0x02), ("FIN", 0x01), ("RST", 0x04), ("PSH", 0x08), ("ACK", 0x10))
SYN, FIN = 0x02, 0x01
# The first four bytes of a classic pcap file: byte order, and seconds per timestamp fraction.
PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e-6),
    b"\xa1\xb2\xc3\xd4": (">", 1e-6),
    b"\x4d\x3c\xb2\xa1": ("<", 1e-9),
    b"\xa1\xb2\x3c\x4d": (">", 1e-9),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
LINKTYPE_ETHERNET = 1
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_VLAN = 0x8100
IPPROTO_TCP = 6


@dataclass(frozen=True)
class Segment:
    """One TCP segment to or from the BGP port, as decoded from one frame."""

    time: float
    src: str
    sport: int
    dst: str
    dport: int
    seq: int
    flags: int
    payload: bytes
    vlan: int | None = None  # the 802.1Q VLAN id when the frame is tagged


def pcap_frames(data: bytes) -> list[tuple[float, bytes]]:
    """The (timestamp, frame bytes) records of a classic pcap file of Ethernet frames."""
    if data[:4] == PCAPNG_MAGIC:
        raise ValueError("this is pcapng; convert it with `editcap -F pcap in.pcapng out.pcap`")
    if data[:4] not in PCAP_MAGIC or len(data) < 24:
        raise ValueError("not a pcap file")
    order, tick = PCAP_MAGIC[data[:4]]
    (linktype,) = struct.unpack_from(order + "I", data, 20)
    if linktype != LINKTYPE_ETHERNET:
        raise ValueError(f"link type {linktype} is not Ethernet (1)")
    frames, offset = [], 24
    while offset < len(data):
        if offset + 16 > len(data):
            raise ValueError(f"truncated record header at byte {offset}")
        seconds, fraction, captured, _ = struct.unpack_from(order + "IIII", data, offset)
        offset += 16
        if offset + captured > len(data):
            raise ValueError(f"truncated frame at byte {offset}")
        frames.append((seconds + fraction * tick, data[offset : offset + captured]))
        offset += captured
    return frames


def ipv4_packet(frame: bytes) -> tuple[int | None, bytes] | None:
    """Decode Ethernet II and an optional 802.1Q tag: (the VLAN id or None, the IPv4 packet cut
    at its total length, so Ethernet padding is never read as data), or None unless the frame
    carries IPv4 with at least a whole header's worth of bytes."""
    if len(frame) < 14:
        return None
    (ethertype,) = struct.unpack_from("!H", frame, 12)
    ip_start, vlan = 14, None
    if ethertype == ETHERTYPE_VLAN and len(frame) >= 18:
        (tag, ethertype) = struct.unpack_from("!HH", frame, 14)
        ip_start, vlan = 18, tag & 0x0FFF
    ip = frame[ip_start:]
    if ethertype != ETHERTYPE_IPV4 or len(ip) < 20 or ip[0] >> 4 != 4:
        return None
    (total_len,) = struct.unpack_from("!H", ip, 2)
    ip = ip[:total_len]
    return (vlan, ip) if len(ip) >= 20 else None


def tcp_segment(time: float, frame: bytes) -> Segment | None:
    """Decode Ethernet, IPv4, and TCP; None unless the frame is TCP to or from port 179."""
    packet = ipv4_packet(frame)
    if packet is None or packet[1][9] != IPPROTO_TCP:
        return None
    vlan, ip = packet
    header_len = (ip[0] & 0x0F) * 4
    tcp = ip[header_len:]
    if len(tcp) < 20:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", tcp, 0)
    if BGP_PORT not in (sport, dport):
        return None
    data_offset = (tcp[12] >> 4) * 4
    return Segment(
        time=time,
        src=socket.inet_ntoa(ip[12:16]),
        sport=sport,
        dst=socket.inet_ntoa(ip[16:20]),
        dport=dport,
        seq=seq,
        flags=tcp[13],
        payload=tcp[data_offset:],
        vlan=vlan,
    )


def describe_message(msg_type: int, length: int, body: bytes) -> str:
    """One BGP message in words, from its header's type and length and the body bytes present."""
    name = MESSAGE_TYPES.get(msg_type, f"type {msg_type}")
    if msg_type == 1 and len(body) >= 9:
        _version, asn, hold = struct.unpack_from("!BHH", body, 0)
        return f"OPEN AS {asn} hold {hold} id {socket.inet_ntoa(body[5:9])}"
    if msg_type == 3 and len(body) >= 2:
        code, subcode = body[0], body[1]
        reason = ERROR_CODES.get(code, "unknown error")
        if code == 6 and subcode in CEASE_SUBCODES:
            reason += f": {CEASE_SUBCODES[subcode]}"
        return f"NOTIFICATION {code}/{subcode} {reason}"
    if msg_type == 2:
        return f"UPDATE ({length} bytes)"
    return name


def bgp_messages(payload: bytes) -> str:
    """Every BGP message in a TCP payload, described and joined by commas."""
    if not payload.startswith(BGP_MARKER):
        return "continuation of an earlier message"
    described, offset = [], 0
    while offset < len(payload):
        header = payload[offset : offset + BGP_HEADER_LEN]
        if len(header) < BGP_HEADER_LEN or not header.startswith(BGP_MARKER):
            described.append("partial message")
            break
        length, msg_type = struct.unpack_from("!HB", header, 16)
        if not BGP_HEADER_LEN <= length <= BGP_MAX_LEN:
            described.append(f"malformed header (length {length})")
            break
        body = payload[offset + BGP_HEADER_LEN : offset + length]
        text = describe_message(msg_type, length, body)
        if len(body) < length - BGP_HEADER_LEN:
            text += " (continues in the next segment)"
        described.append(text)
        offset += length
    return ", ".join(described)


def flag_names(flags: int) -> str:
    return ",".join(name for name, bit in TCP_FLAGS if flags & bit)


def describe_segments(segments: list[Segment]) -> list[str]:
    """Each segment in words, in the order given and without a time: endpoints, TCP flags, the
    BGP messages, and a retransmission mark. The whole list is needed at once, because a
    segment is a retransmission only against the ones before it."""
    seen, lines = set(), []
    for seg in segments:
        endpoints = f"{seg.src}:{seg.sport} -> {seg.dst}:{seg.dport}"
        line = f"{endpoints}  [{flag_names(seg.flags)}]"
        if seg.payload:
            line += "  " + bgp_messages(seg.payload)
        # A segment that carries data, SYN, or FIN uses sequence space; the same one again on
        # the same flow is a retransmission. A bare ACK does not, so repeats of it are normal.
        if seg.payload or seg.flags & (SYN | FIN):
            key = (seg.src, seg.sport, seg.dst, seg.dport, seg.seq, len(seg.payload), seg.flags & (SYN | FIN))
            if key in seen:
                line += "  (retransmission)"
            seen.add(key)
        lines.append(line)
    return lines


def summarize(data: bytes) -> list[str]:
    """The report: one line per BGP-port segment in the capture, oldest first."""
    segments = [s for s in (tcp_segment(t, frame) for t, frame in pcap_frames(data)) if s]
    if not segments:
        return ["no TCP segments to or from port 179"]
    start = segments[0].time
    return [
        f"{seg.time - start:8.3f}  {text}"
        for seg, text in zip(segments, describe_segments(segments), strict=True)
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bgp_pcap.py <file.pcap>")
        return 2
    try:
        lines = summarize(Path(argv[1]).read_bytes())
    except (OSError, ValueError) as err:
        print(f"bgp_pcap.py: {err}")
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
