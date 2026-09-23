"""Small SQLite store: one connection/transaction per operation."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from .models import ChallengeCreate


class ChallengeStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0 CHECK (published = 0)
            )""")

    def create(self, data: ChallengeCreate):
        challenge_id = str(uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO challenges (id, payload) VALUES (?, ?)",
                       (challenge_id, data.model_dump_json()))
        return challenge_id, data

    def get(self, challenge_id: str):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM challenges WHERE id = ?",
                             (challenge_id,)).fetchone()
        return ChallengeCreate.model_validate_json(row[0]) if row else None

    def update(self, challenge_id: str, changes: dict):
        with self.connection() as db:
            # Serialize read/merge/write so concurrent partial edits aren't lost.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM challenges WHERE id = ?",
                             (challenge_id,)).fetchone()
            if row is None:
                return None
            merged = json.loads(row[0])
            merged.update(changes)
            data = ChallengeCreate.model_validate(merged)
            db.execute("UPDATE challenges SET payload = ? WHERE id = ?",
                       (data.model_dump_json(), challenge_id))
        return data
