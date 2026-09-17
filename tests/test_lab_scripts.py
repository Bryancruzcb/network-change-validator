"""The lab-side scripts: the sanitizer that produced the published evidence.

scripts/lab/sanitize_capture.py is what removed the passwords and certificate bodies from
fixtures/lab-2026-09-12 before it was committed. These tests pin its rules on a synthetic
config and check that every published config.json is its own fixed point, so the evidence
in the repository is exactly what those rules leave behind.
"""

from __future__ import annotations

import importlib.util
import json


def _load_sanitizer(root):
    path = root / "scripts" / "lab" / "sanitize_capture.py"
    spec = importlib.util.spec_from_file_location("sanitize_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNTHETIC = """hostname R1
enable password 0 lab-enable
enable secret 9 $9$abcdef
username admin privilege 15 password 0 lab-admin
username cisco secret 5 $1$xyz
ip ssh server algorithm authentication password
crypto pki certificate chain TP-self-signed-1
 certificate self-signed 01
  3082 0330 3082 0218
  A003 0201 0202 0101
  \tquit
line con 0
 password lab-console
line vty 0 4
 password 7 0822455D0A16
 login
end
"""

EXPECTED = """hostname R1
enable password 0 <removed>
enable secret 9 <removed>
username admin privilege 15 password 0 <removed>
username cisco secret 5 <removed>
ip ssh server algorithm authentication password
crypto pki certificate chain TP-self-signed-1
 certificate self-signed 01
  <certificate body removed>
  \tquit
line con 0
 password <removed>
line vty 0 4
 password 7 <removed>
 login
end
"""


def test_sanitizer_replaces_passwords_and_certificate_bodies_only(root):
    sanitized, secrets, cert_lines = _load_sanitizer(root).sanitize(SYNTHETIC)
    assert sanitized == EXPECTED
    assert (secrets, cert_lines) == (6, 2)


def test_published_lab_configs_are_the_sanitizers_fixed_point(root):
    sanitize = _load_sanitizer(root).sanitize
    configs = sorted((root / "fixtures" / "lab-2026-09-12").rglob("config.json"))
    assert len(configs) == 6
    for path in configs:
        for device, record in json.loads(path.read_text(encoding="utf-8")).items():
            sanitized, secrets, _ = sanitize(record["running"])
            assert sanitized == record["running"], f"{path}:{device} would change"
            assert secrets == 0, f"{path}:{device} still has a password line the rules replace"
