import os
import subprocess
import threading
import time

class RDPConnection:
    def __init__(self, config):
        self.config = config
        self.rdp_available = self._check_rdp_available()

    def _check_rdp_available(self):
        """Check if mstsc.exe is available in the system path."""
        # Try 'which' first (works in WSL)
        try:
            subprocess.run(['which', 'mstsc.exe'], capture_output=True, check=True)
            return True
        except Exception:
            pass

        # Try 'where' (works in Windows)
        try:
            subprocess.run(['where', 'mstsc.exe'], capture_output=True, check=True)
            return True
        except Exception:
            return False

    def _add_credentials(self, target, username, password):
        """Add credentials to Windows credential manager."""
        try:
            cmdkey_add = [
                'cmdkey.exe', '/generic:' + target,
                '/user:' + username,
                '/password:' + password
            ]
            subprocess.run(cmdkey_add, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _remove_credentials(self, target):
        """Remove credentials from Windows credential manager."""
        try:
            cmdkey_delete = ['cmdkey.exe', '/delete:' + target]
            subprocess.run(cmdkey_delete, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _delayed_credential_cleanup(self, target):
        """Remove credentials after a delay."""
        time.sleep(30)  # Wait 30 seconds
        self._remove_credentials(target)

    def connect(self, connection):
        """Connect to a remote desktop."""
        if not self.rdp_available:
            return False, "RDP not available (mstsc.exe not found)"

        # Get stored credentials
        username, password = self.config.get_rdp_credentials(connection['id'])
        if not username or not password:
            return False, "No RDP credentials stored"

        # Add credentials to Windows credential manager
        if not self._add_credentials(connection['ip'], username, password):
            return False, "Failed to add credentials"

        # Start credential cleanup in background
        cleanup_thread = threading.Thread(
            target=self._delayed_credential_cleanup,
            args=(connection['ip'],),
            daemon=True
        )
        cleanup_thread.start()

        # Start RDP session
        try:
            subprocess.Popen(['mstsc.exe', '/v:' + connection['ip']])
            return True, "RDP session started"
        except subprocess.CalledProcessError as e:
            self._remove_credentials(connection['ip'])
            return False, f"Failed to start RDP session: {str(e)}"
