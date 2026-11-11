# Copyright (C) 2023 OETIKER+PARTNER AG – License: GNU General Public License v2

from cmk.graphing.v1 import Title, metrics

# The name the check emits; translations.py maps the pre-1.0 "uptime" onto it
metric_oposs_bgp_mon_uptime = metrics.Metric(
    name="oposs_bgp_mon_uptime",
    title=Title("BGP session uptime"),
    unit=metrics.Unit(metrics.TimeNotation()),
    color=metrics.Color.BLUE,
)
