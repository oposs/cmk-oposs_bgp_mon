"""Tests for the special agent agent_oposs_bgp_mon (runs on the Checkmk server).

Each driver turns a device answer into session dicts. The device answers
below follow what the devices send: NX-API JSON-RPC for Cisco Nexus, the
PAN-OS XML API for Palo Alto, and `display bgp ... peer verbose` text read
over SSH for Huawei. No network or SSH is used; requests is patched.
"""

import base64
import getopt
import importlib.util
import json
import logging
import os
import pathlib
import re
import sys
import types
from importlib.machinery import SourceFileLoader

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_bgp_mon"
AGENT = PLUGIN / "libexec/agent_oposs_bgp_mon"
CHECK = PLUGIN / "agent_based/oposs_bgp_mon_sessions.py"

# mktime normalises the subtracted fields, so a DST change inside the span
# moves the result by an hour
DST = 3600


def _no_lookup(pw_file, pw_id):
    raise AssertionError("tests that use --password-ref patch the lookup")


def _load_agent(extra_modules=None, path=AGENT):
    """Load the agent with the one monolith module it needs stubbed.

    cmk.utils.password_store exists only inside a Checkmk site. The stub is
    put in sys.modules for the import only.
    """
    password_store = types.ModuleType("cmk.utils.password_store")
    password_store.lookup = _no_lookup
    stubs = {"cmk.utils.password_store": password_store, **(extra_modules or {})}
    if "cmk.utils" not in sys.modules:
        utils = types.ModuleType("cmk.utils")
        utils.password_store = password_store
        stubs["cmk.utils"] = utils
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        loader = SourceFileLoader("agent_oposs_bgp_mon", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


@pytest.fixture(scope="module")
def agent():
    return _load_agent()


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def json(self):
        return json.loads(self.text)


def _args(agent, driver, host="router1", insecure=False):
    argv = ["-u", "monitor", "-p", "secret", "-r", driver, host]
    return agent.parse_arguments(argv + (["--insecure"] if insecure else []))


# --- Cisco Nexus NX-API ------------------------------------------------------


def _nxapi_neighbor(ip, asn, state, time):
    return {
        "neighborid": ip, "neighborversion": "4", "msgrecvd": "1203", "msgsent": "1198",
        "neighbortableversion": "42", "inq": "0", "outq": "0", "neighboras": asn,
        "time": time, "state": state, "prefixreceived": "12",
    }


def _nxapi_saf(af_name, neighbors):
    return {
        "safi": "1", "af-name": af_name, "tableversion": "42", "configuredpeers": "2",
        "capablepeers": "1", "totalnetworks": "12", "totalpaths": "12",
        "memoryused": "1752", "numberattrs": "1", "bytesattrs": "160",
        "numberpaths": "1", "bytespaths": "36", "numbercommunities": "0",
        "bytescommunities": "0", "numberclusterlist": "0", "bytesclusterlist": "0",
        "dampening": "false", "TABLE_neighbor": {"ROW_neighbor": neighbors},
    }


def _nxapi(vrfs):
    return {"jsonrpc": "2.0", "result": {"body": {"TABLE_vrf": {"ROW_vrf": vrfs}}}, "id": 1}


def _nxapi_vrf(name, afs):
    return {"vrf-name-out": name, "vrf-router-id": "10.0.0.1", "vrf-local-as": "65000",
            "TABLE_af": {"ROW_af": afs}}


NXAPI = _nxapi([
    _nxapi_vrf("default", [
        {"af-id": "1", "TABLE_saf": {"ROW_saf": _nxapi_saf("IPv4 Unicast", [
            _nxapi_neighbor("10.0.0.2", "65001", "Established", "P1DT2H3M4S"),
            _nxapi_neighbor("10.0.0.3", "65002", "Idle", "PT0S"),
        ])}},
        {"af-id": "2", "TABLE_saf": {"ROW_saf": _nxapi_saf(
            "IPv6 Unicast", _nxapi_neighbor("2001:db8::2", "65004", "Active", "PT5M"))}},
    ]),
    # A VRF without BGP address families is skipped
    {"vrf-name-out": "management", "vrf-router-id": "0.0.0.0", "vrf-local-as": "65000"},
])


def test_cisco_parses_nxapi_answer(agent, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(json.dumps(NXAPI))

    monkeypatch.setattr(agent.requests, "post", post)
    fetcher = agent.ciscoFetcher("router1", "monitor", "secret", "cisco_https")
    sessions = fetcher.fetch()

    ((url, kwargs),) = calls
    assert url == "https://router1/ins"
    assert kwargs["auth"] == ("monitor", "secret")
    assert kwargs["verify"] is True
    assert json.loads(kwargs["data"])["params"]["cmd"] == "show bgp vrf all all summary"

    assert [(s["vrf-name-out"], s["af-name"], s["neighbourid"], s["neighbouras"], s["state"])
            for s in sessions] == [
        ("default", "IPv4 Unicast", "10.0.0.2", "65001", "Established"),
        ("default", "IPv4 Unicast", "10.0.0.3", "65002", "Idle"),
        ("default", "IPv6 Unicast", "2001:db8::2", "65004", "Active"),
    ]
    assert abs(sessions[0]["uptime"] - (86400 + 2 * 3600 + 3 * 60 + 4)) <= DST
    assert sessions[1]["uptime"] == 0
    assert abs(sessions[2]["uptime"] - 300) <= DST


def test_cisco_http_uses_plain_http(agent, monkeypatch):
    urls = []
    monkeypatch.setattr(agent.requests, "post",
                        lambda url, **kw: urls.append(url) or _Response(json.dumps(NXAPI)))
    agent.ciscoFetcher("router1", "u", "p", "cisco_http").fetch()
    assert urls == ["http://router1/ins"]


def test_cisco_insecure_turns_off_verification(agent, monkeypatch):
    seen = {}
    monkeypatch.setattr(agent.requests, "post",
                        lambda url, **kw: seen.update(kw) or _Response(json.dumps(NXAPI)))
    agent.ciscoFetcher("router1", "u", "p", "cisco_https", verify_ssl=False).fetch()
    assert seen["verify"] is False


def test_cisco_request_has_a_timeout(agent, monkeypatch):
    seen = {}
    monkeypatch.setattr(agent.requests, "post",
                        lambda url, **kw: seen.update(kw) or _Response(json.dumps(NXAPI)))
    agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()
    assert seen["timeout"] == 30


def test_cisco_sends_json_rpc_content_type(agent, monkeypatch):
    seen = {}
    monkeypatch.setattr(agent.requests, "post",
                        lambda url, **kw: seen.update(kw) or _Response(json.dumps(NXAPI)))
    agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()
    assert seen["headers"] == {"content-type": "application/json-rpc"}


def test_cisco_http_error_raises(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response("denied", 401))
    with pytest.raises(RuntimeError, match="Failed to fetch data"):
        agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()


def test_cisco_garbage_raises_value_error(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response("<html>oops</html>"))
    with pytest.raises(ValueError, match="invalid data"):
        agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()


# NX-API returns a table with a single row as an object, not a one-element
# list, at every level.
SINGLE = _nxapi(_nxapi_vrf("default", {"af-id": "1", "TABLE_saf": {"ROW_saf": _nxapi_saf(
    "IPv4 Unicast", _nxapi_neighbor("10.0.0.2", "65001", "Established", "PT1H"))}}))


def test_cisco_single_vrf_and_af(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response(json.dumps(SINGLE)))
    sessions = agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()
    assert [s["neighbourid"] for s in sessions] == ["10.0.0.2"]


# A peer that was never up has "never" as its session time
NEVER_UP = _nxapi(_nxapi_vrf("default", {"af-id": "1", "TABLE_saf": {"ROW_saf": _nxapi_saf(
    "IPv4 Unicast", [
        _nxapi_neighbor("10.0.0.2", "65001", "Established", "PT1H"),
        _nxapi_neighbor("10.0.0.5", "65005", "Idle", "never"),
    ])}}))


def test_cisco_peer_never_up(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response(json.dumps(NEVER_UP)))
    sessions = agent.ciscoFetcher("router1", "u", "p", "cisco_https").fetch()
    assert [(s["neighbourid"], s["state"]) for s in sessions] == [
        ("10.0.0.2", "Established"), ("10.0.0.5", "Idle")]
    assert abs(sessions[0]["uptime"] - 3600) <= DST
    assert sessions[1]["uptime"] is None


# --- Palo Alto XML API -------------------------------------------------------

PAN_KEYGEN = '<response status="success"><result><key>LUFRPT1abc==</key></result></response>'

PAN_PEERS = """<response status="success"><result>
  <entry peer="isp1" vr="default">
    <peer-group>ISP</peer-group>
    <peer-router-id>198.51.100.1</peer-router-id>
    <remote-as>65010</remote-as>
    <status>Established</status>
    <status-duration>86400</status-duration>
    <password-set>no</password-set>
    <passive>no</passive>
    <multi-hop-ttl>1</multi-hop-ttl>
    <peer-address>198.51.100.1:179</peer-address>
    <local-address>198.51.100.2:35243</local-address>
    <prefix-counter>
      <entry afi-safi="bgpAfiIpv4-unicast">
        <incoming-total>10</incoming-total>
        <incoming-accepted>10</incoming-accepted>
        <outgoing-total>2</outgoing-total>
      </entry>
    </prefix-counter>
  </entry>
  <entry peer="isp2" vr="default">
    <peer-group>ISP</peer-group>
    <peer-router-id>0.0.0.0</peer-router-id>
    <remote-as>65011</remote-as>
    <status>Active</status>
    <status-duration>120</status-duration>
    <peer-address>203.0.113.1</peer-address>
    <local-address>203.0.113.2</local-address>
  </entry>
</result></response>"""


@pytest.fixture
def paloalto(agent, monkeypatch):
    calls = []

    def get(url, params, **kwargs):
        calls.append((url, params, kwargs))
        return _Response(PAN_KEYGEN if params["type"] == "keygen" else PAN_PEERS)

    monkeypatch.setattr(agent.requests, "get", get)
    return calls


def test_paloalto_keygen_then_op(agent, paloalto):
    agent.paloaltoFetcher(_args(agent, "paloalto", "fw1")).fetch()
    (url1, keygen, kw1), (url2, op, kw2) = paloalto
    assert url1 == url2 == "https://fw1/api/"
    assert keygen == {"type": "keygen", "user": "monitor", "password": "secret"}
    assert op["type"] == "op" and op["key"] == "LUFRPT1abc=="
    assert "<bgp><peer></peer></bgp>" in op["cmd"]
    assert kw1["verify"] is kw2["verify"] is True


def test_paloalto_insecure(agent, paloalto):
    agent.paloaltoFetcher(_args(agent, "paloalto", "fw1", insecure=True)).fetch()
    assert all(kw["verify"] is False for _, _, kw in paloalto)


def test_paloalto_parses_peers(agent, paloalto):
    sessions = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert sessions == [
        {"vrf-name-out": "default", "af-name": "bgpAfiIpv4-unicast",
         "neighbourid": "198.51.100.1", "neighbouras": "65010",
         "state": "Established", "uptime": 86400},
        # A peer that is not up has no <prefix-counter>, so no address family
        {"vrf-name-out": "default", "af-name": None,
         "neighbourid": "203.0.113.1", "neighbouras": "65011",
         "state": "Active", "uptime": 120},
    ]


def test_paloalto_empty_prefix_counter(agent, monkeypatch):
    peers = PAN_PEERS.replace("<local-address>203.0.113.2</local-address>",
                              "<local-address>203.0.113.2</local-address><prefix-counter/>")
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        PAN_KEYGEN if params["type"] == "keygen" else peers))
    sessions = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert [(s["neighbourid"], s["af-name"]) for s in sessions] == [
        ("198.51.100.1", "bgpAfiIpv4-unicast"), ("203.0.113.1", None)]


