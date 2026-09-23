"""Local, explicit demo tools. These do NOT verify documents or companies."""
import argparse
from pathlib import Path
import sys

from .auth_models import normalize_email
from .database import ChallengeStore, WorkflowConflict


def verify_demo_user(store: ChallengeStore, email: str):
    email = normalize_email(email)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id, verification_status FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            raise WorkflowConflict("Тестовый пользователь не найден.")
        if row[1] != "pending":
            raise WorkflowConflict("Демо-подтверждение доступно только для пользователя со статусом pending.")
        db.execute("UPDATE users SET verification_status = 'verified' WHERE id = ? AND verification_status = 'pending'",
                   (row[0],))
    return row[0]


def assign_legacy_challenge(store: ChallengeStore, challenge_id: str, email: str):
    email = normalize_email(email)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT id, role FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or user[1] != "business":
            raise WorkflowConflict("Нужен существующий аккаунт бизнеса.")
        challenge = db.execute("SELECT owner_id FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        if challenge is None:
            raise WorkflowConflict("Задача не найдена.")
        if challenge[0] is not None:
            raise WorkflowConflict("У задачи уже есть владелец. Переназначение запрещено.")
        db.execute("UPDATE challenges SET owner_id = ? WHERE id = ? AND owner_id IS NULL", (user[0], challenge_id))
    return user[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="MVP demo only: no real verification of a person or company.")
    parser.add_argument("--database", type=Path, default=Path(__file__).parent / "data" / "challenges.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Mark one pending test user as demo-verified.")
    verify.add_argument("--email", required=True)
    verify.add_argument("--demo", action="store_true", required=True, help="Acknowledge that this is not real verification.")
    assign = commands.add_parser("assign-legacy", help="Explicitly assign an ownerless legacy challenge to a business.")
    assign.add_argument("--challenge-id", required=True)
    assign.add_argument("--business-email", required=True)
    assign.add_argument("--demo", action="store_true", required=True)
    args = parser.parse_args(argv)
    # A typo must never silently create a second, empty database.
    if not args.database.is_file():
        parser.error("Existing database required. Start the backend first.")
    store = ChallengeStore(args.database)
    store.initialize()
    try:
        if args.command == "verify":
            verify_demo_user(store, args.email)
            print("DEMO ONLY: pending -> verified. No document, email or company check was performed.")
        else:
            assign_legacy_challenge(store, args.challenge_id, args.business_email)
            print("DEMO ONLY: ownerless legacy challenge assigned explicitly. Existing owners cannot be replaced.")
    except (WorkflowConflict, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
