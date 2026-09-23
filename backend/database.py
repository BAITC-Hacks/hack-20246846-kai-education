"""Small SQLite store: one connection/transaction per operation."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from .models import ChallengeCreate
from .proposal_models import Proposal, ProposalCreate


class WorkflowConflict(Exception):
    pass


class ChallengeStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'challenges'").fetchone()
            if schema and "CHECK (published = 0)" in schema[0]:
                # Stage 1 allowed only drafts. Rebuild atomically, preserving IDs/payloads.
                db.execute("""CREATE TABLE challenges_v3 (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1))
                )""")
                db.execute("INSERT INTO challenges_v3 SELECT id, payload, published FROM challenges")
                db.execute("DROP TABLE challenges")
                db.execute("ALTER TABLE challenges_v3 RENAME TO challenges")
            db.execute("""CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1))
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS student_proposals (
                id TEXT PRIMARY KEY,
                challenge_id TEXT NOT NULL REFERENCES challenges(id),
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'rejected'))
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_accepted_per_challenge
                ON student_proposals(challenge_id) WHERE status = 'accepted'""")
            db.execute("""CREATE INDEX IF NOT EXISTS proposals_by_challenge
                ON student_proposals(challenge_id)""")
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

    def is_published(self, challenge_id):
        with self.connection() as db:
            row = db.execute("SELECT published FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        return bool(row and row[0])

    def publish(self, challenge_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE challenges SET published = 1 WHERE id = ?", (challenge_id,))
        return ChallengeCreate.model_validate_json(row[0])

    def published_challenges(self):
        with self.connection() as db:
            rows = db.execute("SELECT id, payload FROM challenges WHERE published = 1 ORDER BY id").fetchall()
        return [(row[0], ChallengeCreate.model_validate_json(row[1])) for row in rows]

    @staticmethod
    def proposal_from_row(row):
        return Proposal(id=row[0], challenge_id=row[1], status=row[3], **json.loads(row[2]))

    def create_student_proposal(self, challenge_id, data: ProposalCreate):
        proposal_id = str(uuid4())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT published FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
            if row is None:
                return None
            if not row[0]:
                raise WorkflowConflict("Предложение можно отправить только для опубликованной задачи.")
            db.execute("INSERT INTO student_proposals (id, challenge_id, payload) VALUES (?, ?, ?)",
                       (proposal_id, challenge_id, data.model_dump_json()))
        return Proposal(id=proposal_id, challenge_id=challenge_id, status="pending", **data.model_dump())

    def list_student_proposals(self, challenge_id):
        with self.connection() as db:
            rows = db.execute("""SELECT id, challenge_id, payload, status FROM student_proposals
                WHERE challenge_id = ? ORDER BY rowid""", (challenge_id,)).fetchall()
        return [self.proposal_from_row(row) for row in rows]

    def decide_student_proposal(self, challenge_id, proposal_id, decision):
        if decision not in ("accepted", "rejected"):
            raise ValueError("Unknown decision")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT id, challenge_id, payload, status FROM student_proposals
                WHERE id = ? AND challenge_id = ?""", (proposal_id, challenge_id)).fetchone()
            if row is None:
                return None
            if row[3] == decision:
                return self.proposal_from_row(row)
            if row[3] != "pending":
                raise WorkflowConflict("Решение уже принято. Изменить accepted/rejected нельзя.")
            if decision == "accepted" and db.execute(
                "SELECT 1 FROM student_proposals WHERE challenge_id = ? AND status = 'accepted'",
                (challenge_id,),
            ).fetchone():
                raise WorkflowConflict("Для этой задачи уже принята другая команда.")
            db.execute("UPDATE student_proposals SET status = ? WHERE id = ?", (decision, proposal_id))
        return self.proposal_from_row((row[0], row[1], row[2], decision))

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
