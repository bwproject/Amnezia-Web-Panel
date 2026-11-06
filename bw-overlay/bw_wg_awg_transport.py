"""Standard WireGuard Exit Links carried by an existing AmneziaWG container."""
import ipaddress
import re
import shlex
import time

from managers.awg_manager import (
    AWGManager, TRANSIT_PARAM_KEYS, EXIT_MTU, EXIT_HANDSHAKE_UP_SECONDS,
    EXIT_CONF, EXIT_CONF_BACKUP, EXIT_IFACE, EXIT_TABLE,
)

HOST_SCRIPT = "/usr/local/sbin/bw-wg-awg-router"
HOST_ENV = "/etc/default/bw-wg-awg-router"
AWG_DIR = "/opt/amnezia/bw-wg-exit"
AWG_CONF = AWG_DIR + "/bwexit0.conf"
AWG_KEY = AWG_DIR + "/exit_private.key"
AWG_BACKUP = AWG_CONF + ".failover-bak"
AWG_IFACE = "bwexit0"
WG_CONTAINER = "amnezia-wireguard"
WG_CONFIG = "/opt/amnezia/wireguard/wg0.conf"
WG_IFACE = "wg0"
TABLE = 201
PRIORITY = 120

ROUTER = r"""#!/bin/sh
set -eu
[ -r /etc/default/bw-wg-awg-router ] || exit 0
. /etc/default/bw-wg-awg-router
if [ "${ENABLED:-0}" != 1 ]; then
  docker exec "$WG_CONTAINER" sh -c "ip rule del pref 120 from '$WG_SUBNET' table 201 2>/dev/null || true; ip route flush table 201 2>/dev/null || true" >/dev/null 2>&1 || true
  docker exec "$AWG_CONTAINER" sh -c "ip rule del pref 120 from '$WG_SUBNET' table 201 2>/dev/null || true; ip route flush table 201 2>/dev/null || true; ip route del '$WG_SUBNET' 2>/dev/null || true; iptables -D FORWARD -i eth0 -o bwexit0 -s '$WG_SUBNET' -j ACCEPT 2>/dev/null || true; iptables -D FORWARD -i bwexit0 -o eth0 -d '$WG_SUBNET' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true; iptables -t nat -D POSTROUTING -s '$WG_SUBNET' -o bwexit0 -j MASQUERADE 2>/dev/null || true; awg-quick down '$AWG_CONF' >/dev/null 2>&1 || true" >/dev/null 2>&1 || true
  exit 0
fi
docker network connect bridge "$WG_CONTAINER" >/dev/null 2>&1 || true
docker network connect bridge "$AWG_CONTAINER" >/dev/null 2>&1 || true
WG_RUNNING=$(docker inspect -f '{{.State.Running}}' "$WG_CONTAINER" 2>/dev/null || echo false)
AWG_RUNNING=$(docker inspect -f '{{.State.Running}}' "$AWG_CONTAINER" 2>/dev/null || echo false)
[ "$WG_RUNNING" = true ] || exit 0
# Install a blackhole first: if AWG is stopped or its tunnel cannot start,
# standard WireGuard clients never fall back to the entry server's WAN.
docker exec "$WG_CONTAINER" sh -c "ip route show table 201 | grep -q '^default ' || ip route replace blackhole default table 201; ip -4 rule show | grep -Fq 'from $WG_SUBNET lookup 201' || ip -4 rule add pref 120 from '$WG_SUBNET' table 201" || exit 1
[ "$AWG_RUNNING" = true ] || exit 0
WG_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "bridge").IPAddress}}' "$WG_CONTAINER" 2>/dev/null || true)
AWG_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "bridge").IPAddress}}' "$AWG_CONTAINER" 2>/dev/null || true)
[ -n "$WG_IP" ] && [ -n "$AWG_IP" ] || exit 0
docker exec "$AWG_CONTAINER" sh -c "ip route show table 201 | grep -q '^default ' || ip route replace blackhole default table 201; ip -4 rule show | grep -Fq 'from $WG_SUBNET lookup 201' || ip -4 rule add pref 120 from '$WG_SUBNET' table 201" || exit 1
if [ "$AWG_PROTOCOL" = "awg3" ]; then
  docker exec "$AWG_CONTAINER" sh -c "if ip link add awgprobe type amneziawg 2>/dev/null; then KMOD_VERSION=\$(cat /sys/module/amneziawg/version 2>/dev/null); ip link delete awgprobe 2>/dev/null; case \"\$KMOD_VERSION\" in 3.*|[4-9].*|[1-9][0-9].*) ;; *) export WG_FORCE_USERSPACE=1 ;; esac; fi; ip link show bwexit0 >/dev/null 2>&1 || awg-quick up '$AWG_CONF'" || exit 0
else
  docker exec "$AWG_CONTAINER" sh -c "ip link show bwexit0 >/dev/null 2>&1 || awg-quick up '$AWG_CONF'" || exit 0
fi
WG_DEV=$(docker exec "$WG_CONTAINER" sh -c "ip route get '$AWG_IP' | awk '{for(i=1;i<=NF;i++) if(\$i==\"dev\"){print \$(i+1); exit}}'" 2>/dev/null || true)
AWG_DEV=$(docker exec "$AWG_CONTAINER" sh -c "ip route get '$WG_IP' | awk '{for(i=1;i<=NF;i++) if(\$i==\"dev\"){print \$(i+1); exit}}'" 2>/dev/null || true)
[ -n "$WG_DEV" ] || WG_DEV=eth0
[ -n "$AWG_DEV" ] || AWG_DEV=eth0
docker exec "$WG_CONTAINER" sh -c "sysctl -w net.ipv4.ip_forward=1 >/dev/null; ip route replace default via '$AWG_IP' dev '$WG_DEV' table 201; iptables -C FORWARD -i wg0 -o '$WG_DEV' -s '$WG_SUBNET' -j ACCEPT 2>/dev/null || iptables -A FORWARD -i wg0 -o '$WG_DEV' -s '$WG_SUBNET' -j ACCEPT; iptables -C FORWARD -i '$WG_DEV' -o wg0 -d '$WG_SUBNET' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i '$WG_DEV' -o wg0 -d '$WG_SUBNET' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" || exit 1
if [ "${DNS_VIA_EXIT:-0}" != 1 ]; then
  docker exec "$WG_CONTAINER" sh -c "ip route replace throw 172.29.172.0/24 table 201" >/dev/null 2>&1 || true
else
  docker exec "$WG_CONTAINER" sh -c "ip route del throw 172.29.172.0/24 table 201 2>/dev/null || true" >/dev/null 2>&1 || true
fi
docker exec "$AWG_CONTAINER" sh -c "sysctl -w net.ipv4.ip_forward=1 >/dev/null; sysctl -w net.ipv4.conf.bwexit0.rp_filter=2 >/dev/null 2>&1 || true; ip route replace '$WG_SUBNET' via '$WG_IP' dev '$AWG_DEV'; ip route replace default dev bwexit0 table 201; iptables -C FORWARD -i '$AWG_DEV' -o bwexit0 -s '$WG_SUBNET' -j ACCEPT 2>/dev/null || iptables -A FORWARD -i '$AWG_DEV' -o bwexit0 -s '$WG_SUBNET' -j ACCEPT; iptables -C FORWARD -i bwexit0 -o '$AWG_DEV' -d '$WG_SUBNET' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i bwexit0 -o '$AWG_DEV' -d '$WG_SUBNET' -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -C POSTROUTING -s '$WG_SUBNET' -o bwexit0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s '$WG_SUBNET' -o bwexit0 -j MASQUERADE; iptables -t mangle -C FORWARD -i '$AWG_DEV' -o bwexit0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -i '$AWG_DEV' -o bwexit0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu; iptables -t mangle -C FORWARD -i bwexit0 -o '$AWG_DEV' -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -i bwexit0 -o '$AWG_DEV' -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu" || exit 1
"""

