import paramiko
import os
import sys
import platform
import signal
import struct
from typing import Optional
import curses

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
            except:
                # Default fallback size
                return 24, 80
        else:
            try:
                s = struct.pack('HHHH', 0, 0, 0, 0)
                size = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, s)
                rows, cols, _, _ = struct.unpack('HHHH', size)
                return rows, cols
            except:
                # Default fallback size
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

    def connect(self, conn_data, stdscr=None):
        """Establish SSH connection and start interactive session."""
        try:
            if stdscr:
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()

            # Validate connection data
            required_fields = ['ip', 'username', 'auth_type']
            for field in required_fields:
                if field not in conn_data:
                    raise ValueError(f"Missing required field: {field}")

            if conn_data['auth_type'] not in ['password', 'key']:
                raise ValueError(f"Invalid auth_type: {conn_data['auth_type']}")

            # Start SSH session with proper error handling
            self._start_ssh_session(conn_data, stdscr)

        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            if stdscr:
                # If we're in curses mode, properly exit before showing error
                curses.endwin()
            print(error_msg, file=sys.stderr)
            if not stdscr:
                input("Press Enter to continue...")
        finally:
            self._cleanup()
            if stdscr:
                # Restore curses mode
                curses.initscr()
                curses.noecho()
                curses.cbreak()
                stdscr.keypad(True)
                stdscr.clear()
                stdscr.refresh()

    def _start_ssh_session(self, conn_data, stdscr=None):
        """Start an interactive SSH session."""
        try:
            # Initialize SSH client
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection parameters
            connect_params = {
                'hostname': conn_data['ip'],
                'username': conn_data['username'],
                'port': conn_data.get('port', 22),  # Use port from connection data or default to 22
                'timeout': 30,  # Add timeout to prevent hanging
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
                    
                    # Try to load the key, first with saved password if any
                    try:
                        key_password = self.config.get_key_password(conn_data['id'])
                        connect_params['pkey'] = paramiko.RSAKey.from_private_key_file(key_path, password=key_password)
                    except paramiko.ssh_exception.PasswordRequiredException:
                        # Key is encrypted and we don't have a saved password, ask for it
                        key_password = None
                        if stdscr:
                            stdscr.clear()
                            stdscr.addstr(0, 0, "SSH Key is encrypted")
                            stdscr.addstr(2, 0, "Enter key password: ")
                            stdscr.refresh()
                            curses.echo(False)  # Don't show password
                            key_password = stdscr.getstr(2, 17).decode('utf-8')
                            curses.noecho()
                            
                            # Ask if user wants to save the password
                            stdscr.addstr(4, 0, "Save key password? (y/n): ")
                            stdscr.refresh()
                            save_pwd = stdscr.getch()
                            if save_pwd in [ord('y'), ord('Y')]:
                                self.config.set_key_password(conn_data['id'], key_password)
                        else:
                            key_password = input("Enter key password: ")
                        
                        # Try again with the password
                        connect_params['pkey'] = paramiko.RSAKey.from_private_key_file(key_path, password=key_password)
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

            # Get terminal size
            rows, cols = self._get_terminal_size()

            # Start interactive shell
            try:
                self.channel = self.client.invoke_shell(
                    term='xterm',
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
            self._cleanup()

    def _windows_interactive_shell(self):
        """Windows-specific interactive shell implementation."""
        try:
            import msvcrt
        except ImportError:
            raise Exception("msvcrt module not available - Windows support requires Python for Windows")
        
        while True:
            try:
                # Check if there's data to read from the channel
                if self.channel.recv_ready():
                    data = self.channel.recv(1024)
                    if len(data) == 0:
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()

                # Check if there's input from the user
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    if char == b'\x03':  # Ctrl+C
                        break
                    self.channel.send(char)
                    
            except Exception as e:
                raise Exception(f"Windows shell error: {str(e)}")

    def _unix_interactive_shell(self):
        """Unix-specific interactive shell implementation."""
        try:
            oldflags = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
            fcntl.fcntl(sys.stdin, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)

            while True:
                try:
                    r, w, e = select.select([self.channel, sys.stdin], [], [], 0.1)
                    
                    if self.channel in r:
                        try:
                            data = self.channel.recv(1024)
                            if len(data) == 0:
                                break
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                        except Exception:
                            break

                    if sys.stdin in r:
                        data = sys.stdin.buffer.read1(1024)
                        if len(data) == 0:
                            break
                        self.channel.send(data)

                except select.error:
                    pass
                except (EOFError, OSError):
                    break

        except Exception as e:
            raise Exception(f"Unix shell error: {str(e)}")
        finally:
            # Restore terminal state
            if not self.is_windows:
                fcntl.fcntl(sys.stdin, fcntl.F_SETFL, oldflags)

    def _cleanup(self):
        """Clean up SSH connection and restore terminal settings."""
        self._restore_terminal()
        
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
        if self.client:
            try:
                self.client.close()
            except:
                pass