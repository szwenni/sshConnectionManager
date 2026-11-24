import paramiko
import os
import sys
import platform
import signal
import struct
import socket
import errno
import time
import codecs
import getpass
from typing import Optional
import curses

_WINDOWS_KEY_MAP = {
    b'H': b'\x1b[A',  # up
    b'P': b'\x1b[B',  # down
    b'K': b'\x1b[D',  # left
    b'M': b'\x1b[C',  # right
    b'G': b'\x1b[H',  # home
    b'O': b'\x1b[F',  # end
    b'I': b'\x1b[5~',  # page up
    b'Q': b'\x1b[6~',  # page down
    b'S': b'\x1b[3~',  # delete
    b'R': b'\x1b[2~',  # insert
}


def generate_ssh_key(path: str) -> str:
    """Create an OpenSSH Ed25519 key pair at path and path.pub."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    path = os.path.expanduser(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if os.path.exists(path):
        raise FileExistsError(f"Key already exists: {path}")

    key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    with open(path, 'wb') as f:
        f.write(private_bytes)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    with open(path + '.pub', 'wb') as f:
        f.write(public_bytes + b'\n')
    return path


def load_private_key(path: str, password=None):
    """Load an Ed25519, ECDSA, or RSA private key."""
    last_errors = []
    for key_class in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_class.from_private_key_file(path, password=password)
        except paramiko.PasswordRequiredException:
            raise
        except paramiko.ssh_exception.SSHException as e:
            message = str(e).lower()
            if 'passphrase' in message or 'encrypted' in message:
                raise paramiko.PasswordRequiredException(str(e))
            last_errors.append(f"{key_class.__name__}: {e}")
        except Exception as e:
            last_errors.append(f"{key_class.__name__}: {e}")
    raise Exception("Unsupported or invalid SSH key (" + "; ".join(last_errors) + ")")

IS_WINDOWS = platform.system().lower() == "windows"

if not IS_WINDOWS:
    import termios
    import fcntl
    import tty
    import select

class SSHConnection:
    def __init__(self, config):
        self.config = config
        self.client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
        self.original_terminal_settings = None
        self.is_windows = IS_WINDOWS
        self._windows_original_output_cp = None
        self._windows_original_console_mode = None

    def _get_terminal_size(self):
        """Get the current terminal size."""
        if self.is_windows:
            try:
                from ctypes import windll, create_string_buffer
                h = windll.kernel32.GetStdHandle(-11)
                csbi = create_string_buffer(22)
                res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)
                if res:
                    (_, _, _, _, _, left, top, right, bottom, _, _) = struct.unpack("hhhhHhhhhhh", csbi.raw)
                    cols = right - left + 1
                    rows = bottom - top + 1
                    return rows, cols
            except Exception:
                return 24, 80
        else:
            try:
                s = struct.pack('HHHH', 0, 0, 0, 0)
                size = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, s)
                rows, cols, _, _ = struct.unpack('HHHH', size)
                return rows, cols
            except Exception:
                return 24, 80

    def _set_terminal_raw(self):
        """Set terminal to raw mode."""
        if self.is_windows:
            return  # Windows doesn't need raw mode for basic functionality
        
        if not os.isatty(sys.stdin.fileno()):
            return
        self.original_terminal_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

    def _restore_terminal(self):
        """Restore original terminal settings."""
        if self.is_windows:
            self._restore_windows_console()
            return

        if self.original_terminal_settings and os.isatty(sys.stdin.fileno()):
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.original_terminal_settings)

    def _update_terminal_size(self, signum=None, frame=None):
        """Update the terminal size on the remote session."""
        if self.channel and self.channel.active:
            rows, cols = self._get_terminal_size()
            try:
                self.channel.resize_pty(width=cols, height=rows)
            except paramiko.SSHException:
                pass

    def _enable_windows_vt_mode(self):
        """Enable VT sequences and UTF-8 output on the Windows console."""
        try:
            from ctypes import windll, byref, c_uint
            kernel32 = windll.kernel32
            self._windows_original_output_cp = kernel32.GetConsoleOutputCP()
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = c_uint()
            if kernel32.GetConsoleMode(handle, byref(mode)):
                self._windows_original_console_mode = mode.value
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

    def _restore_windows_console(self):
        """Restore Windows console mode and code page after an SSH session."""
        try:
            from ctypes import windll
            kernel32 = windll.kernel32
            if self._windows_original_output_cp:
                kernel32.SetConsoleOutputCP(self._windows_original_output_cp)
            if self._windows_original_console_mode is not None:
                handle = kernel32.GetStdHandle(-11)
                kernel32.SetConsoleMode(handle, self._windows_original_console_mode)
        except Exception:
            pass

    def _write_local_bytes(self, data: bytes) -> None:
        """Write remote bytes to the local TTY without killing the SSH session."""
        if not data:
            return
        while data:
            try:
                written = sys.stdout.buffer.write(data)
                if not written:
                    break
                data = data[written:]
                sys.stdout.buffer.flush()
            except (InterruptedError, BlockingIOError):
                continue
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                break
            except UnicodeError:
                break

    def _write_local_text(self, text: str) -> None:
        """Write decoded text to the Windows console without killing the SSH session."""
        if not text:
            return
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, UnicodeError, InterruptedError, BlockingIOError):
            pass

    def connect(self, conn_data, stdscr=None):
        """Establish SSH connection and start interactive session."""
        inner_exception = None
        try:
            if stdscr:
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()

            # Validate connection data
            required_fields = ['ip', 'auth_type']
            for field in required_fields:
                if field not in conn_data:
                    raise ValueError(f"Missing required field: {field}")

            if conn_data['auth_type'] not in ['password', 'key']:
                raise ValueError(f"Invalid auth_type: {conn_data['auth_type']}")

            # Start SSH session with proper error handling
            self._start_ssh_session(conn_data, stdscr)

        except Exception as e:
            inner_exception = e
            if not stdscr:
                print(f"Connection failed: {str(e)}", file=sys.stderr)
                input("Press Enter to continue...")
        finally:
            self._cleanup()
            if stdscr:
                # Restore curses mode
                curses.initscr()
                curses.noecho()
                curses.cbreak()
                stdscr.keypad(True)
                try:
                    curses.start_color()
                    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
                except curses.error:
                    pass
                stdscr.clear()
                stdscr.refresh()
        if inner_exception:
            raise inner_exception

    def _start_ssh_session(self, conn_data, stdscr=None):
        """Start an interactive SSH session."""
        try:
            # Initialize SSH client
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection parameters
            connect_params = {
                'hostname': conn_data['ip'],
                'username': self.config.resolve_ssh_username(
                    conn_data.get('id'), conn_data.get('username', "")
                ),
                'port': conn_data.get('port', 22),
                'timeout': 30,
            }

            # Add authentication parameters
            if conn_data['auth_type'] == 'key':
                try:
                    key_path = self.config.get_key_path(conn_data['id'])
                    if key_path:
                        # Expand ~ to user's home directory
                        key_path = os.path.expanduser(key_path)
                    else:
                        # Use default key path
                        key_path = os.path.expanduser('~/.ssh/id_rsa')
                        
                    if not os.path.exists(key_path):
                        raise FileNotFoundError(f"SSH key file not found: {key_path}")

                    key_password = self.config.get_key_password(conn_data['id'])
                    try:
                        connect_params['pkey'] = load_private_key(key_path, password=key_password)
                    except paramiko.PasswordRequiredException:
                        key_password = getpass.getpass("SSH key is encrypted. Enter key password: ")
                        connect_params['pkey'] = load_private_key(key_path, password=key_password)
                        save_pwd = input("Save key password? (y/n): ").strip().lower()
                        if save_pwd in ('y', 'yes'):
                            self.config.set_key_password(conn_data['id'], key_password)
                except Exception as e:
                    raise Exception(f"Failed to load SSH key: {str(e)}")
            else:
                password = self.config.get_password(conn_data['id'])
                if not password:
                    raise ValueError("No password found for this connection")
                connect_params['password'] = password

            # Attempt connection
            try:
                self.client.connect(**connect_params)
            except paramiko.AuthenticationException:
                raise Exception("Authentication failed. Please check your credentials.")
            except paramiko.SSHException as e:
                raise Exception(f"SSH error: {str(e)}")
            except Exception as e:
                raise Exception(f"Connection error: {str(e)}")

            transport = self.client.get_transport()
            if transport:
                transport.set_keepalive(30)

            # Get terminal size
            rows, cols = self._get_terminal_size()

            # Start interactive shell
            try:
                self.channel = self.client.invoke_shell(
                    term='xterm-256color',
                    width=cols,
                    height=rows
                )
            except paramiko.SSHException as e:
                raise Exception(f"Failed to open interactive shell: {str(e)}")

            if not self.is_windows:
                # Set up terminal size handler (Unix only)
                signal.signal(signal.SIGWINCH, self._update_terminal_size)
                self._update_terminal_size()

            # Set terminal to raw mode
            self._set_terminal_raw()

            # Start interactive session
            self._interactive_shell()

        except Exception as e:
            if self.client:
                self.client.close()
            raise Exception(f"Failed to establish SSH connection: {str(e)}")

    def _interactive_shell(self):
        """Handle the interactive shell session."""
        if not self.channel:
            return

        try:
            # Set channel timeout
            self.channel.settimeout(0.0)

            if self.is_windows:
                self._windows_interactive_shell()
            else:
                self._unix_interactive_shell()
        except Exception as e:
            raise Exception(f"Interactive shell error: {str(e)}")
        finally:
            self._restore_terminal()

    def _windows_interactive_shell(self):
        """Windows-specific interactive shell implementation."""
        try:
            import msvcrt
        except ImportError:
            raise Exception("msvcrt module not available - Windows support requires Python for Windows")

        self._enable_windows_vt_mode()
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

        while self.channel and self.channel.active:
            had_io = False
            try:
                if self.channel.recv_ready():
                    try:
                        data = self.channel.recv(4096)
                    except socket.timeout:
                        data = None
                    if data is not None:
                        if len(data) == 0:
                            break
                        had_io = True
                        self._write_local_text(decoder.decode(data))

                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    had_io = True
                    if char in (b'\x00', b'\xe0') and msvcrt.kbhit():
                        char = _WINDOWS_KEY_MAP.get(msvcrt.getch())
                        if not char:
                            continue
                    try:
                        self.channel.send(char)
                    except socket.timeout:
                        pass
                    except (OSError, paramiko.SSHException):
                        if not (self.channel and self.channel.active):
                            break

                if not had_io:
                    time.sleep(0.01)
            except socket.timeout:
                continue
            except (OSError, UnicodeError):
                if not (self.channel and self.channel.active):
                    break
                continue

    def _unix_interactive_shell(self):
        """Unix-specific interactive shell implementation (Linux, macOS, WSL)."""
        oldflags = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
        try:
            fcntl.fcntl(sys.stdin, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)

            while self.channel and self.channel.active:
                try:
                    r, w, e = select.select([self.channel, sys.stdin], [], [], 0.1)
                except InterruptedError:
                    continue
                except OSError as err:
                    if err.errno == errno.EINTR:
                        continue
                    raise

                if self.channel in r:
                    try:
                        data = self.channel.recv(4096)
                    except socket.timeout:
                        data = None
                    except OSError as err:
                        if err.errno == errno.EINTR:
                            data = None
                        else:
                            raise
                    if data is not None:
                        if len(data) == 0:
                            break
                        self._write_local_bytes(data)

                if sys.stdin in r:
                    try:
                        data = sys.stdin.buffer.read1(4096)
                    except InterruptedError:
                        continue
                    except OSError as err:
                        if err.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                            continue
                        if err.errno in (errno.EIO, errno.EBADF):
                            break
                        continue
                    if not data:
                        break
                    try:
                        self.channel.send(data)
                    except socket.timeout:
                        pass
                    except (OSError, paramiko.SSHException):
                        if not (self.channel and self.channel.active):
                            break
        finally:
            try:
                fcntl.fcntl(sys.stdin, fcntl.F_SETFL, oldflags)
            except OSError:
                pass

    def _cleanup(self):
        """Clean up SSH connection and restore terminal settings."""
        self._restore_terminal()
        
        if self.channel:
            try:
                self.channel.close()
            except Exception:
                pass
            self.channel = None
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None