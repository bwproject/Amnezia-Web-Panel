"""Telegram Bot API transport through an existing AmneziaWG Exit Node.

The panel itself is not in the AWG container network namespace.  For selected
Exit Nodes, each Bot API request is executed by curl inside an already-linked
AWG protocol container and bound to that instance's gateway address.  This is
the same source binding used by AWGManager.exit_check_egress(), so the existing
policy rule routes the request through table 200 and exit0.  No host route,
published port, proxy daemon, or VPN-client routing change is required.
"""
import asyncio
import ipaddress
import json
import shlex
from urllib.parse import urlsplit

import httpx


_AWG_PROTOCOLS = {"awg", "awg2", "awg3", "awg_legacy"}
_STATUS_MARKER = "__BW_TELEGRAM_HTTP_STATUS__:"


class TelegramExitHTTPClient:
    """httpx-compatible client that uses the selected Exit Node or direct HTTP."""

    def __init__(self, load_data_fn, get_ssh_fn, awg_manager_factory):
        self._load_data = load_data_fn
        self._get_ssh = get_ssh_fn
        self._awg_manager_factory = awg_manager_factory
        self._direct = httpx.AsyncClient()

    async def __aenter__(self):
        await self._direct.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._direct.__aexit__(exc_type, exc, tb)

    async def post(self, url, json=None, timeout=30, **kwargs):
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or parsed.hostname != "api.telegram.org":
            raise httpx.UnsupportedProtocol("Telegram Exit transport only allows https://api.telegram.org")

        data = self._load_data()
        telegram_settings = ((data.get("settings") or {}).get("telegram") or {})
        exit_uid = str(telegram_settings.get("exit_uid") or "").strip()
        if not exit_uid:
            return await self._direct.post(url, json=json, timeout=timeout, **kwargs)

        payload = {} if json is None else json
        try:
            timeout_seconds = int(float(timeout))
        except (TypeError, ValueError):
            timeout_seconds = 30
        timeout_seconds = max(5, min(55, timeout_seconds))

        return await asyncio.to_thread(
            self._post_via_exit, str(url), payload, timeout_seconds, exit_uid
        )

    def _find_entry(self, data, exit_uid):
        servers = data.get("servers") or []
        installed_exit = any(
            (server.get("uid") == exit_uid)
            and bool(((server.get("protocols") or {}).get("exit") or {}).get("installed"))
            for server in servers
        )
        if not installed_exit:
            raise httpx.ConnectError("Selected Telegram Exit Node is no longer installed")

        for server in servers:
            protocols = server.get("protocols") or {}
            for protocol, record in protocols.items():
                if not isinstance(record, dict) or not record.get("installed"):
                    continue
                if str(protocol).split("__", 1)[0] not in _AWG_PROTOCOLS:
                    continue
                link = record.get("exit_link") or {}
                if link.get("exit_uid") != exit_uid or link.get("stale"):
                    continue
                return server, str(protocol)

        raise httpx.ConnectError(
            "Selected Telegram Exit Node has no active linked AmneziaWG instance"
        )

    def _post_via_exit(self, url, payload, timeout_seconds, exit_uid):
        data = self._load_data()
        server, protocol = self._find_entry(data, exit_uid)
        try:
            ssh = self._get_ssh(server)
            awg = self._awg_manager_factory(ssh)
            container_name = awg._container_name(protocol)
            source_ip = awg._get_subnet_ip(protocol)
            ipaddress.ip_address(source_ip)
        except Exception as exc:
            raise httpx.ConnectError(
                f"Cannot prepare selected Telegram Exit Node route: {exc}"
            ) from exc

        # Read the URL as the first stdin line. curl then receives the JSON body
        # from the remaining stdin, keeping the bot token out of process args
        # and SSH command logs.
        inner_script = (
            "IFS= read -r url || exit 64; "
            f"exec curl --interface {shlex.quote(source_ip)} "
            "--silent --show-error --connect-timeout 10 "
            f"--max-time {timeout_seconds} "
            "--request POST --header 'Content-Type: application/json' "
            f"--data-binary @- --write-out '\\n{_STATUS_MARKER}%{{http_code}}' \"$url\""
        )
        command = (
            f"docker exec -i {shlex.quote(container_name)} "
            f"sh -c {shlex.quote(inner_script)}"
        )
        stdin_payload = (
            url + "\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

        if getattr(ssh, "_is_root", False):
            remote_command = command
        elif getattr(ssh, "password", None):
            remote_command = "sudo -S -p '' " + command
            stdin_payload = str(ssh.password) + "\n" + stdin_payload
        else:
            remote_command = "sudo -n " + command

        out, err, code = ssh.run_command(
            remote_command,
            timeout=timeout_seconds + 20,
            stdin_input=stdin_payload,
        )
        if code != 0:
            detail = (err or out or f"remote curl exited with code {code}").strip()
            raise httpx.ConnectError(
                f"Telegram request through selected Exit Node failed: {detail}"
            )

        if _STATUS_MARKER not in out:
            raise httpx.ConnectError(
                "Telegram Exit Node returned no HTTP status; refusing direct fallback"
            )
        body, status_text = out.rsplit(_STATUS_MARKER, 1)
        try:
            status_code = int(status_text.strip().splitlines()[0])
        except (ValueError, IndexError):
            raise httpx.ConnectError("Invalid HTTP status from Telegram Exit Node")
        if status_code < 100:
            raise httpx.ConnectError("Telegram Exit Node did not establish an HTTPS response")

        return httpx.Response(
            status_code=status_code,
            content=body.encode("utf-8"),
            request=httpx.Request("POST", url),
        )