def _pan_peer(name, body):
    return f'<entry peer="{name}" vr="default"><peer-group>ISP</peer-group>{body}</entry>'


# Peers that are not up, with elements missing or empty
PAN_SPARSE = PAN_PEERS.replace("</result>", "".join([
    _pan_peer("noduration", "<remote-as>65012</remote-as><status>Idle</status>"
              "<peer-address>203.0.113.5</peer-address>"),
    _pan_peer("emptyduration", "<remote-as>65013</remote-as><status>Connect</status>"
              "<status-duration/><peer-address>203.0.113.6</peer-address>"),
    _pan_peer("nostatus", "<remote-as>65014</remote-as><status-duration>5</status-duration>"
              "<peer-address>203.0.113.7</peer-address>"),
    # Without the remote AS or the peer address there is no service name
    _pan_peer("noas", "<status>Idle</status><peer-address>203.0.113.8</peer-address>"),
    _pan_peer("noaddress", "<remote-as>65016</remote-as><status>Idle</status>"
              "<peer-address></peer-address>"),
]) + "</result>")


def test_paloalto_peers_with_missing_elements(agent, check, monkeypatch):
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        PAN_KEYGEN if params["type"] == "keygen" else PAN_SPARSE))
    sessions = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert [(s["neighbourid"], s.get("state"), s["uptime"]) for s in sessions] == [
        ("198.51.100.1", "Established", 86400),
        ("203.0.113.1", "Active", 120),
        ("203.0.113.5", "Idle", None),
        ("203.0.113.6", "Connect", None),
        ("203.0.113.7", None, 5),
    ]
    # Every session reaches the check without a parse error
    rows = [[json.dumps(s, sort_keys=True, separators=(",", ":"))] for s in sessions]
    section = check.parse_oposs_bgp_mon_sessions(rows)
    assert section.errors == []
    out = list(check.check_oposs_bgp_mon_sessions("AS65014 203.0.113.7", {}, section))
    assert out[-1] == check.Result(state=check.State.WARN, summary="state: n/a")


