"""Async client for the TP-Link TL-ER6020 v2 web API (firmware 2.0.x).

The router UI talks to LuCI JSON endpoints:
  POST /cgi-bin/luci/;stok=<token><path>   body: data=<json>
Login password is RSA-encrypted (raw, zero-padded, no PKCS#1) with a key
returned by the login endpoint itself.

This module has no Home Assistant imports so it can be used from scripts.
"""
from __future__ import annotations

import json
import logging
import ssl
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


def _legacy_ssl_context() -> ssl.SSLContext:
    """Router only offers TLS 1.2 with RSA key exchange and a SHA1 self-signed
    cert, which Python's default cipher list rejects."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx


_SSL_CONTEXT = _legacy_ssl_context()

URL_LOGIN = "/login?form=login"
URL_VIRTUAL_SERVERS = "/admin/nat?form=vs"
URL_DHCP_CLIENTS = "/admin/dhcps?form=client"
URL_DHCP_RESERVATIONS = "/admin/dhcps?form=reservation"
URL_ARP_LIST = "/admin/arplist?form=getlist"

VS_FIELDS = (
    "name",
    "interface",
    "external_port",
    "internal_port",
    "ipaddr",
    "protocol",
    "enable",
)


class ER6020Error(Exception):
    """Generic router error."""


class ER6020AuthError(ER6020Error):
    """Login rejected."""


def encrypt_password(password: str, n_hex: str, e_hex: str) -> str:
    """Replicate $.su.encrypt from webpages/js/libs/encrypt.js."""
    n = int(n_hex, 16)
    e = int(e_hex, 16)
    size = (n.bit_length() + 7) >> 3

    # Same (slightly unusual) UTF-8 byte order as the router's JS.
    buf: list[int] = []
    for ch in password:
        c = ord(ch)
        if c < 128:
            buf.append(c)
        elif c < 2048:
            buf += [(c & 63) | 128, (c >> 6) | 192]
        else:
            buf += [(c & 63) | 128, ((c >> 6) & 63) | 128, (c >> 12) | 224]
    if len(buf) > size:
        raise ER6020Error("Password too long for RSA key")

    m = int.from_bytes(bytes(buf) + b"\0" * (size - len(buf)), "big")
    if buf and buf[0] & 0x80:
        # JS BigInteger reads a byte array with the high bit set as negative.
        m -= 1 << (8 * size)
    h = format(pow(m % n, e, n), "x")
    return h if len(h) % 2 == 0 else "0" + h


class ER6020Client:
    """Minimal client: login, virtual servers, DHCP clients, ARP list."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._base = host.rstrip("/") if host.startswith("http") else f"https://{host}"
        self._username = username
        self._password = password
        self._stok: str | None = None

    async def _post(self, path: str, payload: dict[str, Any], stok: str = "") -> dict:
        url = f"{self._base}/cgi-bin/luci/;stok={stok}{path}"
        headers = {
            "Referer": f"{self._base}/webpages/index.html",
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            async with self._session.post(
                url,
                data={"data": json.dumps(payload, separators=(",", ":"))},
                headers=headers,
                ssl=_SSL_CONTEXT,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ER6020Error(f"Request to {path} failed: {err}") from err

        try:
            return json.loads(text)
        except ValueError as err:
            # Expired session usually yields an HTML page instead of JSON.
            raise ER6020Error(f"Non-JSON response from {path}") from err

    async def login(self) -> None:
        keys = await self._post(URL_LOGIN, {"method": "get"})
        try:
            n_hex, e_hex = keys["result"]["password"]
        except (KeyError, TypeError, ValueError) as err:
            raise ER6020Error(f"Unexpected key response: {keys}") from err

        resp = await self._post(
            URL_LOGIN,
            {
                "method": "login",
                "params": {
                    "username": self._username,
                    "password": encrypt_password(self._password, n_hex, e_hex),
                },
            },
        )
        result = resp.get("result") or {}
        stok = result.get("stok")
        if str(resp.get("error_code")) != "0" or not stok:
            # 700 = bad credentials; result carries failureCount/attemptsAllowed.
            self._stok = None
            raise ER6020AuthError(
                f"Login failed (error_code={resp.get('error_code')}, "
                f"attempts left={result.get('attemptsAllowed')})"
            )
        self._stok = stok

    async def _request(self, path: str, payload: dict[str, Any]) -> Any:
        """Authenticated request; re-login once on failure."""
        for attempt in (1, 2):
            if self._stok is None:
                await self.login()
            try:
                resp = await self._post(path, payload, self._stok or "")
            except ER6020Error:
                if attempt == 2:
                    raise
                self._stok = None
                continue
            if str(resp.get("error_code")) == "0":
                return resp.get("result")
            if attempt == 2:
                raise ER6020Error(f"{path} failed (error_code={resp.get('error_code')})")
            _LOGGER.debug("%s returned %s, re-login", path, resp.get("error_code"))
            self._stok = None
        return None

    async def _get_list(self, path: str) -> list[dict[str, Any]]:
        result = await self._request(path, {"method": "get", "params": {}})
        if isinstance(result, dict):
            result = [result]
        return result or []

    async def get_virtual_servers(self) -> list[dict[str, Any]]:
        return await self._get_list(URL_VIRTUAL_SERVERS)

    async def get_dhcp_clients(self) -> list[dict[str, Any]]:
        return await self._get_list(URL_DHCP_CLIENTS)

    async def get_dhcp_reservations(self) -> list[dict[str, Any]]:
        return await self._get_list(URL_DHCP_RESERVATIONS)

    async def get_arp_list(self) -> list[dict[str, Any]]:
        return await self._get_list(URL_ARP_LIST)

    async def set_virtual_server_enabled(self, name: str, enabled: bool) -> None:
        """Mimic the status-column toggle in the Virtual Servers grid."""
        rules = await self.get_virtual_servers()
        for index, rule in enumerate(rules):
            if rule.get("name") == name:
                break
        else:
            raise ER6020Error(f"Virtual server '{name}' not found")

        key = rule.get("key", f"key-{index}")
        old = {f: rule.get(f) for f in VS_FIELDS} | {"key": key}
        new = {f: rule.get(f) for f in VS_FIELDS} | {"enable": "on" if enabled else "off"}
        await self._request(
            URL_VIRTUAL_SERVERS,
            {
                "method": "set",
                "params": {
                    "index": index,
                    "key": key,
                    "old": json.dumps(old, separators=(",", ":")),
                    "new": json.dumps(new, separators=(",", ":")),
                },
            },
        )
