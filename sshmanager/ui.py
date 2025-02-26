import curses
from typing import Dict, List
from collections import defaultdict

class UI:
    def __init__(self, stdscr, connections: Dict[str, List[dict]]):
        self.stdscr = stdscr
        self.connections = connections  # Reference to self.db.connections
        self.selected = 0  # Index of selected connection (not row)
        self.connection_rows = []  # List to map row numbers to connections
        self.folder_structure = {}  # Nested folder structure
        self.search_mode = False
        self.search_term = ""
        curses.curs_set(0)
        self._build_folder_structure()

    def _build_folder_structure(self):
        """Build nested folder structure from flat folder paths."""
        self.folder_structure = {}
        
        # First, add the root folder if it doesn't exist
        if '' not in self.connections and 'default' not in self.connections:
            self.folder_structure['__root'] = {'__contents': [], '__folders': {}}
            
        # Process each folder path
        for folder_path, conns in self.connections.items():
            current = self.folder_structure
            
            # Handle default or empty folder as root
            if not folder_path or folder_path == 'default':
                if '__root' not in self.folder_structure:
                    self.folder_structure['__root'] = {'__contents': [], '__folders': {}}
                self.folder_structure['__root']['__contents'].extend(conns)
                continue
                
            # Split path and process each part
            parts = folder_path.split('/')
            
            # Process each part of the path
            current_path = ""
            for i, part in enumerate(parts):
                current_path = f"{current_path}/{part}" if current_path else part
                
                # Create folder if it doesn't exist
                if part not in current:
                    current[part] = {'__contents': [], '__folders': {}}
                
                # If this is the last part, add connections here
                if i == len(parts) - 1:
                    current[part]['__contents'].extend(conns)
                
                # Move to the next level
                current = current[part]['__folders']

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

        filtered = {'__contents': [], '__folders': {}}
        
        # Filter contents
        filtered['__contents'] = [
            conn for conn in folder_dict.get('__contents', [])
            if self._matches_search(conn)
        ]
        
        # Filter subfolders
        for folder_name, subfolder in folder_dict.get('__folders', {}).items():
            filtered_subfolder = self._filter_folder_structure(subfolder)
            if filtered_subfolder['__contents'] or filtered_subfolder['__folders']:
                filtered['__folders'][folder_name] = filtered_subfolder
                
        return filtered

    def _display_folder_contents(self, folder_dict, path="", level=0, row=2, connection_index=0):
        """Recursively display folder contents with proper indentation."""
        max_y, max_x = self.stdscr.getmaxyx()
        indent = "  " * level

        # If in search mode, filter the folder structure
        display_dict = self._filter_folder_structure(folder_dict) if self.search_mode else folder_dict

        # Sort connections by name for consistent display
        sorted_contents = sorted(display_dict.get('__contents', []), key=lambda x: x['name'])
        
        # Display contents of current folder
        for conn in sorted_contents:
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
        sorted_folders = sorted(display_dict.get('__folders', {}).items())
        
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
        heading = "SSH Connection Manager".center(max_x)[:max_x-1]
        self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
        
        # Reset connection rows mapping
        self.connection_rows = []
        
        # Start displaying content from row 2
        current_row = 2
        
        # Display "Connections" root folder
        self.stdscr.addstr(current_row, 0, "📁 Connections")
        current_row += 1
        
        # Display root contents first
        if '__root' in self.folder_structure:
            current_row, _ = self._display_folder_contents(
                self.folder_structure['__root'], "", 1, current_row, len(self.connection_rows)
            )
        
        # Sort folders to ensure consistent display order
        sorted_folders = sorted((k, v) for k, v in self.folder_structure.items() if k != '__root')
        
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

    def display_menu(self, max_y):
        """Display the menu or search bar at the bottom of the screen."""
        max_x = self.stdscr.getmaxyx()[1]
        
        try:
            if self.search_mode:
                # Display search bar
                search_prompt = f"Search (ESC to exit): {self.search_term}"
                # Ensure we don't write to the last character position
                self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))  # Clear the line
                self.stdscr.addstr(max_y - 1, 0, search_prompt[:max_x - 1], curses.A_REVERSE)
            else:
                # Display regular menu
                menu = "a=Add  e=Edit  r=Remove  c=Connect  m=Master Key  /=Search  q=Quit"
                padded_menu = menu.center(max_x - 1)[:max_x - 1]  # Leave last character
                self.stdscr.addstr(max_y - 1, 0, padded_menu, curses.A_REVERSE)
        except curses.error:
            # Safely handle any curses errors
            pass

    def get_selected_connection(self):
        if 0 <= self.selected < len(self.connection_rows):
            folder, conn = self.connection_rows[self.selected]
            return conn
        return None

    def handle_search_input(self, char):
        """Handle input while in search mode."""
        if char == 27:  # Escape
            self.search_mode = False
            self.search_term = ""
            return True
        elif char == 10:  # Enter
            self.search_mode = False
            return True
        elif char == curses.KEY_BACKSPACE or char == 127:  # Backspace
            self.search_term = self.search_term[:-1]
            return True
        elif 32 <= char <= 126:  # Printable characters
            self.search_term += chr(char)
            return True
        return False

    def _get_all_folders(self):
        """Get a list of all folders with their hierarchy levels."""
        folders = []
        folder_levels = {}
        seen_folders = set()  # Track unique folder paths
        
        def traverse_folders(structure, current_path="", level=0):
            for folder_name, folder_data in sorted(structure.items()):
                if folder_name != "__root":
                    full_path = f"{current_path}/{folder_name}" if current_path else folder_name
                    # Only add if we haven't seen this path before
                    if full_path not in seen_folders:
                        folders.append(full_path)
                        folder_levels[full_path] = level
                        seen_folders.add(full_path)
                    traverse_folders(folder_data.get('__folders', {}), full_path, level + 1)
        
        traverse_folders(self.folder_structure)
        return folders, folder_levels

    def select_folder(self, current_y=1, current_folder=None):
        """Interactive folder selector."""
        max_y, max_x = self.stdscr.getmaxyx()
        folders, folder_levels = self._get_all_folders()
        
        # Find the index of the current folder
        selected = 1  # Default to "Connections" (previously "Default")
        if current_folder:
            if current_folder == "default":
                selected = 1
            else:
                try:
                    selected = folders.index(current_folder) + 2  # +2 for Create New and Connections
                except ValueError:
                    selected = 1
        
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
                level = folder_levels[folder]
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

    def select_auth_type(self, current_y=1, current_auth=None):
        """Interactive authentication type selector."""
        max_y, max_x = self.stdscr.getmaxyx()
        
        auth_types = [
            ("key", "🔑 SSH Key Authentication", "Most secure, uses SSH key pairs"),
            ("password", "🔒 Password Authentication", "Less secure, uses password")
        ]
        
        # Find index of current auth type
        selected = 0
        if current_auth:
            for i, (auth_type, _, _) in enumerate(auth_types):
                if auth_type == current_auth:
                    selected = i
                    break
        
        while True:
            self.stdscr.clear()
            heading = "Select Authentication Method".center(max_x)[:max_x-1]
            self.stdscr.addstr(0, 0, heading, curses.A_REVERSE)
            
            # Display auth type options with descriptions
            y = current_y
            for i, (auth_type, display_text, description) in enumerate(auth_types):
                if y < max_y - 2:
                    # Display the main option
                    self.stdscr.addstr(y, 0, display_text,
                                     curses.A_REVERSE if selected == i else curses.A_NORMAL)
                    # Display the description
                    if y + 1 < max_y - 2:
                        self.stdscr.addstr(y + 1, 2, description, curses.A_DIM)
                    y += 3  # Space for next option
            
            # Display instructions
            inst_y = max_y - 3
            if inst_y > current_y + len(auth_types) * 3:
                self.stdscr.addstr(inst_y, 0, "↑↓: Navigate  Enter: Select  Esc: Cancel", curses.A_DIM)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(auth_types) - 1:
                selected += 1
            elif key == 10:  # Enter
                auth_type = auth_types[selected][0]
                return auth_type
            elif key == 27:  # Escape
                if current_auth:
                    return current_auth
                return auth_types[0][0]  # Default to SSH key
        
        return auth_types[0][0]  # Default to SSH key