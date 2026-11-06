"""Standard WireGuard adapter for the shared ExitLinkService.

Uses the same isolated exit0 interface, source-policy routing, kill-switch,
NAT and health probes as AmneziaWG, but targets the standard WireGuard
container and wg/wg-quick binaries. No AmneziaWG settings are changed.
"""
from managers.awg_manager import AWGManager
from managers.wireguard_manager import WireGuardManager


class WireGuardExitManager(WireGuardManager, AWGManager):
    """WireGuard client server with AWGManager's protocol-neutral exit link."""

    def _base_protocol(self, protocol_type=None):
        return 'wireguard'

    def _instance_index(self, protocol_type=None):
        return 1

    def _container_name(self, protocol_type=None):
        return self.CONTAINER_NAME

    def _config_path(self, protocol_type=None):
        return self.CONFIG_PATH

    def _config_path_candidates(self, protocol_type=None):
        return [self.CONFIG_PATH]

    def _resolve_config_path(self, protocol_type=None):
        return self.CONFIG_PATH

    def _wg_binary(self, protocol_type=None):
        return 'wg'

    def _quick_binary(self, protocol_type=None):
        return 'wg-quick'

    def _interface_name(self, protocol_type=None, config_path=None):
        return self.INTERFACE

    def _userspace_guard(self, protocol_type=None):
        return ''

    def _bwlimits_path(self):
        return self.BWLIMITS_PATH

    def _get_server_config(self, protocol_type=None):
        out, err, code = self.ssh.run_sudo_command(
            f"docker exec -i {self.CONTAINER_NAME} cat {self.CONFIG_PATH}"
        )
        if code != 0:
            raise RuntimeError(f"Failed to get WireGuard server config: {err or out}")
        return out