def test_paloalto_reports_remote_as_and_peer_address(agent, paloalto):
    session = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()[0]
    assert session["neighbouras"] == "65010"
    assert session["neighbourid"] == "198.51.100.1"


@pytest.mark.parametrize("address, expected", [
    ("198.51.100.1:179", "198.51.100.1"),
    ("198.51.100.1", "198.51.100.1"),
    ("[2001:db8::1]:179", "2001:db8::1"),
    ("2001:db8::1", "2001:db8::1"),
])
def test_paloalto_peer_address_without_port(agent, monkeypatch, address, expected):
    peers = PAN_PEERS.replace("<peer-address>198.51.100.1:179</peer-address>",
                              f"<peer-address>{address}</peer-address>")
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        PAN_KEYGEN if params["type"] == "keygen" else peers))
    session = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()[0]
    assert session["neighbourid"] == expected


def test_paloalto_requests_have_a_timeout(agent, paloalto):
    agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert [kw["timeout"] for _, _, kw in paloalto] == [30, 30]


def test_paloalto_debug_log_has_no_key(agent, paloalto, caplog):
    caplog.set_level("DEBUG")
    agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert "LUFRPT1abc==" not in "\n".join(caplog.messages)
    assert "Received an auth key" in caplog.messages


def test_debug_mode_keeps_urllib3_quiet(agent, monkeypatch):
    """urllib3 logs each request line with its query string at debug
    level, which holds the password of the keygen and the key"""
    monkeypatch.setattr(logging.getLogger("urllib3"), "level", logging.NOTSET)
    agent.parse_arguments(["-d", "-u", "u", "-p", "p", "-r", "paloalto", "fw1"])
    # basicConfig does nothing under pytest, so check the logger's own level
    assert logging.getLogger("urllib3").level > logging.DEBUG


