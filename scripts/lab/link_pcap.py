"""One timeline of the OSPF packets and BGP segments in a packet capture of the lab link.

bgp_pcap.py lists BGP segments only. A run that loses OSPF, or OSPF and BGP together, needs
both on one clock, so this prints one line per OSPF packet and per BGP segment in capture
order, with seconds since the first line shown. An OSPF line names the packet type with the
sender's router ID and area: a Hello also shows its hello and dead intervals, the designated
and backup designated router (interface addresses, as RFC 2328 carries them), and the
neighbors it lists; a Database Description shows its I, M, and MS flags and sequence number;
a Link State Update shows how many LSAs it carries. A BGP line is exactly what bgp_pcap.py
prints for that segment. A frame tagged with 802.1Q is prefixed with its VLAN id, so a
session that rides a VLAN on the same link can be told apart.

Every OSPF body ends at the packet length in the OSPF header, not at the end of the IPv4
payload. IOS XE runs link-local signaling (RFC 5613) and appends an LLS block after the OSPF
packet on every Hello and Database Description; the IPv4 length counts it and the OSPF length
does not, so reading a Hello's neighbor list to the end of the IPv4 payload would list the LLS
bytes as about three more neighbors. A Hello therefore lists (packet length - 44) / 4
neighbors, and whatever follows the packet length is ignored. A packet whose length field is
smaller than the OSPF header or larger than the bytes present, one too short for its own
body, or one that is not OSPF version 2, is shown as `OSPF (malformed)` rather than stopping
the read.

It reads classic libpcap only, as bgp_pcap.py does, and reuses that script's frame walk and
BGP descriptions. Standard library only, and outside ncv like the rest of scripts/lab.
Usage: link_pcap.py <file.pcap>
"""

from __future__ import annotations

import socket
import struct
import sys
from pathlib import Path

# bgp_pcap.py sits next to this file and scripts/lab is not a package, so the script's own
# directory goes on the import path before the import, which therefore cannot be at the top.
HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import bgp_pcap  # noqa: E402

IPPROTO_OSPF = 89
OSPF_HEADER_LEN = 24
# RFC 2328 appendix A.3.1
OSPF_TYPES = {1: "Hello", 2: "DB Description", 3: "LS Request", 4: "LS Update", 5: "LS Acknowledgment"}
HELLO_BODY_LEN = 20  # network mask through backup designated router, before the neighbor list
DD_FLAGS = (("I", 0x04), ("M", 0x02), ("MS", 0x01))
MALFORMED = "OSPF (malformed)"
NOTHING = "no OSPF packets or BGP segments"


def ospf_packet(frame: bytes) -> tuple[int | None, str, str, bytes] | None:
    """(VLAN id or None, source, destination, the OSPF bytes) for an IPv4 protocol 89 frame,
    else None. The bytes are cut at the IPv4 total length by bgp_pcap's frame walk, so they
    may still carry an LLS block after the OSPF packet; describe_ospf cuts that off."""
    packet = bgp_pcap.ipv4_packet(frame)
    if packet is None or packet[1][9] != IPPROTO_OSPF:
        return None
    vlan, ip = packet
    header_len = (ip[0] & 0x0F) * 4
    return vlan, socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20]), ip[header_len:]


def _ip(data: bytes, offset: int) -> str:
    return socket.inet_ntoa(data[offset : offset + 4])


def describe_ospf(data: bytes) -> str:
    """One OSPFv2 packet in words (RFC 2328 appendix A.3), from its common header and body.
    The body ends at the header's packet length; bytes after it (an LLS block) are not read."""
    if len(data) < OSPF_HEADER_LEN:
        return MALFORMED
    version, kind, length = struct.unpack_from("!BBH", data, 0)
    if version != 2 or kind not in OSPF_TYPES or not OSPF_HEADER_LEN <= length <= len(data):
        return MALFORMED
    body = data[OSPF_HEADER_LEN:length]  # not data[OSPF_HEADER_LEN:]: an LLS block may follow
    text = f"OSPF {OSPF_TYPES[kind]} rid {_ip(data, 4)} area {_ip(data, 8)}"
    if kind == 1:
        if len(body) < HELLO_BODY_LEN or (len(body) - HELLO_BODY_LEN) % 4:
            return MALFORMED
        (hello,) = struct.unpack_from("!H", body, 4)
        (dead,) = struct.unpack_from("!I", body, 8)
        neighbors = [_ip(body, offset) for offset in range(HELLO_BODY_LEN, len(body), 4)]
        listed = ",".join(neighbors) or "none"
        return f"{text} hello {hello} dead {dead} dr {_ip(body, 12)} bdr {_ip(body, 16)} neighbors {listed}"
    if kind == 2:
        if len(body) < 8:
            return MALFORMED
        flags = ",".join(name for name, bit in DD_FLAGS if body[3] & bit)
        (seq,) = struct.unpack_from("!I", body, 4)
        return f"{text} [{flags}] seq {seq}"
    if kind == 4:
        if len(body) < 4:
            return MALFORMED
        (count,) = struct.unpack_from("!I", body, 0)
        return f"{text} ({count} LSA{'' if count == 1 else 's'})"
    return text


def summarize(data: bytes) -> list[str]:
    """The report: one line per OSPF packet and per BGP-port segment, oldest first. For a
    capture of untagged BGP alone it is exactly bgp_pcap.summarize's report."""
    events: list[tuple[float, int | None, str | bgp_pcap.Segment]] = []
    for time, frame in bgp_pcap.pcap_frames(data):
        segment = bgp_pcap.tcp_segment(time, frame)
        if segment:
            events.append((time, segment.vlan, segment))
            continue
        packet = ospf_packet(frame)
        if packet:
            vlan, src, dst, ospf = packet
            events.append((time, vlan, f"{src} -> {dst}  {describe_ospf(ospf)}"))
    if not events:
        return [NOTHING]
    # A BGP segment's description depends on the segments before it (retransmissions), so the
    # BGP ones are described together and then put back in their places.
    segments = [what for _, _, what in events if isinstance(what, bgp_pcap.Segment)]
    described = iter(bgp_pcap.describe_segments(segments))
    start = events[0][0]
    lines = []
    for time, vlan, what in events:
        text = next(described) if isinstance(what, bgp_pcap.Segment) else what
        tag = f"vlan {vlan}  " if vlan is not None else ""
        lines.append(f"{time - start:8.3f}  {tag}{text}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: link_pcap.py <file.pcap>")
        return 2
    try:
        lines = summarize(Path(argv[1]).read_bytes())
    except (OSError, ValueError) as err:
        print(f"link_pcap.py: {err}")
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
