# TP-Link TL-ER6020 for Home Assistant

Custom integration for TL-ER6020 v2 (firmware 2.0.x). Opens selected port forwarding rules while you're away and closes them when you're back. Talks to the router's local web API — no cloud, no open management ports.

> **Beta.** The API was reverse-engineered from the router's web UI of firmware 2.0.3 Build 20200623. Other firmware versions may behave differently — please open an issue with `scripts/probe.py` output if something doesn't work.

## How it works

- Every 30 s the integration reads the router's ARP table.
- When the tracked device (e.g. your phone) has been missing for **Away delay** minutes, the selected **Virtual Server** rules are enabled.
- As soon as the device is back, they are disabled.
- Optional notifications on open/close — via a `notify` service (e.g. `mobile_app_iphone`) or in the HA UI.

Entities:

- `switch` per Virtual Server rule (Transmission → NAT → Virtual Servers) for manual control.
- `device_tracker` for the tracked device — can be added to a `person`.

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/aremishevsky/ha-tplink-er6020`, type **Integration**.
2. Find **TP-Link TL-ER6020** in HACS → **Download**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/tplink_er6020` into `/config/custom_components/` and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → TP-Link TL-ER6020**

1. Router IP, username, password.
2. Device to track (★ = DHCP reservation, listed first), ports to control, away delay (default 10 min), notifications.

Change step 2 later via **Configure** on the integration page.

## Check API from a laptop

```bash
pip install aiohttp
export ER6020_HOST=192.168.0.1 ER6020_USER=admin
read -s ER6020_PASSWORD && export ER6020_PASSWORD
python scripts/probe.py
python scripts/probe.py toggle "RULE NAME" off
```

## Notes

- iPhone: disable *Private Wi-Fi Address* for the home network so the MAC stays stable, and reserve its IP in the router.
- The router allows a limited number of admin web sessions; polling may log you out of the web UI (and vice versa — the integration re-logins automatically).
