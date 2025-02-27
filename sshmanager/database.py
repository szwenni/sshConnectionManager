import pyodbc
import psycopg2
from typing import Dict, List
from datetime import datetime
import os

LOG_FILE = os.path.join(os.getcwd(), "ssh_manager_debug.log")

def log_debug(message: str):
    with open(LOG_FILE, 'a') as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {message}\n")

class Database:
    def __init__(self, db_type: str, config: dict):
        self.db_type = db_type
        self.db_config = config
        self.connections: Dict[str, List[dict]] = {}
        self.load_connections()

    def get_db_connection(self):
        if self.db_type == "mssql":
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.db_config['server']};"
                f"DATABASE={self.db_config['database']};"
                f"UID={self.db_config['username']};"
                f"PWD={self.db_config['password']}"
            )
            return pyodbc.connect(conn_str)
        else:
            return psycopg2.connect(
                host=self.db_config["server"],
                database=self.db_config["database"],
                user=self.db_config["username"],
                password=self.db_config["password"],
                port=self.db_config["port"]
            )

    def _create_tables(self):
        """Create the necessary tables if they don't exist."""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                create_table = """
                    CREATE TABLE IF NOT EXISTS Connections (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        folder VARCHAR(255),
                        ip VARCHAR(255) NOT NULL,
                        username VARCHAR(255),
                        auth_type VARCHAR(50) NOT NULL DEFAULT 'key',
                        port INTEGER DEFAULT 22,
                        type VARCHAR(50) NOT NULL DEFAULT 'ssh'
                    )
                """ if self.db_type == "postgres" else """
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='Connections')
                    CREATE TABLE Connections (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        folder VARCHAR(255),
                        ip VARCHAR(255) NOT NULL,
                        username VARCHAR(255),
                        auth_type VARCHAR(50) NOT NULL DEFAULT 'key',
                        port INTEGER DEFAULT 22,
                        type VARCHAR(50) NOT NULL DEFAULT 'ssh'
                    )
                """
                cursor.execute(create_table)
                conn.commit()
        except Exception as e:
            log_debug(f"Error creating tables: {str(e)}")
            raise

    def load_connections(self):
        self._create_tables()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM Connections")
                rows = cursor.fetchall()
                # Update self.connections in place instead of reassigning
                self.connections.clear()  # Clear existing data
                for row in rows:
                    folder = row[2] or "default"
                    if folder not in self.connections:
                        self.connections[folder] = []
                    self.connections[folder].append({
                        "id": row[0],
                        "name": row[1],
                        "folder": row[2],
                        "ip": row[3],
                        "username": row[4],
                        "auth_type": row[5],
                        "type": row[7],
                        "port": row[6],
                    })
                conn.commit()
                log_debug(f"Loaded connections: {self.connections}")
        except Exception as e:
            log_debug(f"Error loading connections: {str(e)}")
            raise

    def save_connection(self, conn_data: dict):
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                if "id" in conn_data:
                    # Update existing connection
                    query = """
                        UPDATE Connections 
                        SET name = %s, folder = %s, ip = %s, username = %s, auth_type = %s, type = %s, port = %s
                        WHERE id = %s
                    """ if self.db_type == "postgres" else """
                        UPDATE Connections 
                        SET name = ?, folder = ?, ip = ?, username = ?, auth_type = ?, type = ?, port = ?
                        WHERE id = ?
                    """
                    params = (
                        conn_data["name"],
                        conn_data.get("folder", "default"),
                        conn_data["ip"],
                        conn_data.get("username", ""),
                        conn_data.get("auth_type", "key"),
                        conn_data.get("type", "ssh"),
                        conn_data.get("port") if conn_data.get("type") == "ssh" else None,
                        conn_data["id"]
                    )
                    cursor.execute(query, params)
                else:
                    # Insert new connection
                    query = """
                        INSERT INTO Connections (name, folder, ip, username, auth_type, type, port)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """ if self.db_type == "postgres" else """
                        INSERT INTO Connections (name, folder, ip, username, auth_type, type, port)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                    params = (
                        conn_data["name"],
                        conn_data.get("folder", "default"),
                        conn_data["ip"],
                        conn_data.get("username", ""),
                        conn_data.get("auth_type", "key"),
                        conn_data.get("type", "ssh"),
                        conn_data.get("port") if conn_data.get("type") == "ssh" else None
                    )
                    cursor.execute(query, params)
                    if self.db_type == "postgres":
                        cursor.execute("SELECT currval(pg_get_serial_sequence('Connections', 'id'))")
                    else:
                        cursor.execute("SELECT @@IDENTITY")
                    conn_data["id"] = cursor.fetchone()[0]
                conn.commit()
                log_debug(f"Saved connection: {conn_data}")
        except Exception as e:
            log_debug(f"Error saving connection: {str(e)}")
            raise

    def remove_connection(self, conn_id: int):
        """Remove a connection from the database."""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Connections WHERE id = %s", (conn_id,))
            conn.commit()
            log_debug(f"Removed connection with id: {conn_id}")