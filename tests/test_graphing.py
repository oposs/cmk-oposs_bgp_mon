"""Metric names: prefixed, and the pre-1.0 name translated to the current one."""

import importlib.util
import pathlib
import sys

import pytest
from cmk.graphing.v1 import metrics, translations

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_bgp_mon"


@pytest.fixture(scope="module")
def graphing_objects():
    objects = []
    for path in sorted((PLUGIN / "graphing").glob("*.py")):
        name = "test_bgp_graphing_" + path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        objects.extend(vars(module).values())
    return objects


def test_old_uptime_metric_translates_to_the_emitted_name(graphing_objects):
    found = [o for o in graphing_objects if isinstance(o, translations.Translation)]
    assert len(found) == 1
    translation = found[0]
    # The lookup key is the check command a live service runs today
    assert translation.check_commands == [translations.PassiveCheck("oposs_bgp_mon_sessions")]
    # The name test_check.py sees the check emit
    assert translation.translations == {"uptime": translations.RenameTo("oposs_bgp_mon_uptime")}


def test_uptime_metric_is_declared(graphing_objects):
    found = [o for o in graphing_objects if isinstance(o, metrics.Metric)]
    assert [m.name for m in found] == ["oposs_bgp_mon_uptime"]
    assert found[0].unit == metrics.Unit(metrics.TimeNotation())
