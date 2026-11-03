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
    # IMPORTANT: must reference the *new* check command. Checkmk's translation
    # lookup is an exact dict-key match against the live service's current
    # check_command — entries keyed on the legacy command (now uninstalled)
    # would never fire. The legacy bgp_mon_sessions key was removed because
    # it was dead code; the rename rule below still picks up legacy uptime.rrd
    # files in the same per-service directory once the new key matches.
    check_commands=[translations.PassiveCheck("oposs_bgp_mon_sessions")],
    translations={
        "uptime": translations.RenameTo("oposs_bgp_mon_uptime"),
    },
)
