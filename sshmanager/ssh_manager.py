import curses
from .config import Config
from .database import Database, log_debug
from .ssh_connection import SSHConnection
from .rdp_connection import RDPConnection
from .ui import UI
import os

class SSHConnectionManager:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
        self.config = Config()
        
        # Check if config is encrypted and get master password
        if self.config.is_config_encrypted():
            while True:
                password = self.get_input(0, 0, "Enter master password: ", True)
                if self.config.load_config(password):
                    break
                self.show_error("Invalid master password")
                self.stdscr.clear()
        else:
            self.config.load_config()
            
        self.db = self.setup_db_connection()
        self.ssh = SSHConnection(self.config)
        self.rdp = RDPConnection(self.config)
        self.ui = UI(stdscr, self.db.connections)

    def get_input(self, y, x, prompt="", hidden=False):
        self.stdscr.move(y, 0)
        self.stdscr.clrtoeol()
        self.stdscr.addstr(y, 0, prompt)
        curses.echo(not hidden)
        self.stdscr.move(y, len(prompt))
        self.stdscr.refresh()
        input_str = self.stdscr.getstr(y, len(prompt)).decode('utf-8')
        curses.noecho()
        return input_str

    def show_error(self, message):
        """Show an error message in red."""
        max_y = self.stdscr.getmaxyx()[0]
        self.stdscr.addstr(max_y-1, 0, message, curses.color_pair(1))
        self.stdscr.refresh()
        self.stdscr.getch()
        self.stdscr.move(max_y-1, 0)
        self.stdscr.clrtoeol()

    def setup_db_connection(self):
        max_x = self.stdscr.getmaxyx()[1]
        db_config = self.config.config["db"].copy()
        
        if not db_config["server"]:
            self.stdscr.clear()
            self.stdscr.addstr(0, 0, "Select database type:\n1. MSSQL\n2. PostgreSQL")
            self.stdscr.refresh()
            while True:
                key = self.stdscr.getch()
                if key == ord('1'):
                    db_type = "mssql"
                    break
                elif key == ord('2'):
                    db_type = "postgres"
                    break
            
            self.stdscr.clear()
            heading = f"Configure {db_type.upper()}".center(max_x)[:max_x-1]
            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
            self.stdscr.addstr(2, 0, "Server: ")
            db_config["server"] = self.get_input(2, 8, "Server: ")
            self.stdscr.addstr(3, 0, "Database: ")
            db_config["database"] = self.get_input(3, 10, "Database: ")
            self.stdscr.addstr(4, 0, "Username: ")
            db_config["username"] = self.get_input(4, 10, "Username: ")
            self.stdscr.addstr(5, 0, "Password: ")
            db_config["password"] = self.get_input(5, 10, "Password: ", True)
            db_config["type"] = db_type
            
            # Save the DB config
            self.config.config["db"] = db_config
            self.config._save_config()
        
        return Database(db_config["type"], db_config)

    def refresh_ui(self):
        """Refresh the UI after connection changes."""
        self.db.load_connections()
        self.ui.connections = self.db.connections
        self.ui._build_folder_structure()

    def handle_auth_config(self, conn, is_new=False):
        """Handle authentication configuration for a connection."""
        max_y, max_x = self.stdscr.getmaxyx()

        # For new connections, connection type should already be set
        conn_type = conn.get('type', 'ssh')

        if conn_type == 'rdp':
            # RDP only supports password auth
            self.stdscr.clear()
            heading = "RDP Credentials".center(max_x)[:max_x-1]
            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
            
            # Get current credentials if editing
            current_username = ""
            current_password = ""
            if not is_new and 'id' in conn:
                current_username, current_password = self.config.get_rdp_credentials(conn['id'])
            
            self.stdscr.addstr(2, 0, f"Username ({current_username}): ")
            username = self.ui.get_input(2, 10, f"Username ({current_username}): ") or current_username or ""
            
            self.stdscr.addstr(3, 0, "Password (current): ")
            password = self.ui.get_input(3, 10, "Password (current): ", True) or current_password or ""
            
            # Store credentials after connection is saved
            conn['_rdp_creds'] = (username, password)
            
            return 'password'  # Always password for RDP
        else:
            # For SSH connections, use the existing auth type selector
            auth_type = self.ui.select_auth_type(current_type=conn.get('auth_type') if not is_new else None)
            
            if auth_type == "key":
                # Handle SSH key configuration
                self.stdscr.clear()
                heading = "SSH Key Configuration".center(max_x)[:max_x-1]
                self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                
                current_key = None if is_new else self.config.get_key_path(conn['id'])
                self.stdscr.addstr(2, 0, "Current SSH key path:")
                if current_key:
                    expanded_path = os.path.expanduser(current_key)
                    self.stdscr.addstr(3, 2, expanded_path, curses.A_DIM)
                    if expanded_path != current_key:
                        self.stdscr.addstr(4, 2, f"→ {expanded_path}", curses.A_DIM)
                else:
                    default_path = "~/.ssh/id_rsa"
                    expanded_default = os.path.expanduser(default_path)
                    self.stdscr.addstr(3, 2, f"{default_path} (default)", curses.A_DIM)
                    self.stdscr.addstr(4, 2, f"→ {expanded_default}", curses.A_DIM)
                
                # Show key options
                options = []
                if not is_new:
                    # For existing connections
                    current_display = current_key if current_key else "default (~/.ssh/id_rsa)"
                    options.append(("keep", f"🔒 Keep current key ({current_display})", "Continue using the current SSH key"))
                options.extend([
                    ("default", "🔒 Use default key", "Use the default SSH key (~/.ssh/id_rsa)"),
                    ("new", "🔒 Specify key file", "Choose a different SSH key file"),
                    ("generate", "🔒 Generate new key", "Create a new SSH key pair")
                ])
                
                selected = 0
                while True:
                    # Clear the options area
                    for i in range(6, max_y - 3):
                        self.stdscr.move(i, 0)
                        self.stdscr.clrtoeol()
                    
                    # Display options with descriptions
                    y = 6
                    for i, (_, text, desc) in enumerate(options):
                        if y >= max_y - 4:
                            break
                        self.stdscr.addstr(y, 2, text,
                                         curses.A_REVERSE if selected == i else curses.A_NORMAL)
                        self.stdscr.addstr(y + 1, 4, desc, curses.A_DIM)
                        y += 3
                    
                    # Display instructions
                    inst_y = max_y - 3
                    if inst_y > y:
                        self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
                    
                    self.stdscr.refresh()
                    
                    key = self.stdscr.getch()
                    if key == curses.KEY_UP and selected > 0:
                        selected -= 1
                    elif key == curses.KEY_DOWN and selected < len(options) - 1:
                        selected += 1
                    elif key == 10:  # Enter
                        action = options[selected][0]
                        if action == "keep":
                            return auth_type
                        elif action == "default":
                            # Store the key path after connection is saved
                            conn['_key_path'] = ""
                            return auth_type
                        elif action == "new":
                            key_path = self.ui.get_input(max_y - 2, 0, "Enter new key path: ") or ""
                            if key_path:
                                expanded_path = os.path.expanduser(key_path)
                                if os.path.exists(expanded_path):
                                    # Store the key path after connection is saved
                                    conn['_key_path'] = key_path
                                    return auth_type
                        elif action == "generate":
                            # Show key generation dialog
                            self.stdscr.clear()
                            heading = "Generate SSH Key".center(max_x)[:max_x-1]
                            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                            self.stdscr.addstr(2, 0, "This will create a new SSH key pair.")
                            key_path = self.ui.get_input(4, 0, "Save to path (default: ~/.ssh/id_rsa): ") or "~/.ssh/id_rsa"
                            if key_path:
                                # Store the key path after connection is saved
                                conn['_key_path'] = key_path
                                return auth_type
                    elif key == 27:  # Escape
                        return None
            else:  # password auth
                self.stdscr.clear()
                heading = "Password Configuration".center(max_x)[:max_x-1]
                self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                
                has_password = False if is_new else self.config.get_password(conn['id']) is not None
                self.stdscr.addstr(2, 0, "Current status:")
                self.stdscr.addstr(3, 0, "  Password is " + ("set" if has_password else "not set"), 
                                 curses.A_DIM)
                
                # Show security warning
                y = 5
                self.stdscr.addstr(y, 0, "⚠️  Note: Password auth is less secure than SSH keys", curses.A_DIM)
                y += 2
                
                # Show password options
                if has_password:
                    options = [
                        ("keep", "🔒 Keep current password", "Continue using the current password"),
                        ("new", "🔒 Set new password", "Enter a new password for this connection"),
                        ("clear", "🔒 Clear password", "Remove stored password")
                    ]
                else:
                    options = [
                        ("new", "🔒 Set new password", "Enter a password for this connection")
                    ]
                
                selected = 0
                while True:
                    # Display options with descriptions
                    y = 7
                    for i, (_, text, desc) in enumerate(options):
                        if y >= max_y - 4:
                            break
                        self.stdscr.addstr(y, 2, text,
                                         curses.A_REVERSE if selected == i else curses.A_NORMAL)
                        self.stdscr.addstr(y + 1, 4, desc, curses.A_DIM)
                        y += 3
                    
                    # Display instructions
                    inst_y = max_y - 3
                    if inst_y > y:
                        self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
                    
                    self.stdscr.refresh()
                    
                    key = self.stdscr.getch()
                    if key == curses.KEY_UP and selected > 0:
                        selected -= 1
                    elif key == curses.KEY_DOWN and selected < len(options) - 1:
                        selected += 1
                    elif key == 10:  # Enter
                        action = options[selected][0]
                        if action == "keep":
                            return auth_type
                        elif action == "new":
                            password = self.ui.get_input(max_y - 2, 0, "Enter new password: ", True)
                            if password:
                                # Store the password after connection is saved
                                conn['_password'] = password
                                return auth_type
                        elif action == "clear":
                            # Store the password after connection is saved
                            conn['_password'] = None
                            return auth_type
                    elif key == 27:  # Escape
                        return None
            
            return auth_type

    def main_loop(self):
        while True:
            max_y = self.stdscr.getmaxyx()[0]
            connections_count = self.ui.display_connections()
            self.ui.display_menu(max_y)
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            
            if key == ord('q'):  # Quit
                break
            
            elif key == ord('/'):  # Search
                self.ui.search_mode = True
                self.ui.search_term = ""
            
            elif self.ui.search_mode and key != curses.KEY_UP and key != curses.KEY_DOWN and key != ord('\n'):
                if self.ui.handle_search_input(key):
                    self.ui.selected = 0  # Reset selection when search changes
                    continue
            
            elif key == ord('m'):  # Master Key
                self.set_master_password()
                self.refresh_ui()

            elif key == 9:  # Tab - Switch connection type
                self.ui.current_type = "rdp" if self.ui.current_type == "ssh" else "ssh"
                if self.ui.current_type == "rdp" and not self.rdp.rdp_available:
                    self.show_error("RDP not available (mstsc.exe not found)")
                    self.ui.current_type = "ssh"
                self.ui.selected = 0

            elif key == ord('a'):  # Add
                # Basic connection info screen
                self.stdscr.clear()
                max_x = self.stdscr.getmaxyx()[1]
                heading = "Add New Connection".center(max_x)[:max_x-1]
                self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                
                # Interactive connection type selection first
                conn_data = {}
                conn_data["type"] = self.ui.select_connection_type(current_y=2)
                
                self.stdscr.clear()
                self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                
                # Get connection details
                self.stdscr.addstr(2, 0, "Name:")
                conn_data["name"] = self.ui.get_input(2, 6, "Name: ")
                if not conn_data["name"]:
                    return
                
                self.stdscr.addstr(3, 0, "IP/Host:")
                conn_data["ip"] = self.ui.get_input(3, 9, "IP/Host: ")
                if not conn_data["ip"]:
                    return
                
                # Username only for SSH connections
                if conn_data["type"] == "ssh":
                    self.stdscr.addstr(4, 0, "Username:")
                    conn_data["username"] = self.ui.get_input(4, 10, "Username: ")
                    if not conn_data["username"]:
                        return
                    
                    self.stdscr.addstr(5, 0, "Port (22):")
                    port = self.ui.get_input(5, 11, "Port (22): ")
                    conn_data["port"] = int(port) if port else 22
                else:
                    conn_data["username"] = ""
                    conn_data["port"] = None
                
                # Interactive folder selection in separate screen
                conn_data["folder"] = self.ui.select_folder(current_y=8, conn_type=conn_data["type"])
                
                # Handle authentication configuration
                auth_type = self.handle_auth_config(conn_data, is_new=True)
                conn_data["auth_type"] = auth_type
                
                # Save the connection
                self.db.save_connection(conn_data)
                
                # Now that we have the connection ID, save any credentials
                if '_rdp_creds' in conn_data:
                    username, password = conn_data.pop('_rdp_creds')
                    if username and password:
                        self.config.set_rdp_credentials(conn_data['id'], username, password)
                if '_key_path' in conn_data:
                    self.config.set_key_path(conn_data['id'], conn_data.pop('_key_path'))
                if '_password' in conn_data:
                    self.config.set_password(conn_data['id'], conn_data.pop('_password'))
                
                self.refresh_ui()
                # Reset selection to first connection after adding
                self.ui.selected = 0
            
            elif key == ord('e'):  # Edit
                conn = self.ui.get_selected_connection()
                if conn:
                    # Basic info screen
                    self.stdscr.clear()
                    max_x = self.stdscr.getmaxyx()[1]
                    heading = "Edit Connection".center(max_x)[:max_x-1]
                    self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                    
                    # Get basic connection info
                    self.stdscr.addstr(2, 0, "Leave fields empty to keep current values")
                    
                    new_name = self.ui.get_input(4, 0, f"Name ({conn['name']}): ")
                    new_ip = self.ui.get_input(5, 0, f"IP ({conn['ip']}): ")
                    new_username = self.ui.get_input(6, 0, f"Username ({conn['username']}): ")
                    new_port = self.ui.get_input(7, 0, f"Port ({conn.get('port', 22)}): ")
                    
                    # Update the connection data
                    conn_data = conn.copy()
                    if new_name: conn_data["name"] = new_name
                    if new_ip: conn_data["ip"] = new_ip
                    if new_username: conn_data["username"] = new_username
                    if new_port: conn_data["port"] = int(new_port)
                    
                    # Interactive folder selection
                    new_folder = self.ui.select_folder(current_y=8, current_folder=conn['folder'], conn_type=conn_data["type"])
                    
                    if new_folder:
                        conn_data["folder"] = new_folder

                    auth_type = self.handle_auth_config(conn_data, is_new=False)
                    conn_data["auth_type"] = auth_type

                    # Save the updated connection
                    self.db.save_connection(conn_data)
                    self.refresh_ui()
            
            elif key == ord('d'):  # Delete
                conn = self.ui.get_selected_connection()
                if conn:
                    self.stdscr.clear()
                    max_x = self.stdscr.getmaxyx()[1]
                    heading = "Delete Connection".center(max_x)[:max_x-1]
                    self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                    
                    # Show warning
                    self.stdscr.addstr(2, 0, f"Are you sure you want to delete connection '{conn['name']}'?")
                    self.stdscr.addstr(3, 0, "This will also remove any associated SSH keys and passwords.")
                    self.stdscr.addstr(4, 0, "This action cannot be undone.")
                    self.stdscr.addstr(6, 0, "Press 'y' to confirm, any other key to cancel.")
                    self.stdscr.refresh()
                    
                    if self.stdscr.getch() == ord('y'):
                        # Clean up all config entries for this connection
                        self.config.remove_connection_config(conn['id'])
                        
                        # Then delete the connection
                        self.db.remove_connection(conn['id'])
                        
                        # Update selection if needed
                        total_connections = sum(len(conns) for conns in self.db.connections.values())
                        if self.ui.selected >= total_connections:
                            self.ui.selected = max(0, total_connections - 1)
                        
                        self.refresh_ui()
            
            elif key == curses.KEY_UP:
                if self.ui.selected > 0:
                    self.ui.selected -= 1
            elif key == curses.KEY_DOWN:
                # Count only connections of current type
                filtered_count = sum(
                    len([c for c in conns if c.get('type', 'ssh') == self.ui.current_type])
                    for conns in self.db.connections.values()
                )
                if self.ui.selected < connections_count - 1:
                    self.ui.selected += 1
            
            elif key == ord('\n') or key == ord('c'):  # Connect
                conn = self.ui.get_selected_connection()
                if conn:
                    if conn.get('type', 'ssh') == 'rdp':
                        success, message = self.rdp.connect(conn)
                        if not success:
                            self.show_error(message)
                    else:
                        try:
                            self.ssh.connect(conn, self.stdscr)
                        except Exception as e:
                            self.show_error(f"Connection failed: {str(e)}")

    def set_master_password(self):
        """Set or change the master password."""
        max_y, max_x = self.stdscr.getmaxyx()
        
        # Clear screen and show header
        self.stdscr.clear()
        heading = "Master Key Configuration".center(max_x)[:max_x-1]
        self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
        
        # Show current status
        is_encrypted = self.config.is_config_encrypted()
        self.stdscr.addstr(2, 0, "Current status:")
        self.stdscr.addstr(3, 0, "  Config is " + ("encrypted" if is_encrypted else "not encrypted"), 
                         curses.A_DIM)
        
        # Show options based on current state
        if is_encrypted:
            options = [
                ("keep", "🔒 Keep current key", "Continue using the current master key"),
                ("change", "🔒 Change key", "Set a new master key"),
                ("remove", "🔓 Remove encryption", "Disable config encryption")
            ]
        else:
            options = [
                ("create", "🔒 Enable encryption", "Set up config encryption with a master key")
            ]
        
        selected = 0
        while True:
            # Display options with descriptions
            y = 5
            for i, (_, text, desc) in enumerate(options):
                if y >= max_y - 4:
                    break
                self.stdscr.addstr(y, 2, text,
                                 curses.A_REVERSE if selected == i else curses.A_NORMAL)
                self.stdscr.addstr(y + 1, 4, desc, curses.A_DIM)
                y += 3
            
            # Display instructions
            inst_y = max_y - 3
            if inst_y > y:
                self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(options) - 1:
                selected += 1
            elif key == 10:  # Enter
                action = options[selected][0]
                if action == "keep":
                    break
                elif action == "create" or action == "change":
                    # Get new password
                    self.stdscr.clear()
                    heading = "Set Master Key".center(max_x)[:max_x-1]
                    self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
                    
                    # Add instructions
                    self.stdscr.addstr(2, 0, "This will encrypt your configuration file with a master password.")
                    self.stdscr.addstr(3, 0, "You will need to enter this password each time you start the program.")
                    self.stdscr.addstr(4, 0, "Make sure to remember your password - there is no way to recover it!")
                    
                    # Get new password with proper spacing
                    password = self.ui.get_input(6, 0, "Enter new master password: ", True)
                    
                    if password:
                        # Confirm password
                        confirm = self.ui.get_input(7, 0, "Confirm password: ", True)
                        
                        if password != confirm:
                            self.show_error("Passwords do not match")
                        else:
                            self.config.set_master_password(password)
                    break
                elif action == "remove":
                    self.config.disable_encryption()
                    break
            elif key == 27:  # Escape
                break
        
        # Clear screen before returning
        self.stdscr.clear()

def main(stdscr):
    manager = SSHConnectionManager(stdscr)
    manager.main_loop()

def main_cli():
    """Entry point for the CLI command."""
    curses.wrapper(main)

if __name__ == "__main__":
    curses.wrapper(main)