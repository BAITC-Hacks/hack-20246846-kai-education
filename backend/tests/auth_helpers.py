"""Real identity setup for tests; verification is a local fixture, never an API bypass."""
import sqlite3
from contextlib import closing
from uuid import uuid4

from fastapi.testclient import TestClient


ORIGIN = "http://localhost:5173"
PASSWORD = "Test-password-2026!"


def browser_client(app):
    return TestClient(app, headers={"Origin": ORIGIN})


def set_verification(path, user_id, status="verified"):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE users SET verification_status = ? WHERE id = ?", (status, user_id))


def register_and_login(client, path, *, role="business", verified=False, email=None):
    email = email or f"{uuid4().hex}@example.com"
    result = client.post("/auth/register", json={
        "name": "Test User", "email": email, "password": PASSWORD, "role": role,
    })
    assert result.status_code == 201, result.text
    user = result.json()
    if verified:
        set_verification(path, user["id"])
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()
