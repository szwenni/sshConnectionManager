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

    def load_connections(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            create_table = """
                CREATE TABLE IF NOT EXISTS Connections (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    folder VARCHAR(255),
                    ip VARCHAR(255),
                    username VARCHAR(255),
                    auth_type VARCHAR(50),
                    port INTEGER DEFAULT 22
                )
            """ if self.db_type == "postgres" else """
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='Connections')
                CREATE TABLE Connections (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    name VARCHAR(255),
                    folder VARCHAR(255),
                    ip VARCHAR(255),
                    username VARCHAR(255),
                    auth_type VARCHAR(50),
                    port INTEGER DEFAULT 22
                )
            """
            cursor.execute(create_table)
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
                    "port": row[6],
                })
            conn.commit()
            log_debug(f"Loaded connections: {self.connections}")

    def save_connection(self, conn_data: dict):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            if "id" in conn_data:
                query = """
                    UPDATE Connections SET name=%s, folder=%s, ip=%s, username=%s, auth_type=%s, port=%s
                    WHERE id=%s
                """ if self.db_type == "postgres" else """
                    UPDATE Connections SET name=?, folder=?, ip=?, username=?, auth_type=?, port=?
                    WHERE id=?
                """
                params = (conn_data["name"], conn_data.get("folder", "default"), conn_data["ip"], 
                         conn_data["username"], conn_data["auth_type"], conn_data.get("port", 22), conn_data["id"])
                cursor.execute(query, params)
            else:
                query = """
                    INSERT INTO Connections (name, folder, ip, username, auth_type, port)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """ if self.db_type == "postgres" else """
                    INSERT INTO Connections (name, folder, ip, username, auth_type, port)
                    VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (conn_data["name"], conn_data.get("folder", "default"), conn_data["ip"], 
                         conn_data["username"], conn_data["auth_type"], conn_data.get("port", 22))
                cursor.execute(query, params)
                if self.db_type == "postgres":
                    cursor.execute("SELECT currval(pg_get_serial_sequence('Connections', 'id'))")
                else:
                    cursor.execute("SELECT @@IDENTITY")
                conn_data["id"] = cursor.fetchone()[0]
            conn.commit()
            log_debug(f"Saved connection: {conn_data}")

    def remove_connection(self, conn_id: int):
        """Remove a connection from the database."""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Connections WHERE id = %s", (conn_id,))
            conn.commit()
            log_debug(f"Removed connection with id: {conn_id}")