"""Copy an ncv lab run for publishing: lab passwords and certificate bodies out, raw/ left behind.

Usage: sanitize_capture.py <run dir holding pre/ post/ restored/> <new destination dir>

Only config.json is edited, and only these forms, which are what the DevNet sandbox routers
carried: `enable password|secret`, `username ... password|secret`, the indented `password`
of a console or vty line, and the body of a `certificate self-signed|ca` block up to its
`quit`. Everything else is copied as captured, so read a copy before publishing it and
record what was removed in the run's SOURCE.md. tests/test_lab_scripts.py pins these rules
and checks that the published fixtures are this script's own output.
"""

import json
import re
import shutil
import sys
from pathlib import Path

USAGE = "usage: sanitize_capture.py <run dir holding pre/ post/ restored/> <new destination dir>"
SECTIONS = ("SOURCE.json", "bgp.json", "config.json", "interface.json", "ospf.json", "routing.json")
STAGES = ("pre", "post", "restored")
RULES = [
    (re.compile(r"^(enable (?:password|secret)(?: \d+)?) .*$"), r"\1 <removed>"),
    (re.compile(r"^(username \S+(?: privilege \d+)? (?:password|secret)(?: \d+)?) .*$"), r"\1 <removed>"),
    (re.compile(r"^(\s+password(?: \d+)?) .*$"), r"\1 <removed>"),
]
CERT_START = re.compile(r"^\s+certificate (?:self-signed|ca) \S+")


def sanitize(text: str) -> tuple[str, int, int]:
    """Return the sanitized config, the password lines replaced, and the certificate lines dropped."""
    out: list[str] = []
    in_cert, secrets, cert_lines = False, 0, 0
    for line in text.splitlines():
        if in_cert:
            if line.strip() == "quit":
                in_cert = False
                out.append(line)
            else:
                cert_lines += 1
            continue
        if CERT_START.match(line):
            out.extend([line, "  <certificate body removed>"])
            in_cert = True
            continue
        new = line
        for pattern, replacement in RULES:
            new = pattern.sub(replacement, new)
        if new != line:
            secrets += 1
        out.append(new)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), secrets, cert_lines


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(USAGE)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    for stage in STAGES:
        (dst / stage).mkdir(parents=True, exist_ok=False)
        for name in SECTIONS:
            shutil.copy2(src / stage / name, dst / stage / name)
        config_path = dst / stage / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for device, record in config.items():
            record["running"], secrets, cert_lines = sanitize(record["running"])
            print(
                f"{stage}/{device}: {secrets} password lines replaced, {cert_lines} certificate lines removed"
            )
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