class BWAWGWireGuardTransport:
    def __init__(self, ssh):
        self.ssh = ssh
        self.awg = AWGManager(ssh)
        self.protocol = ""
        self.container = ""
        self.wg_bin = "awg"
        self.quick_bin = "awg-quick"
        self._select_container()

    def _run(self, command, timeout=60):
        out, err, code = self.ssh.run_sudo_command(command, timeout=timeout)
        if code:
            raise RuntimeError((err or out or f"SSH command failed ({code})").strip())
        return out

    def _select_container(self):
        out, err, code = self.ssh.run_sudo_command("docker ps -a --format '{{.Names}}'")
        if code:
            raise RuntimeError("Could not inspect Docker containers on the entry server")
        installed = set(out.splitlines())
        out, _, _ = self.ssh.run_sudo_command("docker ps --format '{{.Names}}'")
        running = set(out.splitlines())
        for proto in ("awg3", "awg2", "awg", "awg__3", "awg__2"):
            name = self.awg._container_name(proto)
            if name not in installed:
                continue
            if name not in running:
                self._run(f"docker start {shlex.quote(name)}")
            self.protocol, self.container = proto, name
            self.wg_bin = self.awg._wg_binary(proto)
            self.quick_bin = self.awg._quick_binary(proto)
            return
        raise RuntimeError(
            "To link standard WireGuard, this entry server must already have a running "
            "AmneziaWG container. Install/start AWG first; BW will not create a second VPN."
        )

    def _wg_config(self):
        out = self._run(f"docker exec -i {WG_CONTAINER} cat {WG_CONFIG}")
        return out

    def _wg_network(self):
        for line in self._wg_config().splitlines():
            if line.strip().startswith("Address") and "=" in line:
                value = line.split("=", 1)[1].strip().split(",", 1)[0].strip()
                interface = ipaddress.ip_interface(value)
                return str(interface.network), str(interface.ip)
        raise RuntimeError("Could not read the standard WireGuard client subnet")

    def _host_env(self, enabled, dns_via_exit=False):
        subnet, _ = self._wg_network()
        values = {
            "ENABLED": "1" if enabled else "0",
            "WG_CONTAINER": WG_CONTAINER,
            "AWG_CONTAINER": self.container,
            "AWG_PROTOCOL": self.awg._base_protocol(self.protocol),
            "WG_SUBNET": subnet,
            "AWG_CONF": AWG_CONF,
            "DNS_VIA_EXIT": "1" if dns_via_exit else "0",
        }
        return "".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items())

    def _install_router(self, enabled=True, dns_via_exit=False):
        _, _, code = self.ssh.run_sudo_command("command -v systemctl >/dev/null 2>&1")
        if code:
            raise RuntimeError("Automatic WireGuard/AWG routing requires systemd on the entry server")
        service = "[Unit]\nDescription=BW WireGuard via AmneziaWG router\nAfter=docker.service\nRequires=docker.service\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/bw-wg-awg-router\n"
        timer = "[Unit]\nDescription=Keep BW WireGuard/AWG routes active\n[Timer]\nOnBootSec=10s\nOnUnitActiveSec=5s\nAccuracySec=1s\nPersistent=true\nUnit=bw-wg-awg-router.service\n[Install]\nWantedBy=timers.target\n"
        for content, path in (
            (ROUTER, "/tmp/bw-wg-awg-router"),
            (self._host_env(enabled, dns_via_exit), "/tmp/bw-wg-awg-router.env"),
            (service, "/tmp/bw-wg-awg-router.service"),
            (timer, "/tmp/bw-wg-awg-router.timer"),
        ):
            self.ssh.upload_file(content, path)
        command = (
            f"install -m 0755 /tmp/bw-wg-awg-router {HOST_SCRIPT} && "
            f"install -m 0600 /tmp/bw-wg-awg-router.env {HOST_ENV} && "
            "install -m 0644 /tmp/bw-wg-awg-router.service /etc/systemd/system/bw-wg-awg-router.service && "
            "install -m 0644 /tmp/bw-wg-awg-router.timer /etc/systemd/system/bw-wg-awg-router.timer && "
            "systemctl daemon-reload && "
            + ("systemctl enable --now bw-wg-awg-router.timer && systemctl start bw-wg-awg-router.service"
               if enabled else "systemctl start bw-wg-awg-router.service && { systemctl disable --now bw-wg-awg-router.timer >/dev/null 2>&1 || true; }")
        )
        self._run(command, timeout=60)
        self.ssh.run_command("rm -f /tmp/bw-wg-awg-router*")
        return "systemd WireGuard/AWG routing service installed and synchronized"

    def exit_prepare_keys(self, protocol_type):
        out = self._run(
            f"docker exec -i {self.container} sh -c 'umask 077; mkdir -p {AWG_DIR}; "
            f"[ -s {AWG_KEY} ] || {self.wg_bin} genkey > {AWG_KEY}; {self.wg_bin} pubkey < {AWG_KEY}'"
        )
        if not out.strip():
            raise RuntimeError("Could not generate the AWG transport public key")
        return out.strip()

    @staticmethod
    def _config(link):
        lines = [
            "[Interface]",
            "# Managed by Amnezia Web Panel BW - standard WireGuard transport",
            f"# ExitUid = {link.get('exit_uid', '')}",
            f"# ExitName = {link.get('exit_name', '')}",
            f"# DnsViaExit = {'on' if link.get('dns_via_exit') else 'off'}",
            "PrivateKey = __BW_PRIVATE_KEY__",
            f"Address = {link['transit_ip']}/{link.get('subnet_cidr', 24)}",
            f"MTU = {min(int(link.get('mtu') or EXIT_MTU), EXIT_MTU)}",
            "Table = off",
        ]
        if link.get("obfuscation"):
            params = link.get("awg_params") or {}
            lines.extend(
                f"{dst} = {params[src]}" for src, dst in TRANSIT_PARAM_KEYS
                if params.get(src) is not None and str(params.get(src)).strip()
            )
        lines.extend([
            "", "[Peer]", f"PublicKey = {link['exit_public_key']}",
            f"PresharedKey = {link['psk']}", "AllowedIPs = 0.0.0.0/0",
            f"Endpoint = {link['endpoint_host']}:{link['endpoint_port']}",
            "PersistentKeepalive = 25", "",
        ])
        return "\n".join(lines)

    def _write_config(self, link):
        self.ssh.upload_file(self._config(link), "/tmp/bw-wg-awg-exit.conf")
        try:
            self._run(
                f"docker exec -i {self.container} mkdir -p {AWG_DIR} && "
                f"docker cp /tmp/bw-wg-awg-exit.conf {self.container}:{AWG_CONF} && "
                f"docker exec -i {self.container} sh -c 'k=$(cat {AWG_KEY}) && "
                f"sed -i \"s|__BW_PRIVATE_KEY__|$k|\" {AWG_CONF} && chmod 600 {AWG_CONF}'"
            )
        finally:
            self.ssh.run_command("rm -f /tmp/bw-wg-awg-exit.conf")

    def _apply(self, dns_via_exit=False):
        self._run(
            f"docker exec -i {self.container} sh -c '{self.quick_bin} down {AWG_CONF} >/dev/null 2>&1 || true; "
            f"{self.quick_bin} up {AWG_CONF}'", timeout=60
        )
        self._install_router(True, dns_via_exit)
        return "AWG transport up; standard WireGuard client traffic is routed through the existing AWG container"

    def _cleanup_legacy_wg_exit(self):
        """Remove the previous BW plain-WireGuard exit0 route after migration."""
        subnet, _ = self._wg_network()
        command = (
            f"docker exec -i {WG_CONTAINER} sh -c '"
            f"wg-quick down {EXIT_CONF} >/dev/null 2>&1 || true; "
            f"ip link del {EXIT_IFACE} 2>/dev/null || true; "
            f"for p in 190 191 {EXIT_TABLE}; do "
            f"while ip -4 rule del pref $p 2>/dev/null; do :; done; "
            f"while ip -6 rule del pref $p 2>/dev/null; do :; done; done; "
            f"ip -4 route flush table {EXIT_TABLE} 2>/dev/null || true; "
            f"ip -6 route flush table {EXIT_TABLE} 2>/dev/null || true; "
            f"while iptables -D FORWARD -i wg0 -o {EXIT_IFACE} -s {subnet} -j ACCEPT 2>/dev/null; do :; done; "
            f"while iptables -t nat -D POSTROUTING -s {subnet} -o {EXIT_IFACE} -j MASQUERADE 2>/dev/null; do :; done; "
            f"while iptables -t mangle -D FORWARD -o {EXIT_IFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null; do :; done; "
            f"while iptables -t mangle -D FORWARD -i {EXIT_IFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null; do :; done; "
            f"rm -f {EXIT_CONF} {EXIT_CONF_BACKUP}'"
        )
        self._run(command)

    def exit_link(self, protocol_type, link):
        self._write_config(link)
        return self._apply(bool(link.get("dns_via_exit")))

    def exit_cleanup_legacy(self):
        # Called only after the replacement AWG peer has completed handshake.
        return self._cleanup_legacy_wg_exit()

    def exit_unlink(self, protocol_type):
        self._install_router(False, False)
        self._run(
            f"docker exec -i {self.container} sh -c '{self.quick_bin} down {AWG_CONF} >/dev/null 2>&1 || true; rm -f {AWG_CONF}'"
        )
        self._cleanup_legacy_wg_exit()
        return "Standard WireGuard Exit Link removed"

    def exit_backup_conf(self, protocol_type):
        self._run(f"docker exec -i {self.container} sh -c 'test -f {AWG_CONF} && cp -p {AWG_CONF} {AWG_BACKUP}'")
        return True

    def exit_restore_conf(self, protocol_type):
        self._run(f"docker exec -i {self.container} sh -c 'test -f {AWG_BACKUP} && cp -p {AWG_BACKUP} {AWG_CONF}'")
        out = self._run(f"docker exec -i {self.container} cat {AWG_CONF}")
        return self._apply("# DnsViaExit = on" in out)

    def exit_set_dns_via_exit(self, protocol_type, enabled):
        value = "on" if enabled else "off"
        self._run(
            f"docker exec -i {self.container} sh -c 'test -f {AWG_CONF} && "
            f"sed -i \"s|^# DnsViaExit = .*|# DnsViaExit = {value}|\" {AWG_CONF}'"
        )
        self._install_router(True, bool(enabled))
        return "DNS traffic is routed " + ("through the Exit Node" if enabled else "through the entry server")

    def exit_link_info(self, protocol_type):
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.container} sh -c 'test -f {AWG_CONF} && "
            f"grep -E \"^# (ExitUid|ExitName|DnsViaExit) =|^Address|^Endpoint\" {AWG_CONF}'"
        )
        if code:
            return None
        info = {}
        for line in out.splitlines():
            line = line.strip().lstrip("#").strip()
            if "=" in line:
                k, _, v = line.partition("=")
                info[k.strip()] = v.strip()
        return {
            "exit_uid": info.get("ExitUid", ""),
            "exit_name": info.get("ExitName", ""),
            "dns_via_exit": info.get("DnsViaExit") == "on",
            "address": info.get("Address", ""),
            "endpoint": info.get("Endpoint", ""),
        }

    def exit_link_status(self, protocol_type, now=None):
        command = (
            f"docker exec -i {self.container} sh -c 'test -f {AWG_CONF} || exit 9; "
            f"{self.wg_bin} show {AWG_IFACE} latest-handshakes; echo ---; "
            f"{self.wg_bin} show {AWG_IFACE} transfer; echo ---; "
            f"{self.wg_bin} show {AWG_IFACE} endpoints'"
        )
        out, err, code = self.ssh.run_sudo_command(command)
        if code == 9:
            return None
        if code:
            return {"up": False, "handshake_age": None, "rx_bytes": 0, "tx_bytes": 0, "endpoint": "", "error": (err or out).strip()}
        peers = AWGManager._parse_wg_peer_lists(out)
        peer = next(iter(peers.values()), {})
        handshake = peer.get("latest_handshake", 0)
        age = int((now or time.time()) - handshake) if handshake else None
        return {
            "up": age is not None and 0 <= age < EXIT_HANDSHAKE_UP_SECONDS,
            "handshake_age": age,
            "rx_bytes": peer.get("rx_bytes", 0),
            "tx_bytes": peer.get("tx_bytes", 0),
            "endpoint": peer.get("endpoint", ""),
        }

    def exit_check_egress(self, protocol_type):
        _, gateway = self._wg_network()
        script = (
            "x_ip() { for u in https://api.ipify.org https://ifconfig.me/ip; do "
            "r=$(curl -fsS -4 --max-time 8 \"$@\" \"$u\" 2>/dev/null | tr -d '[:space:]'); "
            "case \"$r\" in ''|*[!0-9.]*) ;; *) echo \"$r\"; return 0;; esac; done; echo ''; }; "
            f"x_ip --interface {gateway}; echo ---; x_ip"
        )
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {WG_CONTAINER} sh -c {shlex.quote(script)}", timeout=40
        )
        if code:
            raise RuntimeError(f"WireGuard egress probe failed: {err or out}")
        via, _, direct = out.partition("---")
        valid = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
        def first(value):
            return next((line.strip() for line in value.splitlines() if valid.match(line.strip())), "")
        return {"via_exit": first(via), "direct": first(direct)}
