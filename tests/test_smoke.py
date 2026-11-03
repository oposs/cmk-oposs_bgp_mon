# repo-infra: checkmk-harness v1
"""Every plugin module imports and registers.

This is the floor, not the ceiling. It catches the failure that actually
happens: a check that references a Checkmk API which moved, discovered by a
user on upgrade rather than by CI.
"""

import importlib.util
import pathlib
import sys

import pytest

# Anchored to this file, not to the working directory: `pytest tests/` and
# `pytest` from a subdirectory must collect the same modules, or the suite
# silently shrinks to nothing and still reports success.
ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = sorted((ROOT / "local/lib/python3").rglob("*.py"))


def _module_name(path):
    """A name unique per file.

    Several plugins name the agent_based, graphing and rulesets modules
    identically, so the file stem is not unique. Registering two different
    files under one name would let the second silently reuse the first.
    """
    return "cmk_smoke_" + path.relative_to(ROOT).as_posix().replace("/", "_")[:-3]


# Modules known not to import against CMK_VERSION, with the reason. Each one
# is a bug in the plugin, kept visible here until it is fixed; strict, so the
# fix turns the run red until this entry goes.
KNOWN_BROKEN = {
    "local/lib/python3/cmk_addons/plugins/oposs_bgp_mon/agent_based/oposs_bgp_mon_sessions.py":
        "BUG: imports cmk.ccc.debug, which no Checkmk 2.3 release has (2.4+ only)",
}


def _params():
    for path in MODULES:
        reason = KNOWN_BROKEN.get(path.relative_to(ROOT).as_posix())
        marks = [pytest.mark.xfail(strict=True, raises=ImportError, reason=reason)] if reason else []
        yield pytest.param(path, marks=marks, id=str(path.relative_to(ROOT)))


@pytest.mark.parametrize("path", list(_params()))
def test_the_module_imports(path):
    name = _module_name(path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # A dataclass with `from __future__ import annotations` resolves its
    # deferred annotations by looking itself up in sys.modules, so a module
    # that is not registered there fails to import for a reason that has
    # nothing to do with the plugin.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)


def test_there_is_something_to_import():
    assert MODULES, "no plugin modules under local/lib/python3 -- is this a Checkmk plugin?"
