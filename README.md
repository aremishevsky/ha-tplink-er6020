# TP-Link TL-ER6020 for Home Assistant

Custom integration for TL-ER6020 v2 (firmware 2.0.x). Talks to the router's local web API — no cloud, no open management ports.

> **Beta.** The API was reverse-engineered from the router's web UI of firmware 2.0.3 Build 20200623. Other firmware versions may behave differently — please open an issue with `scripts/probe.py` output if something doesn't work.

## Features

- `switch` per **Virtual Server** rule (Transmission → NAT → Virtual Servers) — enable/disable port forwarding.
- `device_tracker` per LAN client (router ARP table + DHCP names), disabled by default — enable your phone.
- Options: polling interval, `consider_home` grace period.

## Check API first (from a laptop in the LAN)

```bash
pip install aiohttp
export ER6020_HOST=192.168.0.1 ER6020_USER=admin
read -s ER6020_PASSWORD && export ER6020_PASSWORD
python scripts/probe.py
python scripts/probe.py toggle "RULE NAME" off
```

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/aremishevsky/ha-tplink-er6020`, type **Integration**.
2. Find **TP-Link TL-ER6020** in HACS → **Download**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/tplink_er6020` into `/config/custom_components/` and restart Home Assistant.

### Setup

**Settings → Devices & services → Add integration → TP-Link TL-ER6020**, then enter router IP, username and password.

## Automation

See [examples/automations.yaml](examples/automations.yaml): `person` combining Companion app + router tracker → open ports after 10 min away, close on return.

## Notes

- The router allows a limited number of admin web sessions; polling may log you out of the web UI (and vice versa — the integration re-logins automatically). Increase the polling interval if that annoys you.
- iPhone: disable *Private Wi-Fi Address* for the home network so the MAC stays stable.
