"""Tests for the special agent agent_oposs_bgp_mon (runs on the Checkmk server).

Each driver turns a device answer into session dicts. The device answers
below follow what the devices send: NX-API JSON-RPC for Cisco Nexus, the
PAN-OS XML API for Palo Alto, and `display bgp ... peer verbose` text read
over SSH for Huawei. No network or SSH is used; requests is patched.
"""

import importlib.util
import json
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


def _load_agent(extra_modules=None, path=AGENT):
    """Load the agent with the one monolith module it needs stubbed.

    cmk.utils.password_store exists only inside a Checkmk site. The stub is
    put in sys.modules for the import only.
    """
    password_store = types.ModuleType("cmk.utils.password_store")
    password_store.replace_passwords = lambda: None
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


def test_paloalto_skips_peer_without_prefix_counter(agent, paloalto):
    sessions = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert len(sessions) == 1
    session = sessions[0]
    assert session["vrf-name-out"] == "default"
    assert session["af-name"] == "bgpAfiIpv4-unicast"
    assert session["state"] == "Established"
    assert session["uptime"] == 86400


def test_paloalto_reports_remote_as_and_peer_address(agent, paloalto):
    (session,) = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
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
    (session,) = agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()
    assert session["neighbourid"] == expected


def test_paloalto_failed_keygen(agent, monkeypatch):
    monkeypatch.setattr(agent.requests, "get", lambda url, params, **kw: _Response(
        '<response status="error"><result><msg>Invalid credentials.</msg></result></response>'))
    with pytest.raises(ValueError, match="no auth key"):
        agent.paloaltoFetcher(_args(agent, "paloalto")).fetch()


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