def test_paloalto_failed_keygen(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        '<response status="error"><result><msg>Invalid credentials.</msg></result></response>'))
    with pytest.raises(ValueError, match="no auth key"):
        agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()


def test_paloalto_keygen_without_key_logs_the_answer(agent, monkeypatch, caplog):
    answer = '<response status="success"><result/></response>'
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(answer))
    with pytest.raises(ValueError, match="no auth key"):
        agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert f"Failed to extract key from: {answer}" in caplog.messages


def test_paloalto_error_answer(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        PAN_KEYGEN if params["type"] == "keygen" else '<response status="error"/>'))
    with pytest.raises(ValueError, match="invalid data"):
        agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()


# --- Huawei SSH text -----------------------------------------------------------

HUAWEI = """display bgp vpnv4 all peer verbose

         BGP Peer is 10.1.1.2,  remote AS 65020
         Type: EBGP link
         BGP version 4, Remote router ID 10.1.1.2
         Update-group ID: 1
         BGP current state: Established, Up for 01h02m03s
         BGP current event: KATimerExpired
         BGP last state: OpenConfirm

 Peer of IPv4-family for VPN instance: vpn1

         BGP Peer is 10.2.2.2,  remote AS 65021
         Type: EBGP link
         BGP version 4, Remote router ID 0.0.0.0
         Update-group ID: 2
         BGP current state: Idle
         BGP current event: Start

         BGP Peer is 10.2.2.3,  remote AS 65022
         Type: EBGP link
         BGP version 4, Remote router ID 10.2.2.3
         Update-group ID: 2
         BGP current state: Established, Up for 3d04h05m06s
"""


