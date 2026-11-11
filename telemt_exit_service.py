"""Route one Telemt container through an already-linked AWG Exit Node."""
import shlex
from managers.awg_manager import AWGManager

HOST_SCRIPT = "/usr/local/sbin/bw-telemt-awg-route"
ROUTER = r"""#!/bin/sh
set -eu
[ -r /etc/default/bw-telemt-awg-route ] || exit 0
. /etc/default/bw-telemt-awg-route
remove_rules() {
  ip -4 rule del pref 124 2>/dev/null || true
  ip -4 route flush table 203 2>/dev/null || true
  if [ -n "${TELEMT_IP:-}" ]; then
    docker exec "$AWG_CONTAINER" sh -c "
      ip -4 rule del pref 124 2>/dev/null || true
      iptables -D FORWARD -i '$TELEMT_DEV' -o exit0 -s '$TELEMT_IP/32' -j ACCEPT 2>/dev/null || true
      iptables -D FORWARD -i exit0 -o '$TELEMT_DEV' -d '$TELEMT_IP/32' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
      iptables -t nat -D POSTROUTING -s '$TELEMT_IP/32' -o exit0 -j MASQUERADE 2>/dev/null || true
    " >/dev/null 2>&1 || true
  fi
}
TELEMT_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "bridge").IPAddress}}' "$TELEMT_CONTAINER" 2>/dev/null || echo "${TELEMT_IP_SAVED:-}")
AWG_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "bridge").IPAddress}}' "$AWG_CONTAINER" 2>/dev/null || true)
TELEMT_ROUTE=$(docker exec "$AWG_CONTAINER" ip route get "$TELEMT_IP" 2>/dev/null || true)
TELEMT_DEV=$(printf '%s\n' "$TELEMT_ROUTE" | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
if [ "${ENABLED:-0}" != 1 ]; then remove_rules; exit 0; fi
TELEMT_RUNNING=$(docker inspect -f '{{.State.Running}}' "$TELEMT_CONTAINER" 2>/dev/null || echo false)
if [ "$TELEMT_RUNNING" != true ]; then remove_rules; exit 0; fi
[ -n "$TELEMT_IP" ] && [ -n "$AWG_IP" ] || exit 0
HOST_DEV=$(ip route get "$AWG_IP" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
[ -n "$HOST_DEV" ] && [ -n "$TELEMT_DEV" ] || exit 0
# A blackhole remains in place unless the selected AWG tunnel is ready.
ip -4 rule del pref 124 2>/dev/null || true
ip -4 route replace blackhole default table 203
ip -4 rule add pref 124 from "$TELEMT_IP/32" table 203
if ! docker exec "$AWG_CONTAINER" ip link show exit0 >/dev/null 2>&1; then exit 0; fi
docker exec "$AWG_CONTAINER" sh -c "
  ip -4 rule del pref 124 2>/dev/null || true
  ip -4 rule add pref 124 from '$TELEMT_IP/32' table 204
  ip -4 route replace default dev exit0 table 204
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
  sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null 2>&1 || true
  iptables -C FORWARD -i '$TELEMT_DEV' -o exit0 -s '$TELEMT_IP/32' -j ACCEPT 2>/dev/null || iptables -A FORWARD -i '$TELEMT_DEV' -o exit0 -s '$TELEMT_IP/32' -j ACCEPT
  iptables -C FORWARD -i exit0 -o '$TELEMT_DEV' -d '$TELEMT_IP/32' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i exit0 -o '$TELEMT_DEV' -d '$TELEMT_IP/32' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  iptables -t nat -C POSTROUTING -s '$TELEMT_IP/32' -o exit0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s '$TELEMT_IP/32' -o exit0 -j MASQUERADE
" || exit 1
ip -4 route replace default via "$AWG_IP" dev "$HOST_DEV" table 203
"""

