#!/usr/bin/env python3
# Copyright (C) 2023 OETIKER+PARTNER AG – License: GNU General Public License v2

import json
from typing import Any, Mapping
from pprint import pprint
from collections import namedtuple

from cmk.ccc import debug
from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    Metric,
    Result,
    Service,
    State,
)

Section = Mapping[str, Any]


def parse_oposs_bgp_mon_sessions(string_table: list[list[str]]) -> Section:
    """Parse BGP session data from JSON format.

    Each line in string_table contains a JSON object with BGP session information:
    - vrf-name-out: VRF or virtual router name
    - af-name: Address family (IPv4/IPv6 Unicast, etc.)
    - neighbourid: BGP neighbor identifier
    - neighbouras: Neighbor AS number
    - state: Session state (established, idle, etc.)
    - uptime: Session uptime in seconds (can be null)
    """
    bgp_class = namedtuple('bgp_class', ['inventory', 'result', 'errors'])
    parsed = bgp_class(inventory=[], result={}, errors=[])

    for row in string_table:
        try:
            data = json.loads(row[0])
            service = 'AS' + data['neighbouras'] + ' ' + data['neighbourid']
            parsed.inventory.append(service)
            parsed.result[service] = data
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            error_msg = f"Failed to parse BGP session data: {e}"
            parsed.errors.append(error_msg)
            if debug.enabled():
                print(f"DEBUG: {error_msg}")
                print(f"DEBUG: Row data: {row}")

    return parsed


def discover_sessions(section: Section) -> DiscoveryResult:
    """Discover one service per BGP session.

    Service names follow the format: AS{as_number} {neighbor_id}
    Example: AS65001 10.0.0.1

    If there are parsing errors, a special error service is created.
    """
    if debug.enabled():
        print("DEBUG Discover Section:")
        pprint(section)

    # Report parsing errors as a special service
    if hasattr(section, 'errors') and section.errors:
        yield Service(item="_parse_errors")

    for service in section.inventory:
        # v2 API: discovery parameters removed (not supported)
        yield Service(item=service)


def check_oposs_bgp_mon_sessions(item: Any, params: Mapping[str, Any], section: Section) -> CheckResult:
    """Check BGP session state and report metrics.

    States:
    - established: OK (session active)
    - idle: CRITICAL (session down)
    - other states: WARNING (transitional states)

    Metrics:
    - oposs_bgp_mon_uptime: Session uptime in seconds
    """
    # Special service for reporting parsing errors
    if item == "_parse_errors":
        if hasattr(section, 'errors') and section.errors:
            error_count = len(section.errors)
            yield Result(
                state=State.WARN,
                summary=f"Failed to parse {error_count} BGP session(s)"
            )
            for error in section.errors[:5]:  # Show first 5 errors
                yield Result(state=State.OK, notice=error)
        else:
            yield Result(state=State.OK, summary="No parsing errors")
        return

    result = section.result.get(item, {})

    if not result:
        yield Result(
            state=State.UNKNOWN,
            summary=f"Session {item} not found in agent output"
        )
        return

    if debug.enabled():
        print("DEBUG Check Section:")
        pprint(item)
        pprint(result)

    # Report informational fields
    session_status = result.get("state", "").lower()
    for key in ['vrf-name-out', 'af-name', 'neighbourid', 'neighbouras']:
        yield Result(state=State.OK, summary=f"{key}: {result.get(key, 'n/a')}")

    # Report uptime metric (if available)
    if "uptime" in result and result["uptime"] is not None:
        # v2 API: metric renamed with proper prefix to avoid conflicts
        yield Metric(
            name="oposs_bgp_mon_uptime",
            value=float(result["uptime"]),
        )

    # Evaluate session state with min_uptime check for established sessions
    session_state = result.get('state', 'n/a')
    uptime = result.get('uptime')

    if session_status == 'established':
        # Check minimum uptime thresholds (warn, crit) - uses LOWER direction
        min_uptime = params.get('min_uptime')
        if min_uptime is not None and uptime is not None:
            warn_threshold, crit_threshold = min_uptime
            if crit_threshold and uptime < crit_threshold:
                yield Result(
                    state=State.CRIT,
                    summary=f"state: {session_state} (uptime {uptime:.0f}s < {crit_threshold:.0f}s critical threshold)",
                )
                return
            elif warn_threshold and uptime < warn_threshold:
                yield Result(
                    state=State.WARN,
                    summary=f"state: {session_state} (uptime {uptime:.0f}s < {warn_threshold:.0f}s warning threshold)",
                )
                return
        yield Result(state=State.OK, summary=f"state: {session_state}")
    elif session_status == 'idle':
        yield Result(state=State.CRIT, summary=f"state: {session_state}")
    else:
        yield Result(state=State.WARN, summary=f"state: {session_state}")


# v2 API: Class-based registration with entry point prefix
# Supersedes the old bgp_mon_sessions plugin for automatic service migration
agent_section_oposs_bgp_mon_sessions = AgentSection(
    name="oposs_bgp_mon_sessions",
    parse_function=parse_oposs_bgp_mon_sessions,
    supersedes=["bgp_mon_sessions"],  # Automatic migration from old plugin
)

check_plugin_oposs_bgp_mon_sessions = CheckPlugin(
    name="oposs_bgp_mon_sessions",
    service_name="BGP %s",
    sections=["oposs_bgp_mon_sessions"],
    discovery_function=discover_sessions,
    check_function=check_oposs_bgp_mon_sessions,
    check_default_parameters={},
    check_ruleset_name="oposs_bgp_mon_sessions",
)
