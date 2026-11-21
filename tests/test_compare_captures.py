"""scripts/lab/compare_captures.py: whether two snapshots hold the same data.

run-ssh-path.sh captures the routers through the console server and then over SSH, and expects
this to find no difference. The snapshots here are small invented ones written to temporary
directories; no capture over SSH exists yet.
"""

from __future__ import annotations

import json

import pytest
from test_lab_scripts import _load_script

CONFIG = "hostname R1\nenable password 0 {enable}\ninterface Ethernet0/1\n ip address 1.1.1.1 255.255.255.0\n"
SECTIONS = {
    "ospf": {},
    "bgp": {},
    "routing": {"R1": {"vrfs": {"default": {"routes": {"1.1.1.0/24": {"protocol": "connected"}}}}}},
    "interface": {"R1": {"interfaces": {"Ethernet0/1": {"oper_status": "up", "in_errors": 0, "crc": 0}}}},
    "config": {"R1": {"running": CONFIG.format(enable="lab-enable")}},
}


@pytest.fixture
def compare(root):
    return _load_script(root, "compare_captures.py")


def _snapshot(directory, sections=None, source="console"):
    directory.mkdir(parents=True)
    for name, value in (sections or SECTIONS).items():
        (directory / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    (directory / "SOURCE.json").write_text(json.dumps({"testbed": source}), encoding="utf-8")
    (directory / "raw").mkdir()
    (directory / "raw" / "R1_config.txt").write_text(source, encoding="utf-8")
    return str(directory)


def _changed(**changes):
    return {**SECTIONS, **changes}


def test_identical_snapshots_from_two_testbeds_hold_the_same_data(compare, tmp_path, capsys):
    a = _snapshot(tmp_path / "console")
    b = _snapshot(tmp_path / "ssh", source="ssh")
    assert compare.main(["compare_captures.py", a, b]) == 0
    assert capsys.readouterr().out == f"{a} and {b} hold the same data\n"


def test_a_changed_leaf_is_printed_with_its_section_and_path(compare, tmp_path, capsys):
    down = {"R1": {"interfaces": {"Ethernet0/1": {"oper_status": "down", "in_errors": 0, "crc": 0}}}}
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", _changed(interface=down))
    assert compare.main(["compare_captures.py", a, b]) == 1
    assert capsys.readouterr().out.splitlines() == [
        'interface.R1.interfaces.Ethernet0/1.oper_status: "up" != "down"',
        "1 differences",
    ]


def test_a_key_on_one_side_only_shows_missing_on_the_other(compare):
    a = {"R1": {"x": 1}, "R2": {"y": [1, 2]}}
    b = {"R1": {"x": 1, "z": True}}
    assert compare.differences(a, b, "bgp") == [
        "bgp.R1.z: <missing> != true",
        'bgp.R2: {"y": [1, 2]} != <missing>',
    ]
    assert compare.differences(b, a, "bgp") == [
        "bgp.R1.z: true != <missing>",
        'bgp.R2: <missing> != {"y": [1, 2]}',
    ]
    assert compare.differences(a, a) == []
    assert compare.differences([1, 2], [2, 1], "ospf.list") == ["ospf.list: [1, 2] != [2, 1]"]


def test_a_missing_section_file_or_unreadable_json_exits_2_naming_the_file(compare, tmp_path, capsys):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b")
    (tmp_path / "b" / "bgp.json").unlink()
    assert compare.main(["compare_captures.py", a, b]) == 2
    assert "bgp.json" in capsys.readouterr().out
    (tmp_path / "a" / "ospf.json").write_text("{not json", encoding="utf-8")
    assert compare.main(["compare_captures.py", a, a]) == 2
    assert "ospf.json" in capsys.readouterr().out


@pytest.mark.parametrize("args", [[], ["one"], ["one", "two", "three"]])
def test_bad_usage_exits_2(compare, capsys, args):
    assert compare.main(["compare_captures.py", *args]) == 2
    assert capsys.readouterr().out == compare.USAGE + "\n"


def test_configs_that_differ_only_in_a_password_print_no_part_of_either(compare, tmp_path, capsys):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", _changed(config={"R1": {"running": CONFIG.format(enable="other-secret")}}))
    assert compare.main(["compare_captures.py", a, b]) == 1
    out = capsys.readouterr().out
    assert out.splitlines() == ["config.R1.running line 2 differs: <removed>", "1 differences"]
    assert "lab-enable" not in out and "other-secret" not in out


@pytest.mark.parametrize(
    "line",
    [
        "snmp-server community {value} RO",
        " key-string {value}",
        " standby 1 authentication {value}",
        " vrrp 1 authentication text {value}",
        "snmp-server host 192.0.2.1 version 2c {value}",
        " wpa-psk ascii 0 {value}",
    ],
)
def test_a_secret_line_that_differs_prints_neither_value(compare, line):
    def config(value):
        return {"R1": {"running": f"hostname R1\n{line.format(value=value)}\n"}}

    out = compare.config_differences(config("FIRST-VALUE"), config("SECOND-VALUE"))
    assert out == ["config.R1.running line 2 differs: <removed>"]


@pytest.mark.parametrize("line", ["snmp-server community ONE-SIDE RO", " key-string ONE-SIDE"])
def test_a_secret_line_on_one_side_only_is_not_printed(compare, line):
    without = {"R1": {"running": "hostname R1\n"}}
    with_line = {"R1": {"running": f"hostname R1\n{line}\n"}}
    for a, b in ((without, with_line), (with_line, without)):
        out = compare.config_differences(a, b)
        assert out == ["config.R1.running line 2 differs: <removed>"]
        assert "ONE-SIDE" not in "".join(out)


def test_other_config_lines_are_shown_cut_to_100_characters(compare):
    long = "description " + "x" * 200
    a = {"R1": {"running": "hostname R1\n" + long}}
    b = {"R1": {"running": "hostname R2\n"}}
    assert compare.config_differences(a, b) == [
        "config.R1.running line 1 differs: hostname R1 != hostname R2",
        f"config.R1.running line 2 differs: {long[:100]} != <missing>",
    ]
    assert compare.config_differences(a, {}) == ["config.R1: present != <missing>"]


def test_more_than_40_differences_print_40_and_the_count(compare, tmp_path, capsys):
    many = {
        "R1": {"vrfs": {"default": {"routes": {f"10.0.{n}.0/24": {"protocol": "static"} for n in range(45)}}}}
    }
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", _changed(routing=many))
    assert compare.main(["compare_captures.py", a, b]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 41
    assert lines[-1] == "46 differences, the first 40 shown"
    assert all(len(line.split(": ", 1)[1]) <= 100 + len(" != ") + 100 for line in lines[:-1])
