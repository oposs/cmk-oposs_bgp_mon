"""Tests for the BGP session check (runs on the Checkmk server).

The section comes from the special agent agent_oposs_bgp_mon. It prints
`<<<oposs_bgp_mon_sessions:sep(0)>>>` and then one JSON object per session,
written with sort_keys and compact separators, so every row of the string
table holds exactly one JSON string.
"""

import importlib.util
import json
import pathlib
import re

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECK = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_bgp_mon/agent_based/oposs_bgp_mon_sessions.py"


def _load_check(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check():
    return _load_check(CHECK, "test_oposs_bgp_mon_sessions_check")


def _row(**session):
    """One string-table row, as the agent writes it."""
    return [json.dumps(session, sort_keys=True, separators=(",", ":"))]


# Sessions as each driver of the agent produces them
CISCO_UP = dict(**{"vrf-name-out": "default", "af-name": "IPv4 Unicast"},
                neighbourid="10.0.0.2", neighbouras="65001", state="Established", uptime=93784)
CISCO_IDLE = dict(**{"vrf-name-out": "default", "af-name": "IPv4 Unicast"},
                  neighbourid="10.0.0.3", neighbouras="65002", state="Idle", uptime=0)
HUAWEI_ACTIVE = dict(**{"vrf-name-out": "vpn1", "af-name": "ipv4"},
                     neighbourid="10.2.2.2", neighbouras="65003", state="Active", uptime=None)

STRING_TABLE = [_row(**CISCO_UP), _row(**CISCO_IDLE), _row(**HUAWEI_ACTIVE)]


def _results(out):
    return [r for r in out if isinstance(r, Result)]


def _metrics(out):
    return [m for m in out if isinstance(m, Metric)]


def _worst(out):
    return State.worst(*(r.state for r in _results(out)))


# --- parse and discovery ---------------------------------------------------


def test_parse_keys_sessions_by_as_and_neighbour(check):
    section = check.parse_oposs_bgp_mon_sessions(STRING_TABLE)
    assert section.inventory == ["AS65001 10.0.0.2", "AS65002 10.0.0.3", "AS65003 10.2.2.2"]
    assert section.result["AS65001 10.0.0.2"]["uptime"] == 93784
    assert section.errors == []


def test_discovery_one_service_per_session(check):
    section = check.parse_oposs_bgp_mon_sessions(STRING_TABLE)
    assert list(check.discover_sessions(section)) == [
        Service(item="AS65001 10.0.0.2"),
        Service(item="AS65002 10.0.0.3"),
        Service(item="AS65003 10.2.2.2"),
    ]


def test_empty_section_discovers_nothing(check):
    section = check.parse_oposs_bgp_mon_sessions([])
    assert list(check.discover_sessions(section)) == []


def test_plugin_registration(check):
    plugin = check.check_plugin_oposs_bgp_mon_sessions
    assert plugin.service_name == "BGP %s"
    assert plugin.sections == ["oposs_bgp_mon_sessions"]
    assert plugin.check_ruleset_name == "oposs_bgp_mon_sessions"
    assert check.agent_section_oposs_bgp_mon_sessions.supersedes == ["bgp_mon_sessions"]


# --- session state ---------------------------------------------------------


def _check(check, item, params=None, table=STRING_TABLE):
    section = check.parse_oposs_bgp_mon_sessions(table)
    return list(check.check_oposs_bgp_mon_sessions(item, params or {}, section))


def test_established_is_ok_with_uptime_metric(check):
    out = _check(check, "AS65001 10.0.0.2")
    assert _worst(out) is State.OK
    assert [r.summary for r in _results(out)] == [
        "vrf-name-out: default",
        "af-name: IPv4 Unicast",
        "neighbourid: 10.0.0.2",
        "neighbouras: 65001",
        "state: Established",
    ]
    assert _metrics(out) == [Metric("oposs_bgp_mon_uptime", 93784.0)]


def test_idle_is_crit(check):
    out = _check(check, "AS65002 10.0.0.3")
    assert _results(out)[-1] == Result(state=State.CRIT, summary="state: Idle")
    assert _metrics(out) == [Metric("oposs_bgp_mon_uptime", 0.0)]


def test_other_state_is_warn_and_null_uptime_gives_no_metric(check):
    out = _check(check, "AS65003 10.2.2.2")
    assert _results(out)[-1] == Result(state=State.WARN, summary="state: Active")
    assert _metrics(out) == []


def test_state_match_ignores_case(check):
    table = [_row(**dict(CISCO_UP, state="ESTABLISHED")), _row(**dict(CISCO_IDLE, state="idle"))]
    assert _worst(_check(check, "AS65001 10.0.0.2", table=table)) is State.OK
    assert _worst(_check(check, "AS65002 10.0.0.3", table=table)) is State.CRIT


def test_missing_state_is_warn(check):
    session = {k: v for k, v in CISCO_UP.items() if k != "state"}
    out = _check(check, "AS65001 10.0.0.2", table=[_row(**session)])
    assert _results(out)[-1] == Result(state=State.WARN, summary="state: n/a")


def test_vanished_session_is_unknown(check):
    out = _check(check, "AS65099 10.9.9.9")
    assert out == [Result(state=State.UNKNOWN, summary="Session AS65099 10.9.9.9 not found in agent output")]


# --- minimum uptime after recovery ------------------------------------------
#
# The rule form is SimpleLevels with LevelDirection.LOWER, so the check gets
# ("fixed", (warn, crit)) or ("no_levels", None) -- never a bare pair.

FLAPPED = dict(CISCO_UP, uptime=30)
SETTLING = dict(CISCO_UP, uptime=300)


@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="BUG: min_uptime unpacks the SimpleLevels tuple as (warn, crit); any rule crashes the check")
def test_min_uptime_crit_below_crit_level(check):
    out = _check(check, "AS65001 10.0.0.2", {"min_uptime": ("fixed", (600.0, 60.0))}, [_row(**FLAPPED)])
    assert _worst(out) is State.CRIT


