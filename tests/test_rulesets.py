"""The rule forms build and match what the check and the agent call read."""

import importlib.util
import pathlib
import re
import sys

import pytest
from cmk.rulesets.v1.form_specs import LevelDirection, SimpleLevels, SingleChoice
from cmk.rulesets.v1.rule_specs import (
    CheckParameters,
    HostAndItemCondition,
    SpecialAgent,
)
from cmk.server_side_calls.v1 import HostConfig, IPv4Config, Secret, SpecialAgentCommand

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_bgp_mon"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rulesets():
    return _load(PLUGIN / "rulesets/oposs_bgp_mon.py", "test_oposs_bgp_mon_rulesets")


@pytest.fixture(scope="module")
def ssc():
    return _load(PLUGIN / "server_side_calls/oposs_bgp_mon.py", "test_oposs_bgp_mon_ssc")


@pytest.fixture(scope="module")
def check():
    return _load(PLUGIN / "agent_based/oposs_bgp_mon_sessions.py", "test_oposs_bgp_mon_check_rs")


# --- special agent rule --------------------------------------------------------


def test_special_agent_form_builds(rulesets):
    rule = rulesets.rule_spec_special_agent_oposs_bgp_mon
    assert isinstance(rule, SpecialAgent)
    form = rule.parameter_form()
    assert set(form.elements) == {"username", "password", "driver", "verify_ssl"}
    assert all(e.required for e in form.elements.values())


def test_rule_and_agent_call_share_a_name(rulesets, ssc):
    assert rulesets.rule_spec_special_agent_oposs_bgp_mon.name == ssc.special_agent_oposs_bgp_mon.name


def test_form_fields_are_the_agent_call_parameters(rulesets, ssc):
    form = rulesets.rule_spec_special_agent_oposs_bgp_mon.parameter_form()
    assert set(form.elements) == set(ssc.Params.model_fields)


def test_every_driver_choice_is_one_the_agent_knows(rulesets):
    driver = rulesets.rule_spec_special_agent_oposs_bgp_mon.parameter_form().elements["driver"].parameter_form
    assert isinstance(driver, SingleChoice)
    choices = {e.name for e in driver.elements}
    agent = (PLUGIN / "libexec/agent_oposs_bgp_mon").read_text()
    known = set(re.findall(r'args\.driver == "([a-z_]+)"', agent))
    assert choices == known == {"cisco_http", "cisco_https", "huawei", "paloalto"}
    assert driver.prefill.value == "cisco_https"


# --- check parameter rule ------------------------------------------------------


def test_check_parameter_form_builds(rulesets):
    rule = rulesets.rule_spec_check_parameters_oposs_bgp_mon_sessions
    assert isinstance(rule, CheckParameters)
    # The check yields Service(item=...), so the rule needs an item condition
    assert isinstance(rule.condition, HostAndItemCondition)
    levels = rule.parameter_form().elements["min_uptime"].parameter_form
    assert isinstance(levels, SimpleLevels)
    assert levels.level_direction is LevelDirection.LOWER


def test_check_uses_this_ruleset(rulesets, check):
    plugin = check.check_plugin_oposs_bgp_mon_sessions
    rule = rulesets.rule_spec_check_parameters_oposs_bgp_mon_sessions
    assert plugin.check_ruleset_name == rule.name
    form = rule.parameter_form()
    assert set(plugin.check_default_parameters) <= set(form.elements)


# --- agent call ----------------------------------------------------------------

HOST = HostConfig(name="router1.example.net", ipv4_config=IPv4Config(address="192.0.2.10"))
PASSWORD = Secret(7)


def _command(ssc, **params):
    params = {"username": "monitor", "password": PASSWORD, "driver": "cisco_https", **params}
    (command,) = ssc.special_agent_oposs_bgp_mon(params, HOST)
    assert isinstance(command, SpecialAgentCommand)
    return command.command_arguments


def test_command_with_verification(ssc):
    assert _command(ssc, verify_ssl=True) == [
        "-u", "monitor", "-p", PASSWORD.unsafe(), "-r", "cisco_https", "router1.example.net",
    ]


def test_command_without_verification(ssc):
    assert "--insecure" in _command(ssc, driver="paloalto", verify_ssl=False)


def test_old_rule_without_verify_ssl_stays_insecure(ssc):
    # Rules saved before 1.0.5 have no verify_ssl; they keep the old behaviour
    assert "--insecure" in _command(ssc)


def test_command_uses_host_name_not_address(ssc):
    # The certificate names the host, not its address
    args = _command(ssc, verify_ssl=True)
    assert args[-1] == "router1.example.net"
    assert "192.0.2.10" not in args
