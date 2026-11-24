import pyodbc
import psycopg2
from typing import Dict, List
from datetime import datetime
import os

from .config import CONFIG_DIR, LOG_FILE

MSSQL_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server",
)


def log_debug(message: str):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


class Database:
    def __init__(self, db_type: str, config: dict):
        self.db_type = db_type
        self.db_config = config
        self.connections: Dict[str, List[dict]] = {}
        self.load_connections()

    def get_db_connection(self):
        if self.db_type == "mssql":
            last_error = None
            server = self.db_config['server']
            port = self.db_config.get('port')
            if port and str(port) not in ("", "5432"):
                server = f"{server},{port}"
            for driver in MSSQL_DRIVERS:
                conn_str = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={server};"
                    f"DATABASE={self.db_config['database']};"
                    f"UID={self.db_config['username']};"
                    f"PWD={self.db_config['password']}"
                )
                try:
                    return pyodbc.connect(conn_str)
                except Exception as e:
                    last_error = e
                    continue
            raise last_error or Exception("No working SQL Server ODBC driver found")
        return psycopg2.connect(
            host=self.db_config["server"],
            database=self.db_config["database"],
            user=self.db_config["username"],
            password=self.db_config["password"],
            port=self.db_config.get("port", "5432")
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
                self._ensure_columns(cursor)
                conn.commit()
        except Exception as e:
            log_debug(f"Error creating tables: {str(e)}")
            raise

    def _ensure_columns(self, cursor):
        """Add columns introduced after the original schema."""
        if self.db_type == "postgres":
            cursor.execute("ALTER TABLE connections ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 22")
            cursor.execute("ALTER TABLE connections ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'ssh'")
            return

        for column, ddl in (
            ("port", "ALTER TABLE Connections ADD port INTEGER NULL"),
            ("type", "ALTER TABLE Connections ADD type VARCHAR(50) NOT NULL DEFAULT 'ssh'"),
        ):
            cursor.execute(
                """
                SELECT 1 FROM sys.columns c
                INNER JOIN sys.tables t ON c.object_id = t.object_id
                WHERE t.name = ? AND c.name = ?
                """,
                ("Connections", column),
            )
            if cursor.fetchone() is None:
                cursor.execute(ddl)

    def load_connections(self):
        self._create_tables()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, name, folder, ip, username, auth_type, port, type FROM Connections"
                )
                rows = cursor.fetchall()
                self.connections.clear()
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
                        "auth_type": row[5] or "key",
                        "port": row[6] if row[6] is not None else 22,
                        "type": row[7] or "ssh",
                    })
                log_debug(f"Loaded {sum(len(v) for v in self.connections.values())} connections")
        except Exception as e:
            log_debug(f"Error loading connections: {str(e)}")
            raise

    def save_connection(self, conn_data: dict):
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                if "id" in conn_data:
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
                    params = (
                        conn_data["name"],
                        conn_data.get("folder", "default"),
                        conn_data["ip"],
                        conn_data.get("username", ""),
                        conn_data.get("auth_type", "key"),
                        conn_data.get("type", "ssh"),
                        conn_data.get("port") if conn_data.get("type") == "ssh" else None
                    )
                    if self.db_type == "postgres":
                        cursor.execute(
                            """
                            INSERT INTO Connections (name, folder, ip, username, auth_type, type, port)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            params,
                        )
                        conn_data["id"] = cursor.fetchone()[0]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO Connections (name, folder, ip, username, auth_type, type, port)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            params,
                        )
                        cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS INT)")
                        conn_data["id"] = cursor.fetchone()[0]
                conn.commit()
                log_debug(f"Saved connection id={conn_data.get('id')} name={conn_data.get('name')}")
        except Exception as e:
            log_debug(f"Error saving connection: {str(e)}")
            raise

    def remove_connection(self, conn_id: int):
        """Remove a connection from the database."""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            if self.db_type == "postgres":
                cursor.execute("DELETE FROM Connections WHERE id = %s", (conn_id,))
            else:
                cursor.execute("DELETE FROM Connections WHERE id = ?", (conn_id,))
            conn.commit()
            log_debug(f"Removed connection with id: {conn_id}")