class TelemtExitService:
    def __init__(self, get_ssh):
        self.get_ssh = get_ssh

    @staticmethod
    def _base(protocol):
        return str(protocol or "").split("__", 1)[0]

    @staticmethod
    def _telemt_container(protocol):
        parts = str(protocol or "telemt").split("__", 1)
        try:
            index = max(1, int(parts[1])) if len(parts) == 2 else 1
        except ValueError:
            index = 1
        return "telemt" if index == 1 else f"telemt-{index}"

    def _run(self, ssh, command, timeout=60):
        out, err, code = ssh.run_sudo_command(command, timeout=timeout)
        if code:
            raise RuntimeError((err or out or f"command failed ({code})").strip())
        return out

    def _install_router(self, ssh, telemt_container, awg_container, enabled, telemt_ip=""):
        env = (
            f"ENABLED={'1' if enabled else '0'}\n"
            f"TELEMT_CONTAINER={shlex.quote(telemt_container)}\n"
            f"AWG_CONTAINER={shlex.quote(awg_container)}\n"
            f"TELEMT_IP_SAVED={shlex.quote(telemt_ip)}\n"
        )
        service = (
            "[Unit]\nDescription=BW Telemt via existing AWG Exit Node\n"
            "After=docker.service\nRequires=docker.service\n"
            "[Service]\nType=oneshot\nExecStart=/usr/local/sbin/bw-telemt-awg-route\n"
        )
        timer = (
            "[Unit]\nDescription=Keep Telemt AWG Exit route synchronized\n"
            "[Timer]\nOnBootSec=12s\nOnUnitActiveSec=5s\nAccuracySec=1s\n"
            "Persistent=true\nUnit=bw-telemt-awg-route.service\n"
            "[Install]\nWantedBy=timers.target\n"
        )
        for body, path in (
            (ROUTER, "/tmp/bw-telemt-awg-route"),
            (env, "/tmp/bw-telemt-awg-route.env"),
            (service, "/tmp/bw-telemt-awg-route.service"),
            (timer, "/tmp/bw-telemt-awg-route.timer"),
        ):
            ssh.upload_file(body, path)
        self._run(
            ssh,
            "install -m 0755 /tmp/bw-telemt-awg-route /usr/local/sbin/bw-telemt-awg-route && "
            "install -m 0600 /tmp/bw-telemt-awg-route.env /etc/default/bw-telemt-awg-route && "
            "install -m 0644 /tmp/bw-telemt-awg-route.service /etc/systemd/system/bw-telemt-awg-route.service && "
            "install -m 0644 /tmp/bw-telemt-awg-route.timer /etc/systemd/system/bw-telemt-awg-route.timer && "
            "systemctl daemon-reload && systemctl enable --now bw-telemt-awg-route.timer && "
            "systemctl start bw-telemt-awg-route.service && rm -f /tmp/bw-telemt-awg-route*",
            timeout=90,
        )

    def link(self, server, telemt_protocol, awg_protocol):
        telemt_protocol = str(telemt_protocol or "telemt")
        awg_protocol = str(awg_protocol or "")
        if self._base(telemt_protocol) != "telemt":
            raise ValueError("Selected protocol is not Telemt")
        if self._base(awg_protocol) not in {"awg", "awg2", "awg3", "awg_legacy"}:
            raise ValueError("Choose an AmneziaWG instance")
        protocols = server.get("protocols") or {}
        telemt_record = protocols.get(telemt_protocol) or {}
        awg_record = protocols.get(awg_protocol) or {}
        if not telemt_record.get("installed"):
            raise ValueError("Telemt is not installed on this server")
        link = awg_record.get("exit_link") or {}
        if not awg_record.get("installed") or not link.get("exit_uid") or link.get("stale"):
            raise ValueError("Selected AmneziaWG instance must have an active Exit Node link")
        if not server.get("uid"):
            raise ValueError("Server uid is missing; refresh the panel")
        ssh = self.get_ssh(server)
        try:
            ssh.connect()
            awg = AWGManager(ssh)
            telemt_container = self._telemt_container(telemt_protocol)
            awg_container = awg._container_name(awg_protocol)
            self._run(ssh, f"docker network connect bridge {shlex.quote(telemt_container)} >/dev/null 2>&1 || true")
            self._run(ssh, f"docker network connect bridge {shlex.quote(awg_container)} >/dev/null 2>&1 || true")
            self._run(ssh, f"docker inspect {shlex.quote(telemt_container)} >/dev/null")
            self._run(ssh, f"docker inspect {shlex.quote(awg_container)} >/dev/null")
            telemt_ip = self._run(
                ssh, f"docker inspect -f '{{{{(index .NetworkSettings.Networks \"bridge\").IPAddress}}}}' {shlex.quote(telemt_container)}"
            ).strip()
            awg_ip = self._run(
                ssh, f"docker inspect -f '{{{{(index .NetworkSettings.Networks \"bridge\").IPAddress}}}}' {shlex.quote(awg_container)}"
            ).strip()
            if not telemt_ip or not awg_ip:
                raise RuntimeError("Could not attach Telemt and AWG containers to Docker bridge networking")
            self._run(ssh, f"docker exec {shlex.quote(awg_container)} ip link show exit0 >/dev/null")
            self._install_router(ssh, telemt_container, awg_container, True, telemt_ip)
        finally:
            ssh.disconnect()
        return {
            "enabled": True, "awg_protocol": awg_protocol,
            "exit_uid": link.get("exit_uid"),
            "exit_name": link.get("exit_name") or "",
            "telemt_container": telemt_container,
            "awg_container": awg_container,
            "telemt_ip": telemt_ip,
        }

    def unlink(self, server, telemt_protocol):
        telemt_protocol = str(telemt_protocol or "telemt")
        if self._base(telemt_protocol) != "telemt":
            raise ValueError("Selected protocol is not Telemt")
        saved = ((server.get("protocols") or {}).get(telemt_protocol) or {}).get("telemt_exit") or {}
        if not saved.get("enabled"):
            return {"enabled": False}
        ssh = self.get_ssh(server)
        try:
            ssh.connect()
            self._install_router(
                ssh, saved.get("telemt_container") or self._telemt_container(telemt_protocol),
                saved.get("awg_container") or "amnezia-awg", False,
                saved.get("telemt_ip") or "",
            )
        finally:
            ssh.disconnect()
        return {"enabled": False}
