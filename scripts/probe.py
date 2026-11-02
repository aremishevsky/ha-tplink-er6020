"""Check the router API from a laptop before installing into Home Assistant.

    pip install aiohttp
    export ER6020_HOST=192.168.0.1 ER6020_USER=admin
    read -s ER6020_PASSWORD && export ER6020_PASSWORD
    python scripts/probe.py                 # list rules, DHCP clients, ARP
    python scripts/probe.py toggle "NAME" on|off
"""
import asyncio
import json
import os
from pathlib import Path
import sys

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "tplink_er6020"))
from api import ER6020Client  # noqa: E402


async def main() -> None:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        client = ER6020Client(
            session,
            os.environ.get("ER6020_HOST", "192.168.0.1"),
            os.environ.get("ER6020_USER", "admin"),
            os.environ["ER6020_PASSWORD"],
        )
        await client.login()
        print("login ok")

        if len(sys.argv) == 4 and sys.argv[1] == "toggle":
            await client.set_virtual_server_enabled(sys.argv[2], sys.argv[3] == "on")
            print("toggled")

        for title, fetch in (
            ("virtual servers", client.get_virtual_servers),
            ("dhcp reservations", client.get_dhcp_reservations),
            ("dhcp clients", client.get_dhcp_clients),
            ("arp list", client.get_arp_list),
        ):
            print(f"== {title}")
            print(json.dumps(await fetch(), indent=2, ensure_ascii=False))


asyncio.run(main())
