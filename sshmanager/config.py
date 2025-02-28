import os
import json
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

HOME_DIR = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME_DIR, ".sshConnectionManager")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SALT_FILE = os.path.join(CONFIG_DIR, ".salt")

# Old config files
OLD_DB_CONFIG_FILE = os.path.join(CONFIG_DIR, "db_config.json")
OLD_KEY_LOCATIONS_FILE = os.path.join(CONFIG_DIR, "key_locations.json")
OLD_PASSWORDS_FILE = os.path.join(CONFIG_DIR, "passwords.json")

class Config:
    def __init__(self):
        self.config = {
            "db": {"server": "", "database": "", "username": "", "password": "", "port": "5432", "type": "postgres"},
            "passwords": {},  # For SSH password auth
            "key_paths": {},  # For SSH key paths
            "key_passwords": {},  # For SSH key passwords
            "rdp_credentials": {}  # For RDP credentials (overrides DB)
        }
        self.fernet = None
        self.is_encrypted = False
        self._ensure_salt()
        self.load_config()
        self.masterkey = None
        
        # Initialize all sections if they don't exist
        if 'master_key' not in self.config:
            self.config['master_key'] = None
        if 'passwords' not in self.config:
            self.config['passwords'] = {}
        if 'key_paths' not in self.config:
            self.config['key_paths'] = {}
        if 'rdp_credentials' not in self.config:
            self.config['rdp_credentials'] = {}

    def _ensure_salt(self):
        """Ensure salt exists for key derivation."""
        os.makedirs(CONFIG_DIR, exist_ok=True)  # Create config directory if it doesn't exist
        if not os.path.exists(SALT_FILE):
            with open(SALT_FILE, 'wb') as f:
                f.write(os.urandom(16))

    def _get_salt(self):
        """Get the salt for key derivation."""
        with open(SALT_FILE, 'rb') as f:
            return f.read()

    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._get_salt(),
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def set_master_password(self, password: str):
        """Set or change master password."""
        if not password:
            self.fernet = None
            self.is_encrypted = False
            self.masterkey = None
        else:
            self.masterkey = password
            key = self._derive_key(password)
            self.fernet = Fernet(key)
            self.is_encrypted = True
        self._save_config()

    def check_master_password(self, password: str) -> bool:
        """Check if master password is correct."""
        try:
            key = self._derive_key(password)
            fernet = Fernet(key)
            with open(CONFIG_FILE, 'rb') as f:
                encrypted_data = f.read()
            fernet.decrypt(encrypted_data)
            self.fernet = fernet
            self.is_encrypted = True  # Set encryption state when password is correct
            return True
        except:
            return False

    def is_config_encrypted(self) -> bool:
        """Check if config file is encrypted."""
        if not os.path.exists(CONFIG_FILE):
            return False
        try:
            with open(CONFIG_FILE, 'r') as f:
                json.load(f)
            return False
        except json.JSONDecodeError:
            return True
        except:
            return False

    def load_config(self, password: str = None):
        """Load configuration from file or migrate from old config."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        
        # Check if config exists and is encrypted
        if os.path.exists(CONFIG_FILE):
            is_encrypted = self.is_config_encrypted()
            if is_encrypted:
                if not password:
                    return False
                if not self.check_master_password(password):
                    return False
                
                # Decrypt and load config (is_encrypted and fernet are already set by check_master_password)
                with open(CONFIG_FILE, 'rb') as f:
                    encrypted_data = f.read()
                decrypted_data = self.fernet.decrypt(encrypted_data)
                self.config = json.loads(decrypted_data)
                self.masterkey = password
                return True
            else:
                self.is_encrypted = False  # Explicitly set to false for unencrypted config
                self.fernet = None
                try:
                    with open(CONFIG_FILE, 'r') as f:
                        self.config = json.load(f)
                    return True
                except json.JSONDecodeError:
                    self._migrate_old_config()
                    return True
        else:
            # If new config doesn't exist, try to migrate from old config
            self.is_encrypted = False  # New config starts unencrypted
            self.fernet = None
            self._migrate_old_config()
            return True

    def _save_config(self):
        """Save configuration to file, encrypting if necessary."""
        config_data = json.dumps(self.config).encode()
        
        if self.is_encrypted and self.fernet:
            encrypted_data = self.fernet.encrypt(config_data)
            with open(CONFIG_FILE, 'wb') as f:
                f.write(encrypted_data)
        else:
            with open(CONFIG_FILE, 'w') as f:
                f.write(config_data.decode())

    def _migrate_old_config(self):
        """Migrate configuration from old separate files to new unified config."""
        config_updated = False
        
        # Migrate DB config
        if os.path.exists(OLD_DB_CONFIG_FILE):
            try:
                with open(OLD_DB_CONFIG_FILE, 'r') as f:
                    self.config["db"] = json.load(f)
                    config_updated = True
            except json.JSONDecodeError:
                pass  # Ignore invalid JSON
                
        # Migrate key locations
        if os.path.exists(OLD_KEY_LOCATIONS_FILE):
            try:
                with open(OLD_KEY_LOCATIONS_FILE, 'r') as f:
                    self.config["key_paths"] = json.load(f)
                    config_updated = True
            except json.JSONDecodeError:
                pass
                
        # Migrate passwords
        if os.path.exists(OLD_PASSWORDS_FILE):
            try:
                with open(OLD_PASSWORDS_FILE, 'r') as f:
                    self.config["passwords"] = json.load(f)
                    config_updated = True
            except json.JSONDecodeError:
                pass
        
        # If any old config was migrated, save the new config
        if config_updated:
            self._save_config()
            
            # Optionally backup and remove old config files
            for old_file in [OLD_DB_CONFIG_FILE, OLD_KEY_LOCATIONS_FILE, OLD_PASSWORDS_FILE]:
                if os.path.exists(old_file):
                    backup_file = old_file + '.bak'
                    os.rename(old_file, backup_file)

    def _ensure_section(self, section):
        """Ensure a section exists in the config."""
        if section not in self.config:
            self.config[section] = {}
            self._save_config()

    def set_rdp_credentials(self, conn_id, username, password=None):
        """Set RDP credentials for a connection."""
        conn_id = str(conn_id)
        self._ensure_section("rdp_credentials")
        self.config["rdp_credentials"][conn_id] = {
            "username": username,
            "password": password
        }
        self._save_config()

    def set_password(self, conn_id, password):
        """Set password for a connection."""
        conn_id = str(conn_id)
        self._ensure_section("passwords")
        self.config["passwords"][conn_id] = password
        self._save_config()

    def set_key_path(self, conn_id, key_path):
        """Set key path for a connection."""
        conn_id = str(conn_id)
        self._ensure_section("key_paths")
        self.config["key_paths"][conn_id] = key_path
        self._save_config()

    def set_key_password(self, conn_id, key_password):
        """Set key password for a connection."""
        conn_id = str(conn_id)
        self._ensure_section("key_passwords")
        self.config["key_passwords"][conn_id] = key_password
        self._save_config()

    def _init_config(self):
        """Initialize config with all required sections."""
        sections = ["master_key", "passwords", "key_paths", "key_passwords", "rdp_credentials"]
        for section in sections:
            self._ensure_section(section)

    def get_key_path(self, conn_id, with_default=True):
        """Get the SSH key path for a connection."""
        if with_default:
            return self.config["key_paths"].get(str(conn_id), os.path.join(HOME_DIR, ".ssh", "id_rsa"))
        else:
            return self.config["key_paths"].get(str(conn_id), None)

    def get_key_password(self, conn_id):
        """Get the SSH key password for a connection."""
        return self.config["key_passwords"].get(str(conn_id))

    def get_password(self, conn_id):
        return self.config["passwords"].get(str(conn_id), "")

    def get_rdp_credentials(self, conn_id):
        """Get RDP credentials for a connection."""
        conn_id = str(conn_id)
        creds = self.config["rdp_credentials"].get(conn_id, {})
        return creds.get("username"), creds.get("password")

    def remove_connection_config(self, conn_id):
        """Remove all configuration data for a connection."""
        str_id = str(conn_id)
        # Remove from all sections, ignore if not found
        self.config.get('passwords', {}).pop(str_id, None)
        self.config.get('key_paths', {}).pop(str_id, None)
        self.config.get('key_passwords', {}).pop(str_id, None)
        self.config.get('rdp_credentials', {}).pop(str_id, None)
        self._save_config()

    def delete_connection_data(self, conn_id):
        """Delete all stored data for a connection."""
        self.remove_connection_config(conn_id)