def _huawei_postprocess(agent, text):
    fetcher = agent.huaweiFetcher(_args(agent, "huawei"))
    return fetcher._huaweiFetcher__postprocess(text)


def test_huawei_parses_peer_verbose(agent):
    sessions = _huawei_postprocess(agent, HUAWEI)
    assert [(s["vrf-name-out"], s["af-name"], s["neighbourid"], s["neighbouras"], s["state"])
            for s in sessions] == [
        ("????", "ipv4", "10.1.1.2", "65020", "Established"),
        ("vpn1", "ipv4", "10.2.2.2", "65021", "Idle"),
        ("vpn1", "ipv4", "10.2.2.3", "65022", "Established"),
    ]
    assert abs(sessions[0]["uptime"] - 3723) <= DST
    assert sessions[1]["uptime"] is None
    assert abs(sessions[2]["uptime"] - (3 * 86400 + 4 * 3600 + 5 * 60 + 6)) <= DST


def test_huawei_ipv6_peer(agent):
    text = HUAWEI.replace("10.1.1.2,", "2001:DB8::2,")
    assert _huawei_postprocess(agent, text)[0]["af-name"] == "ipv6"


def test_huawei_no_peers(agent):
    assert _huawei_postprocess(agent, "Info: No peer.\n") == []


def test_huawei_non_ascii_output(agent):
    text = HUAWEI.replace("Type: EBGP link", "Peer's description: \"Zürich POP\"\n         Type: EBGP link")
    assert len(_huawei_postprocess(agent, text)) == 3


# "BGP current event" follows the state line, outside every peer block
NOT_BGP = "KATimerExpired"


def test_huawei_debug_log_has_no_full_dump(agent, caplog):
    caplog.set_level("DEBUG")
    assert len(_huawei_postprocess(agent, HUAWEI)) == 3
    logged = "\n".join(caplog.messages)
    assert NOT_BGP not in logged
    assert base64.encodebytes(HUAWEI.encode()).decode().splitlines()[0] not in logged
    # The peer blocks are what debugging needs
    assert "BGP Peer is 10.2.2.3,  remote AS 65022" in logged


def test_huawei_parse_failure_logs_no_full_dump(agent, monkeypatch, caplog):
    caplog.set_level("DEBUG")

    class Child:
        before = ""

        def expect(self, patterns, timeout):
            if patterns == ["---- More ----", "<.+?>"]:
                self.before = HUAWEI
                return 1
            return 1 if isinstance(patterns, list) and len(patterns) == 2 else 0

        def sendline(self, line):
            pass

    pexpect = types.ModuleType("pexpect")
    pexpect.spawn = lambda cmd, args=None, **kw: Child()
    monkeypatch.setitem(sys.modules, "pexpect", pexpect)

    def broken(self, data):
        raise IndexError("no such group")

    monkeypatch.setattr(agent.huaweiFetcher, "_huaweiFetcher__postprocess", broken)
    with pytest.raises(ValueError, match="invalid data"):
        agent.huaweiFetcher(_args(agent, "huawei")).fetch()
    assert NOT_BGP not in "\n".join(caplog.messages)


