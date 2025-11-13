#!/usr/bin/env python3
# Copyright (C) 2023 OETIKER+PARTNER AG – License: GNU General Public License v2

from cmk.graphing.v1 import translations

# Preserve historical data: translate old "uptime" metric to new "oposs_bgp_mon_uptime"
# This ensures that when users upgrade from bgp_mon to oposs_bgp_mon, their historical
# RRD data remains visible in graphs.
#
# Data flow:
# - Old RRD files: service_uptime.rrd (from bgp_mon plugin)
# - New RRD files: service_oposs_bgp_mon_uptime.rrd (from oposs_bgp_mon plugin)
# - When graphing "oposs_bgp_mon_uptime", both RRD files are queried and merged chronologically
translation_oposs_bgp_mon_sessions = translations.Translation(
    name="oposs_bgp_mon_sessions",
    check_commands=[
        translations.PassiveCheck("oposs_bgp_mon_sessions"),  # New plugin
        translations.PassiveCheck("bgp_mon_sessions"),        # Old plugin (for migration)
    ],
    translations={
        "uptime": translations.RenameTo("oposs_bgp_mon_uptime"),
    },
)
