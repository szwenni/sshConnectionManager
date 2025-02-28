import curses
from typing import Dict, List
from collections import defaultdict
import os
from datetime import datetime

LOG_FILE = os.path.join(os.getcwd(), "ssh_manager_debug.log")

def log_debug(message: str):
    with open(LOG_FILE, 'a') as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {message}\n")

class UI:
    def __init__(self, stdscr, connections: Dict[str, List[dict]]):
        self.stdscr = stdscr
        self.connections = connections  # Reference to self.db.connections
        self.selected = 0  # Index of selected connection (not row)
        self.connection_rows = []  # List to map row numbers to connections
        self.folder_structure = {}  # Nested folder structure
        self.search_mode = False
        self.search_term = ""
        self.current_type = "ssh"  # Current connection type being displayed
        curses.curs_set(0)
        self._build_folder_structure()

    def _build_folder_structure(self):
        """Build folder structure from connections."""
        # Initialize structure with type separation
        self.folder_structure = {
            'ssh': {'__root': {'connections': [], 'children': {}}},
            'rdp': {'__root': {'connections': [], 'children': {}}}
        }
        
        # Process each connection
        for folder, connections in self.connections.items():
            for conn in connections:
                conn_type = conn.get('type', 'ssh')
                folder_parts = folder.split('/') if folder else []
                
                # Start at the type's root
                current = self.folder_structure[conn_type]['__root']
                
                # Add connection to root if no folder
                if not folder_parts or folder_parts[0] == 'default':
                    current['connections'].append(conn)
                    continue
                
                # Build folder path
                for part in folder_parts:
                    if part not in current['children']:
                        current['children'][part] = {'connections': [], 'children': {}}
                    current = current['children'][part]
                
                # Add connection to final folder
                current['connections'].append(conn)
        
        return self.folder_structure[self.current_type]

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

    def _matches_search(self, conn: dict) -> bool:
        """Check if a connection matches the current search term."""
        if not self.search_term:
            return True
        search_lower = self.search_term.lower()
        return (search_lower in conn['name'].lower() or
                search_lower in conn['ip'].lower() or
                search_lower in conn.get('username', '').lower() or
                search_lower in conn.get('folder', '').lower())

    def _filter_folder_structure(self, folder_dict: dict) -> dict:
        """Create a new folder structure containing only matching connections."""
        if not self.search_term:
            return folder_dict

        filtered = {'connections': [], 'children': {}}
        
        # Filter connections
        filtered['connections'] = [
            conn for conn in folder_dict.get('connections', [])
            if self._matches_search(conn)
        ]
        
        # Filter subfolders
        for folder_name, subfolder in folder_dict.get('children', {}).items():
            filtered_subfolder = self._filter_folder_structure(subfolder)
            if filtered_subfolder['connections'] or filtered_subfolder['children']:
                filtered['children'][folder_name] = filtered_subfolder
                
        return filtered

    def _display_folder_contents(self, folder_dict, path="", level=0, row=2, connection_index=0):
        """Recursively display folder contents with proper indentation."""
        max_y, max_x = self.stdscr.getmaxyx()
        indent = "  " * level
        
        # If in search mode, filter the folder structure
        display_dict = self._filter_folder_structure(folder_dict) if self.search_mode else folder_dict

        # Sort connections by name for consistent display
        sorted_connections = sorted(display_dict.get('connections', []), key=lambda x: x['name'])
        
        # Display contents of current folder
        for conn in sorted_connections:
            # Skip connections that don't match the current type
            if conn.get('type', 'ssh') != self.current_type:
                continue
                
            if row >= max_y - 1:  # Leave room for menu/search
                break
            
            # Calculate available width for the line
            available_width = max_x - len(indent) - 1
            name_ip = f"{conn['name']} ({conn['ip']})"
            
            # Truncate the name_ip if it's too long
            if len(name_ip) > available_width - 2:  # -2 for the └─
                name_ip = name_ip[:available_width - 5] + "..."
            
            line = f"{indent}└─ {name_ip}"
            
            # Map this row to the connection and its path
            self.connection_rows.append((path, conn))
            
            if connection_index == self.selected:
                self.stdscr.addstr(row, 0, line, curses.A_REVERSE)
            else:
                self.stdscr.addstr(row, 0, line)
            row += 1
            connection_index += 1

        # Sort subfolders for consistent display
        sorted_folders = sorted(display_dict.get('children', {}).items())
        
        # Display subfolders
        for folder_name, subfolder in sorted_folders:
            if row >= max_y - 1:  # Leave room for menu/search
                break
            
            # Calculate available width for the folder line
            available_width = max_x - len(indent) - 1
            folder_display = folder_name
            if len(folder_display) > available_width - 2:  # -2 for the 📁
                folder_display = folder_display[:available_width - 5] + "..."
            
            folder_line = f"{indent}📁 {folder_display}"
            self.stdscr.addstr(row, 0, folder_line)
            row += 1
            
            new_path = f"{path}/{folder_name}" if path else folder_name
            row, connection_index = self._display_folder_contents(
                subfolder, new_path, level + 1, row, connection_index
            )

        return row, connection_index

    def display_connections(self):
        """Display the connection list with proper alignment and header."""
        self.stdscr.clear()
        max_y, max_x = self.stdscr.getmaxyx()
        
        # Display header in the first row
        heading = f"Connection Manager - {self.current_type.upper()} Connections".center(max_x)[:max_x-1]
        self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
        
        # Reset connection rows mapping
        self.connection_rows = []
        
        # Start displaying content from row 2
        current_row = 2
        
        # Display "Connections" root folder
        self.stdscr.addstr(current_row, 0, "📁 Connections")
        current_row += 1
        
        # Get the current type's folder structure
        type_structure = self.folder_structure[self.current_type]
        
        # Display root contents first
        if '__root' in type_structure:
            current_row, _ = self._display_folder_contents(
                type_structure['__root'], "", 1, current_row, len(self.connection_rows)
            )
        
        # Sort folders to ensure consistent display order
        sorted_folders = sorted(
            (k, v) for k, v in type_structure.get('children', {}).items()
        )
        
        # Display all folders and their contents with increased indentation
        for folder_name, folder_dict in sorted_folders:
            if current_row >= max_y - 1:  # Leave room for menu/search
                break
            
            # Display folder name with one level of indentation
            self.stdscr.addstr(current_row, 2, f"📁 {folder_name}")
            current_row += 1
            
            # Display folder contents with additional indentation
            current_row, _ = self._display_folder_contents(
                folder_dict, folder_name, 2, current_row, len(self.connection_rows)
            )
            
        return len(self.connection_rows)

    def display_menu(self, max_y):
        """Display the menu or search bar at the bottom of the screen."""
        try:
            max_x = self.stdscr.getmaxyx()[1]
            if self.search_mode:
                # Display search bar
                search_prompt = f"Search (ESC to exit): {self.search_term}"
                # Ensure we don't write to the last character position
                self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))  # Clear the line
                self.stdscr.addstr(max_y - 1, 0, search_prompt[:max_x - 1], curses.A_REVERSE)
            else:
                # Display menu
                menu_text = "q:Quit  ^F|/:Search  a:Add  e:Edit  d:Delete  m:Master Key  Tab:Switch Type"
                if self.current_type == 'rdp':
                    menu_text += "  p:Passwords"
                padded_menu = menu_text.center(max_x - 1)[:max_x - 1]  # Leave last character
                self.stdscr.addstr(max_y - 1, 0, padded_menu, curses.A_REVERSE)
        except curses.error:
            pass  # Ignore curses errors from small terminal windows

    def get_selected_connection(self):
        if 0 <= self.selected < len(self.connection_rows):
            folder, conn = self.connection_rows[self.selected]
            return conn
        return None

    def handle_search_input(self, char):
        """Handle input while in search mode."""
        log_debug(char)
        if char == 27:  # Escape
            self.search_mode = False
            self.search_term = ""
            return True
        elif char == 10:  # Enter
            self.search_mode = False
            return True
        elif char == curses.KEY_BACKSPACE or char == 127 or char == 8:  # Backspace
            self.search_term = self.search_term[:-1]
            return True
        elif 32 <= char <= 126:  # Printable characters
            self.search_term += chr(char)
            return True
        return False

    def get_folder_structure(self, conn_type=None):
        """Get folder structure from connections, optionally filtered by type."""
        folder_tree = []
        
        # Build folder tree from existing folders
        for folder in sorted(self.connections.keys()):
            # Skip folders that don't have connections of the requested type
            if conn_type:
                if not any(conn['type'] == conn_type for conn in self.connections[folder]):
                    continue
                    
            if folder:  # Skip root folder
                parts = folder.split("/")
                current = folder_tree
                for i, part in enumerate(parts):
                    # Find or create folder
                    found = False
                    for item in current:
                        if item["name"] == part:
                            found = True
                            current = item["children"]
                            break
                    if not found:
                        new_folder = {"name": part, "children": []}
                        current.append(new_folder)
                        current = new_folder["children"]
        
        return folder_tree
        
    def select_folder(self, current_y=2, current_folder=None, conn_type=None):
        """Interactive folder selector."""
        max_y, max_x = self.stdscr.getmaxyx()
        
        # Get folder structure filtered by connection type
        folder_tree = self.get_folder_structure(conn_type)
        
        # Build flat list of folders with their full paths
        folders = []
        def add_folders(tree, path=""):
            for folder in tree:
                full_path = f"{path}/{folder['name']}" if path else folder["name"]
                if folder['name'] != 'default':
                    folders.append(full_path)
                add_folders(folder["children"], full_path)
        add_folders(folder_tree)
        
        # Add root and new folder options
        #folders = ["", "New Folder"] + folders
        
        # Find index of current folder
        selected = 0
        if current_folder:
            try:
                selected = folders.index(current_folder)
            except ValueError:
                pass
        
        scroll_offset = 0
        
        while True:
            self.stdscr.clear()
            heading = "Select or Create Folder".center(max_x)[:max_x-1]
            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
            
            # Calculate visible range
            visible_height = max_y - current_y - 4  # Leave room for instructions
            max_visible = min(len(folders) + 2, visible_height)  # +2 for Create New and Connections
            
            # Adjust scroll if needed
            if selected - scroll_offset >= visible_height:
                scroll_offset = selected - visible_height + 1
            elif selected < scroll_offset:
                scroll_offset = selected
            
            # Display options
            y = current_y
            
            # Display Create New option
            if y < max_y - 1:
                self.stdscr.addstr(y, 0, "📝 Create New Folder", 
                                 curses.A_REVERSE if selected == 0 else curses.A_NORMAL)
                y += 1
            
            # Display Connections (root) option
            if y < max_y - 1:
                self.stdscr.addstr(y, 0, "📁 Connections", 
                                 curses.A_REVERSE if selected == 1 else curses.A_NORMAL)
                y += 1
            
            # Display existing folders with hierarchy
            current_root = None
            for i, folder in enumerate(folders[scroll_offset:scroll_offset+visible_height-2], 2):
                if y >= max_y - 1:
                    break
                
                parts = folder.split('/')
                level = len(parts) - 1
                display_name = parts[-1]
                
                # Calculate indentation
                indent = "  " * (level + 1)  # +1 to account for root level
                display_text = f"{indent}📁 {display_name}"
                if len(display_text) > max_x - 2:
                    display_text = display_text[:max_x - 5] + "..."
                
                if y < max_y - 1:
                    self.stdscr.addstr(y, 0, display_text,
                                     curses.A_REVERSE if selected == i else curses.A_NORMAL)
                    y += 1
            
            # Display instructions
            inst_y = max_y - 3
            if inst_y > current_y + 2:
                self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(folders) + 1:
                selected += 1
            elif key == 10:  # Enter
                if selected == 0:
                    # Create new folder
                    self.stdscr.addstr(max_y - 2, 0, " " * max_x)  # Clear the line
                    prompt = "Enter new folder path: "
                    self.stdscr.addstr(max_y - 2, 0, prompt, curses.A_BOLD)
                    curses.echo()
                    new_folder = self.stdscr.getstr(max_y - 2, len(prompt)).decode('utf-8').strip()
                    curses.noecho()
                    if new_folder:
                        return new_folder
                elif selected == 1:
                    return "default"  # Still use "default" internally
                else:
                    return folders[selected - 2]  # -2 for Create New and Connections options
            elif key == 27:  # Escape
                if current_folder:
                    return current_folder
                return "default"
        
        return "default"

    def select_auth_type(self, current_y=2, current_type=None):
        """Select authentication type."""
        max_y, max_x = self.stdscr.getmaxyx()
        
        # Clear screen
        self.stdscr.clear()
        
        # Display header
        heading = "Select Authentication Type".center(max_x)[:max_x-1]
        self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
        
        # Add description with offset
        y = current_y + 2
        self.stdscr.addstr(y, 2, "Choose how to authenticate with the server:")
        
        # Show authentication options
        options = [
            ("key", "🔑 SSH Key Authentication", "More secure, recommended for SSH connections"),
            ("password", "🔒 Password Authentication", "Simple but less secure than SSH keys")
        ]
        
        # Find the index of the current type
        selected = 0
        if current_type:
            for i, (type_id, _, _) in enumerate(options):
                if type_id == current_type:
                    selected = i
                    break
        
        while True:
            # Display options with descriptions
            y = current_y + 4  # More spacing from the top
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
                return options[selected][0]
            elif key == 27:  # Escape
                return None

    def select_connection_type(self, current_y=1, current_type=None):
        """Interactive connection type selector."""
        max_y, max_x = self.stdscr.getmaxyx()
        
        types = [
            ("ssh", "🔌 SSH Connection", "Secure Shell connection for remote terminal access"),
            ("rdp", "🖥️ RDP Connection", "Remote Desktop Protocol for Windows remote access")
        ]
        
        # Find index of current type
        selected = 0
        if current_type:
            for i, (type_id, _, _) in enumerate(types):
                if type_id == current_type:
                    selected = i
                    break
        
        while True:
            self.stdscr.clear()
            heading = "Select Connection Type".center(max_x)[:max_x-1]
            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
            
            # Display type options with descriptions
            y = current_y
            for i, (type_id, display_text, description) in enumerate(types):
                if y < max_y - 2:
                    # Display the main option
                    self.stdscr.addstr(y, 0, display_text,
                                     curses.A_REVERSE if selected == i else curses.A_NORMAL)
                    # Display the description
                    if y + 1 < max_y - 2:
                        self.stdscr.addstr(y + 1, 2, description, curses.A_DIM)
                    y += 3
            
            # Display instructions
            inst_y = max_y - 3
            if inst_y > current_y + 2:
                self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(types) - 1:
                selected += 1
            elif key == 10:  # Enter
                return types[selected][0]
            elif key == 27:  # Escape
                if current_type:
                    return current_type
                return types[0][0]  # Default to SSH