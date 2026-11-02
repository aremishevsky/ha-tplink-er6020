# TP-Link ER6020 AutoPortOnOff for Home Assistant

Custom integration for TL-ER6020 v2 (firmware 2.0.x). Opens selected port forwarding rules while you're away and closes them when you're back. Talks to the router's local web API — no cloud, no open management ports.

> **Beta.** The API was reverse-engineered from the router's web UI of firmware 2.0.3 Build 20200623. Other firmware versions may behave differently — please open an issue with `scripts/probe.py` output if something doesn't work.

## How it works

- Every **Polling interval** (default 120 s) the integration reads the router's ARP table.
- When the tracked device (e.g. your phone) has been missing for **Away delay** minutes, the selected **Virtual Server** rules are enabled.
- As soon as the device is back, they are disabled.
- With **Use schedule** on, outside active hours (default 07:00–23:00) the selected rules are always closed.
- Optional notifications on open/close (automatic and manual) — via a `notify` service (e.g. `mobile_app_iphone`) or in the HA UI.

Entities:

- `switch` per Virtual Server rule (Transmission → NAT → Virtual Servers) for manual control. Attributes include `last_on`, `last_off` and a change `log` with the reason (away / home / schedule / manual / router).
- `switch` **Router polling** — turn off to stop all requests to the router (e.g. while you use its web UI, which allows only one admin session). Port switches keep working on demand; automation is paused.
- `switch` **Automation** — turn off to stop opening/closing ports automatically; polling and manual control keep working.
- `device_tracker` for the tracked device — can be added to a `person`.

## Dashboard card

The integration ships a Lovelace card — no separate install needed. Edit dashboard → **Add card** → **TP-Link ER6020 AutoPortOnOff**.

- Presence, polling toggle with last update time and errors, automation toggle (🕒 when the schedule is on).
- Selected ports (choose and reorder in the card editor) with status, time of the last change and a toggle.
- Tap the card for details: active hours and all ports with the change log.
- `layout: buttons` shows everything as a grid of square buttons (polling, automation, ports; presence too when the title is hidden) — tap a button to toggle it, tap the title or the presence button for details.

```yaml
type: custom:tplink-er6020-card
title: TP-Link ER6020 ports
presence_entity: device_tracker.iphone
show_polling: true
show_automation: true
show_title: true      # false = no header
background: true      # false = transparent card
layout: list          # or: buttons
columns: 4            # buttons per row (layout: buttons)
hold_action: details   # long press on a button: details | more-info | none
entities:
  - switch.tl_er6020_port_forward_ssh
  - switch.tl_er6020_port_forward_plex
```

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/aremishevsky/ha-tplink-er6020`, type **Integration**.
2. Find **TP-Link ER6020 AutoPortOnOff** in HACS → **Download**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/tplink_er6020` into `/config/custom_components/` and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → TP-Link TL-ER6020**

1. Router IP, username, password (see [Router account](#router-account)).
2. Device to track (★ = DHCP reservation, listed first), ports to control, away delay (default 10 min), polling interval (default 120 s), *Use schedule*, *Use notifications*.
3. If *Use schedule* is ticked: active hours.
4. If *Use notifications* is ticked: notify on open/close, notification channels, *Send a test notification*.

Change steps 2–4 later via **Configure** on the integration page.

## Check API from a laptop

```bash
pip install aiohttp
export ER6020_HOST=192.168.0.1 ER6020_USER=admin
read -s ER6020_PASSWORD && export ER6020_PASSWORD
python scripts/probe.py
python scripts/probe.py toggle "RULE NAME" off
```

## Router account

TL-ER6020 v2 has **a single administrator account** — there are no extra users or roles, so a dedicated read-only account for Home Assistant is not possible. The integration uses that admin account. To keep it safe:

1. **Set a strong admin password.** System Tools → Admin Setup → **Admin Setup**: enter the old username/password, then a new username and password (6–15 characters). Use these credentials in the integration.
2. **Keep the web UI LAN-only.** System Tools → Admin Setup → **Remote Management**: make sure remote management is disabled (or limited to specific IPs).
3. **Prefer HTTPS.** System Tools → Admin Setup → **System Settings**: keep HTTPS enabled and *Redirect HTTP to HTTPS* on — the integration always uses HTTPS.
4. **Reserve the Home Assistant IP** (Network → LAN → **Address Reservation**) so its address doesn't change.

Home Assistant stores the password in `.storage/core.config_entries`, like any other integration.

### Using the router web UI

The router allows **only one admin session at a time**: when the integration logs in, your browser session ends, and vice versa. Before working in the web UI, turn off the **Router polling** switch (or the toggle on the dashboard card) — the integration then makes no requests at all. Turn it back on when you're done.

If you are logged in to the web UI while polling is on, the integration gets a *login conflict*, logs it and retries on the next poll — it does **not** ask you to re-enter the password.

## Notes

- iPhone: disable *Private Wi-Fi Address* for the home network so the MAC stays stable, and reserve its IP in the router.
