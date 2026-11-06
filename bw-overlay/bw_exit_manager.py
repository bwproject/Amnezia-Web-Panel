"""BW Exit Node extension: a second, plain WireGuard transit alongside AWG.

The original transit0 remains untouched (including AmneziaWG obfuscation).
Standard WireGuard entries use transitwg0 on UDP port transit_port + 1.
"""
import ipaddress
import re

from managers.exit_manager import ExitManager
from managers.awg_manager import generate_psk


class BWExitManager(ExitManager):
    WG_CONFIG_PATH = "/opt/amnezia/exit/transitwg0.conf"
    WG_PRIVATE_KEY_PATH = "/opt/amnezia/exit/transitwg_private.key"
    WG_PUBLIC_KEY_PATH = "/opt/amnezia/exit/transitwg_public.key"
    WG_SUBNET = ipaddress.ip_network("10.10.0.0/24")
    WG_INTERFACE = "transitwg0"

    @staticmethod
    def _wg_port(port):
        value = int(str(port or 55520).strip())
        if value < 1 or value > 65534:
            raise ValueError("Exit Node UDP port must be between 1 and 65534")
        return value + 1

    @staticmethod
    def _dockerfile_content(docker_image, userspace_patch):
        content = ExitManager._dockerfile_content(docker_image, userspace_patch)
        return content.replace(
            "bash curl dumb-init iptables iproute2 conntrack-tools",
            "bash curl dumb-init iptables iproute2 conntrack-tools wireguard-tools",
            1,
        )

    @staticmethod
    def _docker_run_cmd(container_name, image, port, ipv6_enabled):
        command = ExitManager._docker_run_cmd(container_name, image, port, ipv6_enabled)
        wg_port = BWExitManager._wg_port(port)
        return command.replace(
            f"-p {port}:{port}/udp",
            f"-p {port}:{port}/udp \\\n-p {wg_port}:{wg_port}/udp",
            1,
        )

    def _configure_exit_container(self, port, net, awg_params):
        # Keep the upstream AWG config and all existing transit0 peers intact.
        super()._configure_exit_container(port, net, awg_params)
        wg_port = self._wg_port(port)
        script = f"""
set -e
cd {self.CONFIG_DIR}
umask 077
[ -s transitwg_private.key ] || wg genkey > transitwg_private.key
wg pubkey < transitwg_private.key > transitwg_public.key
PEERS=""
if [ -f {self.WG_CONFIG_PATH} ]; then
  PEERS=$(awk "/^\\\\[Peer\\\\]/{{inside=1}} inside" {self.WG_CONFIG_PATH})
fi
cat > {self.WG_CONFIG_PATH} <<EOF
[Interface]
# Managed by Amnezia Web Panel BW - standard WireGuard transit
PrivateKey = $(cat transitwg_private.key)
Address = {self.WG_SUBNET.network_address + 1}/{self.WG_SUBNET.prefixlen}
ListenPort = {wg_port}
MTU = 1420
Table = off
EOF
if [ -n "$PEERS" ]; then
  printf "%s\\n" "$PEERS" >> {self.WG_CONFIG_PATH}
fi
"""
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.CONTAINER_NAME} sh -c '{script}'"
        )
        if code != 0:
            raise RuntimeError(f"Failed to configure standard WireGuard transit: {err or out}")

    def _render_start_script(self, protocol_type=None, config_path=None):
        script = super()._render_start_script(protocol_type, config_path)
        wg_start = f"""
# ---- BW standard WireGuard transit (separate from obfuscated transit0) ----
wg-quick down {self.WG_CONFIG_PATH} >/dev/null 2>&1 || true
wg-quick up {self.WG_CONFIG_PATH}
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
iptables -C FORWARD -i {self.WG_INTERFACE} -o eth0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i {self.WG_INTERFACE} -o eth0 -j ACCEPT
iptables -C FORWARD -i eth0 -o {self.WG_INTERFACE} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i eth0 -o {self.WG_INTERFACE} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -C POSTROUTING -s {self.WG_SUBNET} -o eth0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s {self.WG_SUBNET} -o eth0 -j MASQUERADE
iptables -t mangle -C FORWARD -i {self.WG_INTERFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -i {self.WG_INTERFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
iptables -t mangle -C FORWARD -o {self.WG_INTERFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -o {self.WG_INTERFACE} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
"""
        if "tail -f /dev/null" not in script:
            raise RuntimeError("Could not locate the upstream container keepalive in start.sh")
        return script.replace("tail -f /dev/null", wg_start + "\ntail -f /dev/null", 1)

    def install_protocol(self, protocol_type='exit', port=None, subnet=None,
                         obfuscation=False, **kwargs):
        result = super().install_protocol(
            protocol_type=protocol_type, port=port, subnet=subnet,
            obfuscation=obfuscation, **kwargs
        )
        if result.get("status") != "success":
            return result
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec {self.CONTAINER_NAME} wg show {self.WG_INTERFACE}"
        )
        if code != 0:
            raise RuntimeError(f"Standard WireGuard transit did not start: {err or out}")
        wg_info = self.get_wireguard_info(result.get("port") or port)
        result["wireguard"] = wg_info
        result["log"] = list(result.get("log") or []) + [
            f"Standard WireGuard transit enabled on UDP/{wg_info['port']} ({self.WG_INTERFACE})"
        ]
        return result

    def _read_wg_config(self):
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.CONTAINER_NAME} cat {self.WG_CONFIG_PATH}"
        )
        if code != 0:
            raise RuntimeError(f"Could not read standard WireGuard transit config: {err or out}")
        return out

    def _write_wg_config(self, content):
        self.ssh.upload_file(content, "/tmp/_bw_transitwg0.conf")
        out, err, code = self.ssh.run_sudo_command(
            f"docker cp /tmp/_bw_transitwg0.conf {self.CONTAINER_NAME}:{self.WG_CONFIG_PATH} "
            f"&& docker exec {self.CONTAINER_NAME} chmod 600 {self.WG_CONFIG_PATH}"
        )
        self.ssh.run_command("rm -f /tmp/_bw_transitwg0.conf")
        if code != 0:
            raise RuntimeError(f"Could not update standard WireGuard transit config: {err or out}")
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec {self.CONTAINER_NAME} sh -c "
            f"'wg-quick down {self.WG_CONFIG_PATH} >/dev/null 2>&1 || true; "
            f"wg-quick up {self.WG_CONFIG_PATH}'",
            timeout=30,
        )
        if code != 0:
            raise RuntimeError(f"Could not reload standard WireGuard transit: {err or out}")

    @staticmethod
    def _peer_blocks(config):
        head, marker, rest = config.partition("[Peer]")
        blocks = []
        if marker:
            blocks = ["[Peer]\n" + chunk.strip() for chunk in rest.split("[Peer]") if chunk.strip()]
        return head, blocks

    @staticmethod
    def _peer_id(block):
        match = re.search(r"^# peerId = (.+)$", block, re.M)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _peer_key(block):
        match = re.search(r"^PublicKey\s*=\s*(.+)$", block, re.M)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _peer_ip(block):
        match = re.search(r"^AllowedIPs\s*=\s*(\d+\.\d+\.\d+\.\d+)", block, re.M)
        return match.group(1) if match else ""

    def _next_wg_ip(self, blocks):
        used = {self._peer_ip(block) for block in blocks}
        for host in self.WG_SUBNET.hosts():
            value = str(host)
            if value != str(self.WG_SUBNET.network_address + 1) and value not in used:
                return value
        raise RuntimeError("No free addresses remain in the standard WireGuard transit subnet")

    def get_wireguard_info(self, base_port=None):
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.CONTAINER_NAME} cat {self.WG_PUBLIC_KEY_PATH}"
        )
        if code != 0:
            raise RuntimeError(f"Could not read standard WireGuard transit public key: {err or out}")
        if base_port is None:
            base_port = self._get_awg_params_from_config(self.PROTOCOL).get("port") or "55520"
        return {
            "public_key": out.strip(),
            "port": self._wg_port(base_port),
            "subnet": str(self.WG_SUBNET),
            "obfuscation": False,
            "awg_params": {},
        }

    def add_wireguard_peer(self, peer_id, name, public_key):
        peer_id, public_key = (peer_id or "").strip(), (public_key or "").strip()
        if not peer_id or not public_key:
            raise ValueError("peer_id and public_key are required")
        config = self._read_wg_config()
        head, blocks = self._peer_blocks(config)
        keep_ip = ""
        for block in list(blocks):
            if self._peer_id(block) == peer_id or self._peer_key(block) == public_key:
                keep_ip = keep_ip or self._peer_ip(block)
                blocks.remove(block)
        transit_ip = keep_ip or self._next_wg_ip(blocks)
        psk = generate_psk()
        blocks.append(
            "[Peer]\n"
            f"# peerId = {peer_id}\n"
            f"# clientName = {name or peer_id}\n"
            f"PublicKey = {public_key}\n"
            f"PresharedKey = {psk}\n"
            f"AllowedIPs = {transit_ip}/32"
        )
        blocks.sort(key=lambda block: ipaddress.ip_address(self._peer_ip(block) or "255.255.255.255"))
        self._write_wg_config(head.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n")
        base_port = self._get_awg_params_from_config(self.PROTOCOL).get("port") or "55520"
        info = self.get_wireguard_info(base_port)
        info.update({"transit_ip": transit_ip, "psk": psk})
        return info

    def list_peers(self):
        peers = super().list_peers()
        try:
            config = self._read_wg_config()
            _, blocks = self._peer_blocks(config)
            live_out, _, live_code = self.ssh.run_sudo_command(
                f"docker exec {self.CONTAINER_NAME} wg show {self.WG_INTERFACE} dump"
            )
            live = {}
            if live_code == 0:
                for row in live_out.splitlines()[1:]:
                    cols = row.split("\t")
                    if len(cols) >= 8:
                        live[cols[0]] = {"latestHandshake": cols[4], "dataReceived": cols[5],
                                         "dataSent": cols[6], "allowedIps": cols[3]}
            for block in blocks:
                key = self._peer_key(block)
                ip = self._peer_ip(block)
                stats = live.get(key, {})
                peers.append({
                    "peer_id": self._peer_id(block),
                    "name": re.search(r"^# clientName = (.+)$", block, re.M).group(1)
                            if re.search(r"^# clientName = (.+)$", block, re.M) else "WireGuard transit",
                    "transit_ip": ip,
                    "public_key": key,
                    "created_at": "",
                    "latest_handshake": stats.get("latestHandshake", ""),
                    "rx": stats.get("dataReceived", ""),
                    "tx": stats.get("dataSent", ""),
                    "rx_bytes": int(stats.get("dataReceived", 0) or 0),
                    "tx_bytes": int(stats.get("dataSent", 0) or 0),
                    "external": False,
                    "transport": "wireguard",
                })
        except Exception:
            pass
        return peers

    def remove_wireguard_peer(self, public_key=None, peer_id=None):
        config = self._read_wg_config()
        head, blocks = self._peer_blocks(config)
        kept = [
            block for block in blocks
            if not ((public_key and self._peer_key(block) == public_key)
                    or (peer_id and self._peer_id(block) == peer_id))
        ]
        if len(kept) == len(blocks):
            return False
        self._write_wg_config(head.rstrip() + ("\n\n" + "\n\n".join(kept) if kept else "") + "\n")
        return True
