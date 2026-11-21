"""Copy an ncv lab run for publishing: lab passwords and certificate bodies out, raw/ left behind.

Usage: sanitize_capture.py <run dir> <new destination dir>

The stages are the run directory's subdirectories that hold a config.json: pre/ post/
restored/ for a change run, console/ ssh/ for the SSH-path run. The source is checked before
anything is created, so a run it refuses leaves no half-made destination behind.

Only config.json is edited, and only these forms, which are what the DevNet sandbox routers
carried: `enable password|secret`, `username ... password|secret`, the indented `password`
of a console or vty line, and the body of a `certificate self-signed|ca` block up to its
`quit`. For an NX-OS router (R3 in the second-platform run) it also knows two forms written
from NX-OS's documentation, not from a capture: `username <name> password <type> <hash> role
...`, which the username rule already replaces after the type, and `snmp-server user <name>
<group> auth <alg> <key> priv [<alg>] <key> localizedkey`, whose keys NX-OS derives from the
admin password, replaced from `auth` to the end. Everything else is copied as captured, so
read a copy before publishing it (line by line for a platform no capture has come from yet)
and record what was removed in the run's SOURCE.md. tests/test_lab_scripts.py pins these
rules and checks that the published fixtures are this script's own output.
"""

import json
import re
import shutil
import sys
from pathlib import Path

USAGE = (
    "usage: sanitize_capture.py <run dir holding stage directories (pre/ post/ restored/, or console/ ssh/)>"
    " <new destination dir>"
)
RUN_ORDER = ("pre", "post", "restored")
SECTIONS = ("SOURCE.json", "bgp.json", "config.json", "interface.json", "ospf.json", "routing.json")
RULES = [
    (re.compile(r"^(enable (?:password|secret)(?: \d+)?) .*$"), r"\1 <removed>"),
    (re.compile(r"^(username \S+(?: privilege \d+)? (?:password|secret)(?: \d+)?) .*$"), r"\1 <removed>"),
    (re.compile(r"^(\s+password(?: \d+)?) .*$"), r"\1 <removed>"),
    (re.compile(r"^(snmp-server user \S+(?: \S+)? auth) .*$"), r"\1 <removed>"),
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


def stages(src: Path) -> list[str]:
    """The run's stage directories: each direct subdirectory of `src` holding a config.json,
    sorted by name, except that a change run's pre/ post/ restored/ keep their run order, as
    the report lines always had them."""
    if not src.is_dir():
        return []
    names = [child.name for child in src.iterdir() if (child / "config.json").is_file()]
    return sorted(
        names, key=lambda name: (RUN_ORDER.index(name) if name in RUN_ORDER else len(RUN_ORDER), name)
    )


def problems(src: Path, dst: Path, names: list[str]) -> list[str]:
    """What stops the copy before anything is created: a section file a stage lacks, or a
    destination stage that already exists."""
    sources = [src / stage / name for stage in names for name in SECTIONS]
    missing = [f"{path} is missing" for path in sources if not path.is_file()]
    return missing + [f"{dst / stage} already exists" for stage in names if (dst / stage).exists()]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(USAGE)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    names = stages(src)
    if not names:
        print(USAGE)
        return 2
    refused = problems(src, dst, names)
    for line in refused:
        print(f"sanitize_capture.py: {line}")
    if refused:
        return 2
    # Every config is read and sanitized before the first directory is made.
    configs, reports = {}, {}
    for stage in names:
        configs[stage] = json.loads((src / stage / "config.json").read_text(encoding="utf-8"))
        reports[stage] = []
        for device, record in configs[stage].items():
            record["running"], secrets, cert_lines = sanitize(record["running"])
            reports[stage].append(
                f"{stage}/{device}: {secrets} password lines replaced, {cert_lines} certificate lines removed"
            )
    for stage in names:
        (dst / stage).mkdir(parents=True, exist_ok=False)
        for name in SECTIONS:
            shutil.copy2(src / stage / name, dst / stage / name)
        for line in reports[stage]:
            print(line)
        (dst / stage / "config.json").write_text(
            json.dumps(configs[stage], indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
