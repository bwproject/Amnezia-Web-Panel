"""BW Exit Node manager with cleanup for legacy plain-WireGuard transit peers.

New links use only the upstream AmneziaWG transit interface. This class keeps
a narrow migration helper so peers created by older BW builds are removed
after their replacement AWG link has completed its handshake.
"""
import re

from managers.exit_manager import ExitManager


LEGACY_WG_CONFIG = "/opt/amnezia/exit/transitwg0.conf"
LEGACY_WG_INTERFACE = "transitwg0"


class BWExitManager(ExitManager):
    def remove_legacy_wireguard_peer(self, peer_id=None, public_key=None):
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.CONTAINER_NAME} cat {LEGACY_WG_CONFIG}"
        )
        if code != 0:
            return False
        head, marker, rest = out.partition("[Peer]")
        blocks = ["[Peer]\n" + chunk.strip() for chunk in rest.split("[Peer]") if chunk.strip()] if marker else []
        def block_id(block):
            match = re.search(r"^# peerId = (.+)$", block, re.M)
            return match.group(1).strip() if match else ""
        def block_key(block):
            match = re.search(r"^PublicKey\s*=\s*(.+)$", block, re.M)
            return match.group(1).strip() if match else ""
        kept = [
            block for block in blocks
            if not ((peer_id and block_id(block) == peer_id)
                    or (public_key and block_key(block) == public_key))
        ]
        if len(kept) == len(blocks):
            return False
        content = head.rstrip() + ("\n\n" + "\n\n".join(kept) if kept else "") + "\n"
        self.ssh.upload_file(content, "/tmp/bw-transitwg0-cleanup.conf")
        try:
            out, err, code = self.ssh.run_sudo_command(
                f"docker cp /tmp/bw-transitwg0-cleanup.conf {self.CONTAINER_NAME}:{LEGACY_WG_CONFIG} && "
                f"docker exec -i {self.CONTAINER_NAME} sh -c "
                f"'chmod 600 {LEGACY_WG_CONFIG}; wg-quick down {LEGACY_WG_CONFIG} >/dev/null 2>&1 || true; "
                f"wg-quick up {LEGACY_WG_CONFIG}'",
                timeout=45,
            )
            if code != 0:
                raise RuntimeError(err or out or "Could not reload legacy WireGuard transit peers")
        finally:
            self.ssh.run_command("rm -f /tmp/bw-transitwg0-cleanup.conf")
        return True