def test_huawei_ssh_failure_message_has_no_session_buffer(agent, monkeypatch, caplog, capsys):
    caplog.set_level("DEBUG")
    buffer = "<switch1>display current-configuration"

    class TIMEOUT(Exception):
        pass

    class Child:
        def __str__(self):
            return f"<pexpect.pty_spawn.spawn object>\nbuffer (last 100 chars): {buffer!r}"

        def expect(self, *args, **kwargs):
            # pexpect puts str(child) into the text of its exceptions
            raise TIMEOUT(f"Timeout exceeded.\n{self}")

    pexpect = types.ModuleType("pexpect")
    pexpect.spawn = lambda cmd, args=None, **kw: Child()
    monkeypatch.setitem(sys.modules, "pexpect", pexpect)
    with pytest.raises(RuntimeError) as error:
        agent.huaweiFetcher(_args(agent, "huawei")).fetch()
    assert str(error.value) == "Failed to fetch data from router1: TIMEOUT"
    assert "current-configuration" not in "\n".join(caplog.messages)
    # main prints the traceback into the section; a chained exception would
    # bring the pexpect text back
    code, lines = _run_main(agent, ["-u", "monitor", "-p", "secret", "-r", "huawei", "router1"],
                            capsys)
    assert code == 1
    assert lines[-1] == "Error: Failed to fetch data from router1: TIMEOUT"
    assert "current-configuration" not in "\n".join(lines)


def test_cisco_runs_without_pexpect(monkeypatch, capsys):
    agent = _load_agent({"pexpect": None})
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response(json.dumps(NXAPI)))
    code, lines = _run_main(agent, ["-u", "u", "-p", "p", "-r", "cisco_https", "router1"], capsys)
    assert code == 0
    assert len(lines) == 4


def test_huawei_without_pexpect_says_what_to_install(monkeypatch):
    agent = _load_agent()
    monkeypatch.setitem(sys.modules, "pexpect", None)
    with pytest.raises(ImportError, match="pip3 install pexpect"):
        agent.huaweiFetcher(_args(agent, "huawei")).fetch()


# --- a device named "test" -----------------------------------------------------


@pytest.fixture
def no_local_files(agent, monkeypatch):
    """Pretend every test data file exists, and fail if the agent opens one"""
    monkeypatch.setattr(os, "access", lambda path, mode: True)

    def no_open(*args, **kwargs):
        raise AssertionError(f"agent opened a local file: {args[0]}")

    monkeypatch.setattr(agent, "open", no_open, raising=False)


def test_cisco_host_named_test_asks_the_device(agent, monkeypatch, no_local_files):
    urls = []
    monkeypatch.setattr(agent.requests, "post",
                        lambda url, **kw: urls.append(url) or _Response(json.dumps(NXAPI)))
    assert len(agent.ciscoFetcher("test", "u", "p", "cisco_https").fetch()) == 3
    assert urls == ["https://test/ins"]


def test_paloalto_host_named_test_asks_the_device(agent, paloalto, no_local_files):
    assert len(agent.paloaltoFetcher(_args(agent, "paloalto", "test")).fetch()) == 2
    assert [url for url, _, _ in paloalto] == ["https://test/api/"] * 2


def test_huawei_host_named_test_asks_the_device(agent, monkeypatch, no_local_files):
    spawned = []

    class Child:
        def expect(self, *args, **kwargs):
            raise OSError("connection refused")

    pexpect = types.ModuleType("pexpect")
    pexpect.spawn = lambda cmd, args=None, **kw: spawned.append([cmd, *args]) or Child()
    monkeypatch.setitem(sys.modules, "pexpect", pexpect)
    with pytest.raises(RuntimeError, match="Failed to fetch data"):
        agent.huaweiFetcher(_args(agent, "huawei", "test")).fetch()
    assert spawned == [["ssh", "-l", "monitor", "--", "test"]]


