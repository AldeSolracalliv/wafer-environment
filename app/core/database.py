import sqlite3
from pathlib import Path
from typing import Any


class Database:
    """Small SQLite boundary for runtime metadata and future memory storage."""

    def __init__(self, path: Path):
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, description TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
                assigned_agent TEXT, result TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                capabilities TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tools (
                name TEXT PRIMARY KEY, description TEXT NOT NULL,
                parameter_schema TEXT NOT NULL, required_permission TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_permissions (
                agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                permission TEXT NOT NULL,
                tool_name TEXT NOT NULL DEFAULT '*',
                PRIMARY KEY (agent_id, permission, tool_name)
            );
            CREATE TABLE IF NOT EXISTS permission_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                permission TEXT,
                allowed INTEGER NOT NULL,
                reason TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cursor = self.connection.execute(sql, parameters)
        self.connection.commit()
        return cursor

    def close(self) -> None:
        self.connection.close()
