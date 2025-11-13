#!/usr/bin/env python3
# Copyright (C) 2023 OETIKER+PARTNER AG – License: GNU General Public License v2

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from cmk.server_side_calls.v1 import HostConfig, Secret, SpecialAgentCommand, SpecialAgentConfig


class Params(BaseModel):
    """Parameters for the OETIKER+PARTNER BGP monitoring special agent."""
    username: str
    password: Secret
    driver: str
    verify_ssl: bool | None = None


def generate_oposs_bgp_mon_command(
    params: Params,
    host_config: HostConfig,
) -> Iterator[SpecialAgentCommand]:
    """Generate command line for the OETIKER+PARTNER BGP monitoring special agent.

    This function constructs the command line arguments for agent_oposs_bgp_mon,
    which collects BGP session information from network devices.

    Args:
        params: Configuration parameters from WATO ruleset
        host_config: Host configuration (IP address, etc.)

    Yields:
        SpecialAgentCommand with appropriate command line arguments
    """
    args = [
        "-u",
        params.username,
        "-p",
        params.password.unsafe(),
        "-r",
        params.driver,
    ]

    # Add insecure flag if SSL verification is disabled
    # For backward compatibility: if verify_ssl is not set (None), default to insecure (False)
    # This preserves the old behavior where verify=False was hardcoded for existing configs
    # New configs should explicitly set verify_ssl=True (default in WATO)
    verify_ssl = params.verify_ssl if params.verify_ssl is not None else False

    if not verify_ssl:
        args.append("--insecure")

    # Add host address as final argument
    args.append(host_config.primary_ip_config.address)

    yield SpecialAgentCommand(command_arguments=args)


# Register the special agent configuration
special_agent_oposs_bgp_mon = SpecialAgentConfig(
    name="oposs_bgp_mon",
    parameter_parser=Params.model_validate,
    commands_function=generate_oposs_bgp_mon_command,
)
