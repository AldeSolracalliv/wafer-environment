from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import uuid

from app.core.database import Database


class MemoryKind(str, Enum):
    EXPERIENCE = "experience"
    FACT = "fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    kind: MemoryKind
    content: str
    created_at: str


class MemoryManager:
    """Minimal explicit memory store; no embeddings or semantic retrieval."""

    def __init__(self, database: Database):
        self.database = database

    def list_entries(self) -> list[MemoryEntry]:
        rows = self.database.connection.execute("SELECT * FROM memory_entries ORDER BY created_at").fetchall()
        return [MemoryEntry(row["id"], MemoryKind(row["kind"]), row["content"], row["created_at"]) for row in rows]

    def count(self) -> int:
        return self.database.connection.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
