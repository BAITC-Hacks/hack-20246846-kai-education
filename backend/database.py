"""Small SQLite store: one connection/transaction per operation."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from .models import ChallengeCreate


class WorkflowConflict(Exception):
    pass


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
            db.execute("""CREATE TABLE IF NOT EXISTS ai_workflows (
                id TEXT PRIMARY KEY,
                challenge_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('analysis', 'proposal')),
                base_payload TEXT NOT NULL,
                result TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0
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

    def save_workflow(self, record_id, challenge_id, kind, base, result):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT payload FROM challenges WHERE id = ?",
                                 (challenge_id,)).fetchone()
            if not current or json.loads(current[0]) != base.model_dump():
                raise WorkflowConflict("Задача изменилась. Повторите анализ.")
            db.execute("""INSERT INTO ai_workflows
                (id, challenge_id, kind, base_payload, result) VALUES (?, ?, ?, ?, ?)""",
                (record_id, challenge_id, kind, base.model_dump_json(),
                 json.dumps(result, ensure_ascii=False)))

    def get_workflow(self, record_id, challenge_id, kind):
        with self.connection() as db:
            row = db.execute("""SELECT base_payload, result, confirmed FROM ai_workflows
                WHERE id = ? AND challenge_id = ? AND kind = ?""",
                (record_id, challenge_id, kind)).fetchone()
        if row is None:
            return None
        return {"base": json.loads(row[0]), "result": json.loads(row[1]), "confirmed": bool(row[2])}

    def confirm_proposal(self, proposal_id, challenge_id, edits):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            proposal = db.execute("""SELECT base_payload, result, confirmed FROM ai_workflows
                WHERE id = ? AND challenge_id = ? AND kind = 'proposal'""",
                (proposal_id, challenge_id)).fetchone()
            if proposal is None:
                return None
            if proposal[2]:
                raise WorkflowConflict("Предложение уже подтверждено.")
            current = db.execute("SELECT payload FROM challenges WHERE id = ?",
                                 (challenge_id,)).fetchone()
            if not current or json.loads(current[0]) != json.loads(proposal[0]):
                raise WorkflowConflict("Задача изменилась. Повторите анализ и создание предложения.")
            card = json.loads(proposal[1])["proposed_card"]
            card.update(edits)
            saved = ChallengeCreate(draft=json.loads(current[0])["draft"], **card)
            db.execute("UPDATE challenges SET payload = ? WHERE id = ?",
                       (saved.model_dump_json(), challenge_id))
            db.execute("UPDATE ai_workflows SET confirmed = 1 WHERE id = ?", (proposal_id,))
        return saved
