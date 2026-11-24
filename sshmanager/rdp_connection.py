import subprocess
import threading
import time


class RDPConnection:
    def __init__(self, config):
        self.config = config
        self.rdp_available = self._check_rdp_available()

    def _rdp_target(self, host):
        return 'TERMSRV/' + host

    def _check_rdp_available(self):
        """Check if mstsc.exe is available in the system path."""
        try:
            subprocess.run(['which', 'mstsc.exe'], capture_output=True, check=True)
            return True
        except Exception:
            pass

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
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _remove_credentials(self, target):
        """Remove credentials from Windows credential manager."""
        try:
            cmdkey_delete = ['cmdkey.exe', '/delete:' + target]
            subprocess.run(cmdkey_delete, capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _delayed_credential_cleanup(self, target):
        """Remove credentials after a delay."""
        time.sleep(30)
        self._remove_credentials(target)

    def connect(self, connection):
        """Connect to a remote desktop."""
        if not self.rdp_available:
            return False, "RDP not available (mstsc.exe not found)"

        username, password = self.config.get_rdp_credentials(connection['id'])
        if not username or not password:
            return False, "No RDP credentials stored"

        target = self._rdp_target(connection['ip'])
        if not self._add_credentials(target, username, password):
            return False, "Failed to add credentials"

        cleanup_thread = threading.Thread(
            target=self._delayed_credential_cleanup,
            args=(target,),
            daemon=True
        )
        cleanup_thread.start()

        try:
            subprocess.Popen(['mstsc.exe', '/v:' + connection['ip']])
            return True, "RDP session started"
        except FileNotFoundError:
            self._remove_credentials(target)
            return False, "Failed to start RDP session: mstsc.exe not found"
        except OSError as e:
            self._remove_credentials(target)
            return False, f"Failed to start RDP session: {str(e)}"
