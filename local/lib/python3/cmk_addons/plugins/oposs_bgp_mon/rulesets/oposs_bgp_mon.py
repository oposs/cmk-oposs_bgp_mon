#!/usr/bin/env python3
# Copyright (C) 2023 OETIKER+PARTNER AG – License: GNU General Public License v2

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    DefaultValue,
    DictElement,
    Dictionary,
    InputHint,
    LevelDirection,
    SimpleLevels,
    SingleChoice,
    SingleChoiceElement,
    String,
    Password,
    BooleanChoice,
    TimeMagnitude,
    TimeSpan,
)
from cmk.rulesets.v1.rule_specs import (
    CheckParameters,
    HostAndItemCondition,
    SpecialAgent,
    Topic,
)


def _parameter_form() -> Dictionary:
    return Dictionary(
        title=Title("OPOSS BGP Monitor"),
        help_text=Help(
            "This rule configures the OPOSS BGP monitoring special agent "
            "which collects BGP session information from network devices. "
            "Supports Cisco Nexus 9000, Huawei Sx700, and Palo Alto Networks devices."
        ),
        elements={
            "username": DictElement(
                parameter_form=String(
                    title=Title("Username"),
                    help_text=Help("Username for device authentication"),
                ),
                required=True,
            ),
            "password": DictElement(
                parameter_form=Password(
                    title=Title("Password"),
                    help_text=Help("Password for device authentication (stored securely)"),
                ),
                required=True,
            ),
            "driver": DictElement(
                parameter_form=SingleChoice(
                    title=Title("Device Driver"),
                    help_text=Help("Select the driver matching your device type"),
                    elements=[
                        SingleChoiceElement(
                            name="cisco_http",
                            title=Title("Cisco Nexus 9000 HTTP"),
                        ),
                        SingleChoiceElement(
                            name="cisco_https",
                            title=Title("Cisco Nexus 9000 HTTPS"),
                        ),
                        SingleChoiceElement(
                            name="huawei",
                            title=Title("Huawei Sx700 SSH"),
                        ),
                        SingleChoiceElement(
                            name="paloalto",
                            title=Title("Palo Alto Networks XML API"),
                        ),
                    ],
                    prefill=DefaultValue("cisco_https"),
                ),
                required=True,
            ),
            "verify_ssl": DictElement(
                parameter_form=BooleanChoice(
                    title=Title("Verify SSL certificates"),
                    label=Label("Verify SSL/TLS certificates"),
                    help_text=Help(
                        "When enabled, SSL/TLS certificates are verified for secure connections. "
                        "Disable only for devices with self-signed certificates. "
                        "Note: Only applies to HTTPS-based drivers (Cisco HTTPS, Palo Alto). "
                        "Recommended: Keep enabled for production environments."
                    ),
                    prefill=DefaultValue(True),
                ),
                required=True,
            ),
        },
    )


rule_spec_special_agent_oposs_bgp_mon = SpecialAgent(
    name="oposs_bgp_mon",
    title=Title("OPOSS BGP Monitor"),
    topic=Topic.NETWORKING,
    parameter_form=_parameter_form,
)


def _check_parameter_form() -> Dictionary:
    return Dictionary(
        title=Title("OPOSS BGP Monitor Session Parameters"),
        elements={
            "min_uptime": DictElement(
                parameter_form=SimpleLevels[float](
                    title=Title("Minimum uptime after recovery"),
                    help_text=Help(
                        "When a BGP session recovers to 'established' state, "
                        "keep it in WARNING/CRITICAL state until it has been "
                        "up for at least this duration. This helps detect "
                        "flapping sessions."
                    ),
                    level_direction=LevelDirection.LOWER,
                    form_spec_template=TimeSpan(
                        displayed_magnitudes=[
                            TimeMagnitude.MINUTE,
                            TimeMagnitude.SECOND,
                        ],
                    ),
                    prefill_fixed_levels=InputHint((60.0, 0.0)),
                ),
                required=False,
            ),
        },
    )


rule_spec_check_parameters_oposs_bgp_mon_sessions = CheckParameters(
    name="oposs_bgp_mon_sessions",
    title=Title("OPOSS BGP Monitor Sessions Parameters"),
    topic=Topic.NETWORKING,
    parameter_form=_check_parameter_form,
    condition=HostAndItemCondition(item_title=Title("OPOSS BGP Monitor Sessions Parameters")),
)
