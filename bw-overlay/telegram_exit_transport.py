"""Telegram Bot API transport through an existing AmneziaWG Exit Node.

Selected requests are executed by curl inside an already-linked AWG protocol
container. Binding curl to the instance gateway address invokes the same
source-policy route used by AWGManager.exit_check_egress(): table 200 -> exit0.
No host route, published port, proxy daemon, or VPN-client routing change is
required. If the selected route is unavailable, requests fail closed.
"""
import asyncio
import base64
import ipaddress
import json
import secrets
import shlex
import threading
from urllib.parse import urlencode, urlsplit

import httpx

from managers.awg_manager import AWGManager
from managers.ssh_manager import SSHManager


_AWG_PROTOCOLS = {"awg", "awg2", "awg3", "awg_legacy"}
_STATUS_MARKER = "__BW_TELEGRAM_HTTP_STATUS__:"


def _safe_multipart_header(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


class TelegramExitHTTPClient:
    """httpx-compatible client that uses the selected Exit Node or direct HTTP."""

    def __init__(self, load_data_fn):
        self._load_data = load_data_fn
        self._direct = httpx.AsyncClient()
        # A dedicated SSH connection keeps Telegram long-polling from holding
        # the panel's shared per-server SSH command lock for up to 35 seconds.
        self._ssh_lock = threading.RLock()
        self._ssh_key = None
        self._ssh_session = None

    async def __aenter__(self):
        await self._direct.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._direct.__aexit__(exc_type, exc, tb)
        with self._ssh_lock:
            if self._ssh_session is not None:
                try:
                    self._ssh_session.disconnect()
                except Exception:
                    pass
                self._ssh_session = None
                self._ssh_key = None

    async def post(self, url, json=None, timeout=30, **kwargs):
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or parsed.hostname != "api.telegram.org":
            raise httpx.UnsupportedProtocol(
                "Telegram Exit transport only allows https://api.telegram.org"
            )

        data = self._load_data()
        telegram_settings = ((data.get("settings") or {}).get("telegram") or {})
        exit_uid = str(telegram_settings.get("exit_uid") or "").strip()
        if not exit_uid:
            return await self._direct.post(url, json=json, timeout=timeout, **kwargs)

        body, content_type = self._encode_body(json, kwargs.get("data"), kwargs.get("files"), kwargs.get("content"))
        try:
            timeout_seconds = int(float(timeout))
        except (TypeError, ValueError):
            timeout_seconds = 30
        timeout_seconds = max(5, min(55, timeout_seconds))

        return await asyncio.to_thread(
            self._post_via_exit, str(url), body, content_type, timeout_seconds, exit_uid
        )

    @staticmethod
    def _encode_body(json_payload, data_payload, files_payload, content_payload):
        if files_payload:
            boundary = "----BWTelegram" + secrets.token_hex(16)
            boundary_bytes = boundary.encode("ascii")
            parts = []
            for field, value in (data_payload or {}).items():
                disposition = (
                    f'Content-Disposition: form-data; name="{_safe_multipart_header(field)}"\r\n\r\n'
                ).encode("utf-8")
                parts.extend((b"--" + boundary_bytes + b"\r\n", disposition,
                              str(value).encode("utf-8"), b"\r\n"))
            for field, spec in files_payload.items():
                if isinstance(spec, tuple):
                    filename = spec[0] if len(spec) > 0 else field
                    file_content = spec[1] if len(spec) > 1 else b""
                    mime_type = spec[2] if len(spec) > 2 and spec[2] else "application/octet-stream"
                else:
                    filename = field
                    file_content = spec.read() if hasattr(spec, "read") else spec
                    mime_type = "application/octet-stream"
                if isinstance(file_content, str):
                    file_content = file_content.encode("utf-8")
                file_header = (
                    f'Content-Disposition: form-data; name="{_safe_multipart_header(field)}"; '
                    f'filename="{_safe_multipart_header(filename)}"\r\n'
                    f"Content-Type: {_safe_multipart_header(mime_type)}\r\n\r\n"
                ).encode("utf-8")
                parts.extend((b"--" + boundary_bytes + b"\r\n", file_header,
                              bytes(file_content or b""), b"\r\n"))
            parts.append(b"--" + boundary_bytes + b"--\r\n")
            return b"".join(parts), f"multipart/form-data; boundary={boundary}"

        if content_payload is not None:
            if isinstance(content_payload, str):
                content_payload = content_payload.encode("utf-8")
            return bytes(content_payload), "application/octet-stream"

        if data_payload is not None:
            return urlencode(data_payload, doseq=True).encode("utf-8"), "application/x-www-form-urlencoded"

        payload = {} if json_payload is None else json_payload
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json"

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

    def _dedicated_ssh(self, server):
        key = (
            server.get("uid"), server.get("host"), int(server.get("ssh_port", 22)),
            server.get("username"), server.get("password"), server.get("private_key"),
        )
        with self._ssh_lock:
            if self._ssh_key != key:
                if self._ssh_session is not None:
                    try:
                        self._ssh_session.disconnect()
                    except Exception:
                        pass
                self._ssh_session = None
                self._ssh_key = key
            if self._ssh_session is None:
                self._ssh_session = SSHManager(
                    host=server["host"],
                    port=server.get("ssh_port", 22),
                    username=server["username"],
                    password=server.get("password"),
                    private_key=server.get("private_key"),
                    connect_cooldown_base=float(server.get("ssh_cooldown_base") or 30),
                )
                self._ssh_session.connect()
            else:
                self._ssh_session.ensure_connected()
            return self._ssh_session

    def _post_via_exit(self, url, body, content_type, timeout_seconds, exit_uid):
        data = self._load_data()
        server, protocol = self._find_entry(data, exit_uid)
        try:
            ssh = self._dedicated_ssh(server)
            awg = AWGManager(ssh)
            link_status = awg.exit_link_status(protocol)
            if not link_status or not link_status.get("up"):
                raise httpx.ConnectError(
                    "Selected AmneziaWG Exit Node tunnel has no recent handshake"
                )
            container_name = awg._container_name(protocol)
            source_ip = awg._get_subnet_ip(protocol)
            ipaddress.ip_address(source_ip)
        except Exception as exc:
            raise httpx.ConnectError(
                f"Cannot prepare selected Telegram Exit Node route: {exc}"
            ) from exc

        # URL, content type and body are passed through stdin, not process args.
        # Base64 keeps multipart file bytes safe through the SSH text channel.
        encoded_body = base64.b64encode(body).decode("ascii")
        inner_script = (
            "IFS= read -r url || exit 64; "
            "IFS= read -r content_type || exit 65; "
            "IFS= read -r payload_b64 || exit 66; "
            "umask 077; "
            "tmp_dir=$(mktemp -d /tmp/.bw-telegram.XXXXXX) || exit 68; "
            "cfg=\"$tmp_dir/request.cfg\"; body_file=\"$tmp_dir/request.body\"; "
            "trap 'rm -rf \"$tmp_dir\"' EXIT; "
            "printf '%s' \"$payload_b64\" | base64 -d > \"$body_file\" || exit 67; "
            "{ printf 'url = \"%s\"\\n' \"$url\"; "
            "printf 'request = \"POST\"\\n'; "
            "printf 'header = \"Content-Type: %s\"\\n' \"$content_type\"; "
            "printf 'data-binary = \"@%s\"\\n' \"$body_file\"; "
            "printf 'connect-timeout = 10\\n'; "
            f"printf 'max-time = {timeout_seconds}\\n'; "
            "printf 'silent\\nshow-error\\n'; } > \"$cfg\"; "
            f"curl --interface {shlex.quote(source_ip)} "
            f"--write-out '\\n{_STATUS_MARKER}%{{http_code}}' --config \"$cfg\""
        )
        command = (
            f"docker exec -i {shlex.quote(container_name)} "
            f"sh -c {shlex.quote(inner_script)}"
        )
        stdin_payload = f"{url}\n{content_type}\n{encoded_body}"

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
        response_body, status_text = out.rsplit(_STATUS_MARKER, 1)
        try:
            status_code = int(status_text.strip().splitlines()[0])
        except (ValueError, IndexError):
            raise httpx.ConnectError("Invalid HTTP status from Telegram Exit Node")
        if status_code < 100:
            raise httpx.ConnectError("Telegram Exit Node did not establish an HTTPS response")

        return httpx.Response(
            status_code=status_code,
            content=response_body.encode("utf-8"),
            request=httpx.Request("POST", url),
        )
