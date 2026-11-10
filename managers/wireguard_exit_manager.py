"""WireGuard server adapter: keep wg0 unchanged and use existing AWG for Exit Links."""
from managers.wireguard_manager import WireGuardManager
from bw_wg_awg_transport import BWAWGWireGuardTransport


class WireGuardExitManager(WireGuardManager):
    def __init__(self, ssh_manager):
        super().__init__(ssh_manager)
        self.awg_transport = BWAWGWireGuardTransport(ssh_manager)

    def _get_mtu(self, protocol_type=None):
        for line in self._get_server_config().splitlines():
            if line.strip().startswith("MTU") and "=" in line:
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
        return 1420

    def _get_subnet_ipv6_ip(self, protocol_type=None):
        import ipaddress
        for line in self._get_server_config().splitlines():
            if line.strip().startswith("Address") and "=" in line:
                for value in line.split("=", 1)[1].split(","):
                    value = value.strip()
                    if ":" in value:
                        return str(ipaddress.ip_interface(value).ip)
        return ""

    def exit_prepare_keys(self, protocol_type):
        return self.awg_transport.exit_prepare_keys(protocol_type)

    def exit_link(self, protocol_type, link):
        return self.awg_transport.exit_link(protocol_type, link)

    def exit_unlink(self, protocol_type):
        return self.awg_transport.exit_unlink(protocol_type)

    def exit_backup_conf(self, protocol_type):
        return self.awg_transport.exit_backup_conf(protocol_type)

    def exit_restore_conf(self, protocol_type):
        return self.awg_transport.exit_restore_conf(protocol_type)

    def exit_set_dns_via_exit(self, protocol_type, enabled):
        return self.awg_transport.exit_set_dns_via_exit(protocol_type, enabled)

    def exit_set_smart_route(self, enabled):
        return self.awg_transport.exit_set_smart_route('wireguard', enabled)

    def exit_smartroute_counters(self):
        return self.awg_transport.exit_smartroute_counters('wireguard')

    def exit_link_info(self, protocol_type):
        return self.awg_transport.exit_link_info(protocol_type)

    def exit_link_status(self, protocol_type, now=None):
        return self.awg_transport.exit_link_status(protocol_type, now)

    def exit_check_egress(self, protocol_type):
        return self.awg_transport.exit_check_egress(protocol_type)