# The option string of OpenSSH (ssh.c): an argument after -l or after "--"
# can never become an option
SSH_OPTSTRING = "1246ab:c:e:fgi:kl:m:no:p:qstvxAB:CD:E:F:GI:J:KL:MNO:P:Q:R:S:TVw:W:XYy"


@pytest.mark.parametrize("username, host", [
    ("monitor", "router1"),
    ("net admin", "router1"),
    ("-oProxyCommand=touch /pwned", "router1"),
    ("monitor", "-oProxyCommand=touch /pwned"),
    ("monitor", "router1 -oProxyCommand=touch"),
])
def test_huawei_ssh_gets_username_and_host_as_one_argument_each(agent, monkeypatch,
                                                                username, host):
    spawned = []

    class Child:
        def expect(self, *args, **kwargs):
            raise OSError("connection refused")

    pexpect = types.ModuleType("pexpect")
    # pexpect.spawn splits a command string on spaces, unless args is given
    pexpect.spawn = lambda cmd, args=None, **kw: spawned.append((cmd, args)) or Child()
    monkeypatch.setitem(sys.modules, "pexpect", pexpect)
    args = _args(agent, "huawei")
    args.username, args.hostaddress = username, host
    with pytest.raises(RuntimeError, match="Failed to fetch data"):
        agent.huaweiFetcher(args).fetch()
    [(cmd, argv)] = spawned
    assert cmd == "ssh"
    options, destination = getopt.getopt(argv, SSH_OPTSTRING)
    assert options == [("-l", username)]
    assert destination == [host]


# --- main: what Checkmk reads ---------------------------------------------------


