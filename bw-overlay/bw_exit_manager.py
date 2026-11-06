"""BW Exit Node uses only the upstream AmneziaWG transit endpoint."""
from managers.exit_manager import ExitManager


class BWExitManager(ExitManager):
    """No second plain-WireGuard listener is installed on Exit Nodes."""
    pass
