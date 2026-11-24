# SSH & RDP Connection Manager

A simple terminal-based connection manager for SSH and RDP connections.

## Features

- Manage SSH and RDP connections in one place
- RDP works on windows and WSL
- Organize connections in folders
- Secure credential storage
- Quick search and navigation
- Password management for RDP connections

## Status
- Tested on MacOS
- Windows 11 WSL 2
- Linux

## Installation

- Python 3.11 or higher

```bash
# Create and activate virtual environment (dev only)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install dependencies on windows without WSL install windows-curses
pip install windows-curses

# Install module to PATH
pip install -e .
```

## Usage

Start the manager:
```bash
sshManager
```

### Keyboard Controls

- `↑/↓`: Navigate connections
- `a`: Add connection
- `e`: Edit connection
- `d`: Delete connection
- `Tab`: Toggle SSH/RDP mode
- `p`: Password manager (bulk-update SSH and RDP passwords by username)
- `/`: Search
- `Enter` / `c`: Connect
- `m`: Master key / config encryption
- `q`: Quit

## Security

- All sensitive data can be encrypted optionally
- SSH keys and passwords stored securely
- Automatic RDP credential cleanup

## License

[MIT License](LICENSE)
