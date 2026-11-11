# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

### Changed

### Fixed

## 1.3.1 - 2026-11-11
### Fixed
- The device password of an "OPOSS BGP Monitor" rule no longer shows in
  plain text in the process list (`ps`) or in the configuration Checkmk
  generates for its core. The special agent now gets a reference into the
  Checkmk password store instead, both for a password typed into the rule
  and for one picked from the store, and existing rules need no editing.
  Until the changes are activated after the update, the agent gets the
  password as before.

## 1.3.0 - 2026-11-11
### Changed
- A Palo Alto BGP peer that is not up now shows WARN or CRIT for its state,
  with "af-name: n/a". Before, such a peer had no "BGP ..." service, or its
  service went UNKNOWN with "Session ... not found in agent output". Run a
  service discovery to get services for the peers that are down now.
- With `--debug` or `-vv`, the special agent no longer writes the full
  output of a Huawei device to the log, as base64 or as text. It logs the
  matched BGP peer blocks and the size of the output.

### Fixed
- With `--debug` or `-vv`, the special agent no longer writes the Palo Alto
  API key or the password of the key request to the log. It logs that a key
  was received.
- When the SSH session to a Huawei device fails, the special agent reports
  a short error such as "Error: Failed to fetch data from switch1: TIMEOUT".
  Before, the error carried the internal state of the session, with the last
  output of the device.
- The special agent gives up on a Cisco or Palo Alto device that does not
  answer within 30 seconds and reports an error. Before, it kept waiting
  for the answer.
- When a Palo Alto device answers the key request without a key, the special
  agent warning "Failed to extract key from:" now shows the answer of the
  device instead of a literal "%s".
- A device with the host address "test" is now asked for its BGP sessions
  like any other. Before, the special agent read them from a file under
  `/tmp` on the Checkmk server, and a Huawei device of that name always failed
  with "No such file or directory".
- A Cisco device with a BGP peer that was never up now reports all its BGP
  sessions. Before, the special agent stopped with "Error: Got invalid data
  from host" and no "BGP ..." service of the device got data. The peer that
  was never up shows its state without an uptime.
- The uptime graph of a "BGP ..." service has the title "BGP session uptime"
  and shows its values as time spans. Before, the metric was not declared,
  so the graph had no proper title and showed plain numbers.

## 1.2.0 - 2026-11-06
### New
- The package carries the release version in its check plugin (`__version__`).
- The special agent carries the release version in `__version__`.

### Changed
- A BGP session outside the default VRF gets " VRF <name>" in its service
  name, for example "BGP AS65001 10.0.0.2 VRF blue". Before, the same peer in
  two VRFs shared one "BGP AS65001 10.0.0.2" service, which showed only one of
  the sessions, so the other could go down without an alert. Run a service
  discovery: the old services of all sessions outside the default VRF vanish
  with their uptime graphs, and the new ones appear.
- Palo Alto sessions are named after the remote AS and the peer address,
  for example "BGP AS65010 198.51.100.1" instead of
  "BGP AS198.51.100.1:179 ISP", and their "neighbouras" and "neighbourid"
  lines show these values. Run a service discovery: the old services vanish
  with their uptime graphs, and the new ones appear.
- The package now requires Checkmk 2.4.0p1 or later. On Checkmk 2.3 the
  BGP session check never loaded, so its services could not be discovered
  or checked there.
- Licence is now GNU General Public License v2, matching the headers
  the source files carry. The `LICENSE` file previously held the MIT
  text, which contradicted them.

### Fixed
- With "Minimum uptime after recovery" set in the rule "OPOSS BGP Monitor
  Sessions Parameters", also to "No levels", every established "BGP AS..."
  service went UNKNOWN with a crash report. These services now go WARN or CRIT
  while the session has been up for less than the levels, and OK after that.
- On a Cisco Nexus switch with BGP in only one VRF, or only one address
  family in a VRF, the special agent failed with "Got invalid data from host"
  and no "BGP AS..." service was found. These sessions are now discovered and
  checked.
- On a Checkmk site without the Python module pexpect, the special agent
  failed for Cisco and Palo Alto devices too, with "The 'pexpect' library is
  required for Huawei devices but is not installed." Only the Huawei driver
  needs pexpect now.
- On a Huawei switch whose BGP output held a character outside ASCII, for
  example an umlaut in a peer description, the special agent failed with "Got
  invalid data from host" and none of its "BGP AS..." services was checked.
  Such output is now read.
- An agent output line that was valid JSON but not a session record made the
  whole section fail, so every "BGP AS..." service of the host went UNKNOWN
  with a crash report. Such a line now counts as a parse error, reported in
  the service "BGP _parse_errors", and the other sessions are checked.

## 1.1.3 - 2026-04-27
### Changed
- `graphing/translations.py`: removed the dead `bgp_mon_sessions`
  `PassiveCheck` key. Checkmk's translation lookup is an exact dict-key
  match on the live service's current check command, so the legacy entry
  never fired (no service has the legacy command after the old plugin is
  uninstalled). The new `oposs_bgp_mon_sessions` key remains and continues
  to handle the `uptime` → `oposs_bgp_mon_uptime` rename so legacy RRD
  history merges into the new graph. Pure cleanup; no behaviour change.

## 1.1.2 - 2025-11-27
### Fixed
- Fix nameing inconsistancies

## 1.1.1 - 2025-11-27
### Changed
- Fix nameing inconsistancies

## 1.1.0 - 2025-11-27
### New
- Added "minimum uptime after recovery" feature: configurable
  thresholds to keep recently-recovered BGP sessions in
  WARNING/CRITICAL state until stable (inspired by cisco_bgp_peer plugin)

### Changed
- When logging in via ssh wait for "assword: " and not just
  for "assword:"

## 1.0.7 - 2025-11-19
### Changed
- allow install on 2.3.0

## 1.0.6 - 2025-11-18
## 1.0.5 - 2025-11-18
### Changed
- require ssl verification setting
- remove OETIKER+PARTNER from plugin name

## 1.0.4 - 2025-11-17
### Changed
- Agent now uses hostname instead of IP address for proper HTTPS/SSL certificate validation
- Added `if __name__ == "__main__"` guard to agent plugin for proper module import behavior

## 1.0.3 - 2025-11-17
### Fixed
- Fixed import error: removed deprecated `cmk.agent_based.v2.type_defs` import, now importing types directly from `cmk.agent_based.v2` for Checkmk 2.4.0+ compatibility

## 1.0.2 - 2025-11-17
### Changed
- Improved error message when pexpect library is missing for Huawei devices

### Fixed
- Fixed import error: changed `from cmk.utils import debug` to `from cmk.ccc import debug` for Checkmk 2.4.0+ compatibility

## 1.0.1 - 2025-11-13
### Fixed
- build correct mkp

## 1.0.0 - 2025-11-13

### Changed
- Ported to cmk api 2 and new plugin structures

### Fixed
- Make ssl security configurable