def _run_main(agent, argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        agent.main(argv)
    return exit_info.value.code, capsys.readouterr().out.splitlines()


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("test_bgp_agent_check", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_output_feeds_the_check(agent, check, monkeypatch, capsys):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response(json.dumps(NXAPI)))
    code, lines = _run_main(agent, ["-u", "u", "-p", "p", "-r", "cisco_https", "router1"], capsys)
    assert code == 0
    assert lines[0] == "<<<oposs_bgp_mon_sessions:sep(0)>>>"
    # One compact, key-sorted JSON object per line
    for line in lines[1:]:
        assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"))
    section = check.parse_oposs_bgp_mon_sessions([[line] for line in lines[1:]])
    assert section.inventory == ["AS65001 10.0.0.2", "AS65002 10.0.0.3", "AS65004 2001:db8::2"]
    assert section.errors == []


def test_main_failure_reaches_the_check_as_parse_errors(agent, check, monkeypatch, capsys):
    monkeypatch.setattr(agent.requests, "post", lambda url, **kw: _Response("denied", 403))
    code, lines = _run_main(agent, ["-u", "u", "-p", "p", "-r", "cisco_https", "router1"], capsys)
    assert code == 1
    assert lines[0] == "<<<oposs_bgp_mon_sessions:sep(0)>>>"
    assert lines[-1] == "Error: Failed to fetch data"
    section = check.parse_oposs_bgp_mon_sessions([[line] for line in lines[1:]])
    assert section.inventory == []
    assert len(section.errors) == len(lines) - 1


def test_main_unknown_driver(agent, capsys):
    code, lines = _run_main(agent, ["-u", "u", "-p", "p", "-r", "juniper", "router1"], capsys)
    assert code == 1
    assert lines[-1] == "Error: Unknown driver"


# --- version -----------------------------------------------------------------


def test_release_writes_version_into_agent(tmp_path):
    """Apply the version_files entry of .github/repo-infra.json to the agent,
    as Create release PR does (a multiline regex, first match)"""
    config = json.loads((ROOT / ".github/repo-infra.json").read_text())
    (spec,) = [f for f in config["version_files"] if (ROOT / f["path"]) == AGENT]
    stamped = re.sub(spec["pattern"], spec["replacement"].replace("$VERSION", "9.8.7"),
                     AGENT.read_text(), count=1, flags=re.MULTILINE)
    assert re.search(spec["verify"].replace("$VERSION", re.escape("9.8.7")), stamped, flags=re.MULTILINE)
    copy = tmp_path / "agent_oposs_bgp_mon"
    copy.write_text(stamped)
    assert _load_agent(path=copy).__version__ == "9.8.7"


# --- password store ------------------------------------------------------------

# What Checkmk 2.4 puts in place of a Secret passed safely:
# f"{secret_name}:{password_store_file}" (cmk/server_side_calls_backend/_commons.py)
STORE = "/omd/sites/mon/var/check_mk/core/helper_config/42/stored_passwords"


@pytest.fixture
def store(agent, monkeypatch):
    """A password store with one entry per id, as lookup() reads it"""
    passwords = {"bgp_switches": "s3cret:with:colons", "uuid0d8e": "explicit"}
    calls = []

    def lookup(pw_file, pw_id):
        calls.append((pw_file, pw_id))
        try:
            return passwords[pw_id]
        except KeyError:
            raise ValueError(f"Password '{pw_id}' not found in {pw_file}") from None

    monkeypatch.setattr(agent.password_store, "lookup", lookup)
    return calls


@pytest.mark.parametrize("pw_id, password", [
    ("bgp_switches", "s3cret:with:colons"),  # from the password store
    ("uuid0d8e", "explicit"),  # typed into the rule
])
def test_password_ref_reads_the_store(agent, store, pw_id, password):
    args = agent.parse_arguments(["-u", "monitor", "--password-ref", f"{pw_id}:{STORE}",
                                  "-r", "paloalto", "fw1"])
    assert args.password is None
    assert agent.resolve_password(args) == password
    assert store == [(pathlib.Path(STORE), pw_id)]


def test_password_ref_with_colon_in_the_id(agent, store):
    args = agent.parse_arguments(["-u", "m", "--password-ref", f":uuid:0d8e:{STORE}",
                                  "-r", "huawei", "sw1"])
    with pytest.raises(ValueError):
        agent.resolve_password(args)
    assert store == [(pathlib.Path(STORE), ":uuid:0d8e")]


def test_plain_password_still_works(agent, store):
    """A core config generated before the update still passes -p"""
    assert agent.resolve_password(_args(agent, "cisco_https")) == "secret"
    assert store == []


@pytest.mark.parametrize("argv", [
    ["-u", "m", "-r", "huawei", "sw1"],
    ["-u", "m", "-p", "p", "--password-ref", f"x:{STORE}", "-r", "huawei", "sw1"],
])
def test_exactly_one_password_option(agent, argv, capsys):
    with pytest.raises(SystemExit):
        agent.parse_arguments(argv)


def test_main_resolves_password_ref(agent, store, monkeypatch, capsys):
    sent = []

    def post(url, **kw):
        sent.append(kw["auth"])
        return _Response(json.dumps(NXAPI))

    monkeypatch.setattr(agent.requests, "post", post)
    code, lines = _run_main(agent, ["-u", "monitor", "--password-ref", f"bgp_switches:{STORE}",
                                    "-r", "cisco_https", "router1"], capsys)
    assert code == 0
    assert len(lines) == 4
    assert sent == [("monitor", "s3cret:with:colons")]


def test_main_missing_password_reaches_the_check(agent, check, store, capsys):
    code, lines = _run_main(agent, ["-u", "m", "--password-ref", f"gone:{STORE}",
                                    "-r", "cisco_https", "router1"], capsys)
    assert code == 1
    assert lines[0] == "<<<oposs_bgp_mon_sessions:sep(0)>>>"
    assert lines[-1] == f"Error: Password 'gone' not found in {STORE}"
    assert check.parse_oposs_bgp_mon_sessions([[line] for line in lines[1:]]).inventory == []


def test_main_malformed_password_ref(agent, store, capsys):
    code, lines = _run_main(agent, ["-u", "m", "--password-ref", "nofile",
                                    "-r", "cisco_https", "router1"], capsys)
    assert code == 1
    assert lines[-1] == "Error: --password-ref needs PW_ID:PW_FILE"
    assert store == []