@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="BUG: min_uptime unpacks the SimpleLevels tuple as (warn, crit); any rule crashes the check")
def test_min_uptime_warn_below_warn_level(check):
    out = _check(check, "AS65001 10.0.0.2", {"min_uptime": ("fixed", (600.0, 60.0))}, [_row(**SETTLING)])
    assert _worst(out) is State.WARN


@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="BUG: min_uptime unpacks the SimpleLevels tuple as (warn, crit); any rule crashes the check")
def test_min_uptime_ok_above_levels(check):
    out = _check(check, "AS65001 10.0.0.2", {"min_uptime": ("fixed", (600.0, 60.0))})
    assert _worst(out) is State.OK


@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="BUG: min_uptime unpacks the SimpleLevels tuple as (warn, crit); 'no levels' crashes the check")
def test_min_uptime_no_levels_is_ok(check):
    out = _check(check, "AS65001 10.0.0.2", {"min_uptime": ("no_levels", None)}, [_row(**FLAPPED)])
    assert _worst(out) is State.OK


def test_min_uptime_ignored_for_idle_session(check):
    # Never reaches the levels, so the bug above does not hit this path
    out = _check(check, "AS65002 10.0.0.3", {"min_uptime": ("fixed", (600.0, 60.0))})
    assert _worst(out) is State.CRIT


# --- garbage ---------------------------------------------------------------

# What the agent prints under the section header when a fetch fails
AGENT_FAILURE = [
    ["Traceback (most recent call last):"],
    ['  File "agent_oposs_bgp_mon", line 431, in main'],
    ["RuntimeError: Failed to fetch data"],
    ["Error: Failed to fetch data"],
]


def test_agent_failure_shows_up_as_parse_error_service(check):
    section = check.parse_oposs_bgp_mon_sessions(AGENT_FAILURE)
    assert list(check.discover_sessions(section)) == [Service(item="_parse_errors")]
    out = list(check.check_oposs_bgp_mon_sessions("_parse_errors", {}, section))
    assert out[0] == Result(state=State.WARN, summary="Failed to parse 4 BGP session(s)")
    assert len(out) == 5
    assert all(r.state is State.OK and r.details.startswith("Failed to parse") for r in out[1:])


def test_parse_error_notices_capped_at_five(check):
    section = check.parse_oposs_bgp_mon_sessions([["garbage"]] * 8)
    out = list(check.check_oposs_bgp_mon_sessions("_parse_errors", {}, section))
    assert out[0].summary == "Failed to parse 8 BGP session(s)"
    assert len(out) == 6


def test_good_rows_survive_bad_ones(check):
    section = check.parse_oposs_bgp_mon_sessions([_row(**CISCO_UP), ["{not json"], [json.dumps({"neighbourid": "x"})]])
    assert section.inventory == ["AS65001 10.0.0.2"]
    assert len(section.errors) == 2


def test_parse_error_service_ok_once_errors_are_gone(check):
    section = check.parse_oposs_bgp_mon_sessions(STRING_TABLE)
    out = list(check.check_oposs_bgp_mon_sessions("_parse_errors", {}, section))
    assert out == [Result(state=State.OK, summary="No parsing errors")]


@pytest.mark.parametrize("line", ["null", "[1, 2]", '"text"', "42"])
@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="BUG: a row that is valid JSON but not an object raises TypeError, which parse does not catch")
def test_json_that_is_not_an_object_is_a_parse_error(check, line):
    section = check.parse_oposs_bgp_mon_sessions([_row(**CISCO_UP), [line]])
    assert section.inventory == ["AS65001 10.0.0.2"]
    assert len(section.errors) == 1


@pytest.mark.xfail(strict=True,
                   reason="BUG: sessions with the same AS and neighbour in two VRFs share one item; the last row hides the other")
def test_same_peer_in_two_vrfs_is_checked_twice(check):
    blue = dict(CISCO_UP, **{"vrf-name-out": "blue"})
    red = dict(CISCO_UP, **{"vrf-name-out": "red"}, state="Idle")
    section = check.parse_oposs_bgp_mon_sessions([_row(**red), _row(**blue)])
    items = [s.item for s in check.discover_sessions(section)]
    assert len(set(items)) == 2


# --- version -----------------------------------------------------------------


def test_release_writes_version_into_check(tmp_path):
    """Apply the version_files entry of .github/repo-infra.json to the check
    module, as Create release PR does (a multiline regex, first match)"""
    config = json.loads((ROOT / ".github/repo-infra.json").read_text())
    (spec,) = [f for f in config["version_files"] if (ROOT / f["path"]) == CHECK]
    stamped = re.sub(spec["pattern"], spec["replacement"].replace("$VERSION", "9.8.7"),
                     CHECK.read_text(), count=1, flags=re.MULTILINE)
    assert re.search(spec["verify"].replace("$VERSION", re.escape("9.8.7")), stamped, flags=re.MULTILINE)
    copy = tmp_path / "stamped_check.py"
    copy.write_text(stamped)
    assert _load_check(copy, "stamped_check").__version__ == "9.8.7"
