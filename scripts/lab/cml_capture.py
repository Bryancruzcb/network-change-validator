"""Capture the R1-R2 link of the CML default-lab through the CML API: packet evidence for a run.

The CML web UI has a capture button on each link, but it needs a browser that can reach the
controller, and with the sandbox VPN running inside WSL a Windows browser cannot. This drives
the same capture through the CML 2.7 REST API (/api/v0) from where the run scripts already run.

Usage, with the CML login in NCV_CML_USER and NCV_CML_PASS (the run-*.sh scripts set them):
  cml_capture.py start              start capturing TCP port 179 on the R1-R2 link
  cml_capture.py stop <file.pcap>   stop the capture and save it

The controller is NCV_CML_HOST (default 10.10.20.161) and the lab NCV_CML_LAB (default
default-lab). The sandbox controller has a self-signed certificate, so TLS is not verified:
point this at an isolated lab only. It reads and captures; it never changes a device's
configuration. Standard library only, and outside ncv like the rest of scripts/lab.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

USAGE = "usage: cml_capture.py start | stop <file.pcap>"
DEFAULT_HOST = "10.10.20.161"
DEFAULT_LAB = "default-lab"
# The link the lab runs change: R1 Ethernet0/1 to R2 Ethernet0/1, in either direction.
LINK_ENDS = frozenset({("R1", "Ethernet0/1"), ("R2", "Ethernet0/1")})
BPF_FILTER = "tcp port 179"
MAX_SECONDS = 900  # a run takes about six minutes from the change to the end

Get = Callable[[str], object]


def find_lab(labs: list[dict], title: str) -> str:
    """The id of the one lab with this title."""
    ids = [lab["id"] for lab in labs if lab.get("lab_title") == title]
    if len(ids) != 1:
        raise LookupError(f"expected one lab titled {title!r}, found {len(ids)}")
    return ids[0]


def find_link(links: list[dict], node_labels: dict, interface_labels: dict, ends=LINK_ENDS) -> str:
    """The id of the one link whose two ends are `ends`, as (node label, interface label) pairs."""
    matches = [
        link["id"]
        for link in links
        if {
            (node_labels.get(link["node_a"]), interface_labels.get(link["interface_a"])),
            (node_labels.get(link["node_b"]), interface_labels.get(link["interface_b"])),
        }
        == set(ends)
    ]
    if len(matches) != 1:
        raise LookupError(f"expected one link joining {sorted(ends)}, found {len(matches)}")
    return matches[0]


def capture_body(seconds: int = MAX_SECONDS, bpfilter: str = BPF_FILTER) -> dict:
    """The start request: stop after `seconds`, keep only what `bpfilter` matches."""
    return {"maxtime": seconds, "bpfilter": bpfilter}


def locate(get: Get, title: str, ends=LINK_ENDS) -> tuple[str, str]:
    """(lab id, link id) of the capture target, read through `get(path) -> parsed JSON`."""
    lab_id = find_lab([get(f"/labs/{lab}") for lab in get("/labs")], title)
    links = get(f"/labs/{lab_id}/links?data=true")
    nodes = {link[end] for link in links for end in ("node_a", "node_b")}
    interfaces = {link[end] for link in links for end in ("interface_a", "interface_b")}
    node_labels = {node: get(f"/labs/{lab_id}/nodes/{node}")["label"] for node in nodes}
    interface_labels = {i: get(f"/labs/{lab_id}/interfaces/{i}")["label"] for i in interfaces}
    return lab_id, find_link(links, node_labels, interface_labels, ends)


def _request(host: str, method: str, path: str, token: str | None = None, body=None) -> bytes:
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE  # the sandbox controller's certificate is self-signed
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://{host}/api/v0{path}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=tls, timeout=30) as resp:
        return resp.read()


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("start", "stop") or (argv[1] == "stop") != (len(argv) == 3):
        print(USAGE)
        return 2
    host = os.environ.get("NCV_CML_HOST", DEFAULT_HOST)
    title = os.environ.get("NCV_CML_LAB", DEFAULT_LAB)
    try:
        login = {"username": os.environ["NCV_CML_USER"], "password": os.environ["NCV_CML_PASS"]}
    except KeyError as missing:
        print(f"cml_capture.py: {missing.args[0]} is not set")
        return 2
    try:
        token = json.loads(_request(host, "POST", "/authenticate", body=login))

        def get(path: str):
            return json.loads(_request(host, "GET", path, token))

        lab_id, link_id = locate(get, title)
        capture = f"/labs/{lab_id}/links/{link_id}/capture"
        if argv[1] == "start":
            _request(host, "PUT", f"{capture}/start", token, capture_body())
            print(f"capturing {BPF_FILTER} on the R1-R2 link of {title} for up to {MAX_SECONDS} s")
            return 0
        key = get(f"{capture}/key")
        _request(host, "PUT", f"{capture}/stop", token)
        pcap = _request(host, "GET", f"/pcap/{key}", token)
        Path(argv[2]).write_bytes(pcap)
        print(f"saved {len(pcap)} bytes to {argv[2]}")
        return 0
    except (urllib.error.URLError, LookupError, KeyError, ValueError, OSError) as err:
        print(f"cml_capture.py: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
