# CheckMK OETIKER+PARTNER BGP Monitor

**Version 1.0.0** - CheckMK 2.4 (v2 API) compatible

This extension pack contains a CheckMK special agent that monitors BGP sessions on network devices. It contacts your networking equipment to discover BGP sessions and monitor their operational state.

## Features

- **Multi-vendor support**: Works with different device types
- **Automatic discovery**: Discovers all BGP sessions automatically
- **State monitoring**: Tracks session state (Established, Idle, etc.)
- **Uptime metrics**: Reports BGP session uptime with historical graphing
- **SSL verification**: Configurable SSL/TLS certificate validation
- **CheckMK 2.4 ready**: Uses modern v2 API

## Supported Devices

* **Cisco Nexus 9000** (HTTP/HTTPS JSON-RPC API)
* **Huawei Sx700** (SSH with CLI commands)
* **Palo Alto Networks** (HTTPS XML API)

More drivers can be added in the future.

## Requirements

- **CheckMK version**: 2.4 or newer (uses v2 API)
- **Python dependencies**:
  - `requests` (included with CheckMK)
  - `pexpect` (required for Huawei devices only - install with `pip3 install pexpect` in OMD site)

## Installation

1. Download the MKP package: `oposs_bgp_mon-1.0.0.mkp`
2. Install via command line:
   ```bash
   cmk -P install oposs_bgp_mon-1.0.0.mkp
   ```
   Or via Web UI: **Setup → Maintenance → Extension packages**

## Configuration

1. Navigate to **Setup → Agents → VM, Cloud, Container → OETIKER+PARTNER BGP Monitor**
2. Create a new rule for your BGP-enabled device:
   - **Username**: Device login username
   - **Password**: Device password (stored securely)
   - **Driver**: Select your device type:
     - `Cisco Nexus 9000 HTTP`
     - `Cisco Nexus 9000 HTTPS`
     - `Huawei Sx700 SSH`
     - `Palo Alto Networks XML API`
   - **Verify SSL certificates**:
     - ✅ Enabled (default, recommended for production)
     - ❌ Disabled (for self-signed certificates)
3. Apply the rule to your host(s)
4. Run service discovery on the host

## Service Discovery

After configuration, run discovery to create services:

```bash
cmk -II your-router-hostname
```

This will create one service per BGP session in the format:
- **Service name**: `BGP AS{asn} {neighbor-ip}`
- **Example**: `BGP AS65001 10.0.0.1`

## Monitoring States

- **OK (Green)**: Session state is `Established`
- **CRITICAL (Red)**: Session state is `Idle`
- **WARNING (Yellow)**: Session in transitional state (e.g., `Active`, `OpenConfirm`)
- **UNKNOWN (Gray)**: Cannot retrieve session data

## Metrics

Each BGP session reports:
- **oposs_bgp_mon_uptime**: Session uptime in seconds (graphed over time)

Service details display:
- VRF/Virtual Router name
- Address family (IPv4/IPv6 Unicast, L2VPN EVPN)
- Neighbor ID
- Neighbor AS number
- Current state

## Migrating from bgp_mon (v1)

If you're upgrading from the old `bgp_mon` plugin, see **[MIGRATION_TO_V2.md](MIGRATION_TO_V2.md)** for detailed migration instructions.

**Key changes:**
- Plugin renamed: `bgp_mon` → `oposs_bgp_mon`
- New SSL verification option
- Historical data automatically preserved
- Services migrate automatically with `supersedes` mechanism

## Troubleshooting

### No services discovered

**Cause**: Special agent not configured or not running

**Solution**:
1. Check rule is applied to host: **Setup → Agents → VM, Cloud, Container → OETIKER+PARTNER BGP Monitor**
2. Test special agent manually:
   ```bash
   /omd/sites/SITE/local/lib/python3/cmk_addons/plugins/oposs_bgp_mon/libexec/agent_oposs_bgp_mon \
     -u USERNAME -p PASSWORD -r DRIVER HOSTNAME
   ```

### SSL certificate errors

**Cause**: Device uses self-signed certificate

**Solution**: Disable "Verify SSL certificates" in the WATO rule

### Huawei devices fail

**Cause**: Missing `pexpect` Python library

**Solution**: Install in OMD site:
```bash
pip3 install pexpect
```

### Parse errors service appears

**Cause**: Agent output contains malformed data

**Solution**: Check service details for error messages and verify device driver selection

## Screenshots

![2023-11-24_09-04](https://github.com/oposs/cmk-bgp_mon/assets/429279/7ae8f624-cd13-420b-93f9-68b678548c9e)
The Monitoring Screen

![2023-11-24_09-05](https://github.com/oposs/cmk-bgp_mon/assets/429279/6e43913b-0a58-4843-bf15-b26e584c7857)
The Setup Screen (note: updated for v2 with SSL verification option)

## Development

- **Plugin location**: `local/lib/python3/cmk_addons/plugins/oposs_bgp_mon/`
- **Directory structure**: Follows CheckMK 2.4 v2 API conventions
- **Metric naming**: Uses `oposs_bgp_mon_` prefix to avoid conflicts

## License

GNU General Public License v2

## Authors

**Original Plugin (v1)**:
- Tobias Oetiker <tobi@oetiker.ch>

**v2 Migration**:
- OETIKER+PARTNER AG

## Support

- GitHub Issues: https://github.com/oposs/cmk-oposs_bgp_mon/issues
- Migration Guide: [MIGRATION_TO_V2.md](MIGRATION_TO_V2.md)

Enjoy!

---
© 2023-2025 OETIKER+PARTNER AG
