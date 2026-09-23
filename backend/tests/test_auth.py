"""Identity boundaries exercised through HTTP, without paid AI or real user data."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from backend.main import create_app
from backend.models import ChallengeCreate
from backend.tests.auth_helpers import (
    ORIGIN, PASSWORD, browser_client, register_and_login, set_verification,
)


COOKIE = "kaibridge_session"
TEAM = {"team_name": "Verified team", "skills": "Python, React",
        "solution_idea": "FAQ assistant", "plan": "Prepare, build, test",
        "estimated_time": "5 hours"}


class AuthTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "identity.sqlite3"
        self.provider = MagicMock()
        self.provider.analyze.side_effect = AssertionError("Unexpected AI request")
        self.provider.propose.side_effect = AssertionError("Unexpected AI request")
        self.client = self.new_client()

    def new_client(self):
        return self.enterContext(browser_client(create_app(self.path, self.provider)))

    def user(self, *, role="business", verified=False, client=None):
        client = client or self.new_client()
        user = register_and_login(client, self.path, role=role, verified=verified)
        return client, user

    def draft(self, client):
        result = client.post("/challenges", json={"draft": "Shop needs an FAQ assistant"})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def published(self):
        owner, user = self.user(verified=True)
        card = self.draft(owner)
        result = owner.post(f'/challenges/{card["id"]}/publish', json={"confirmed": True})
        self.assertEqual(result.status_code, 200, result.text)
        return owner, user, result.json()

    def test_registration_both_roles_public_fields_and_no_automatic_login(self):
        profiles = [
            {"role": "student", "university": "Demo University"},
            {"role": "business", "company_name": "Demo Shop", "position": "Owner",
             "company_industry": "Retail", "company_website": "https://example.com"},
        ]
        for fields in profiles:
            with self.subTest(role=fields["role"]):
                response = self.client.post("/auth/register", json={
                    "name": "Test Person", "email": f'{fields["role"]}@example.com',
                    "password": PASSWORD, **fields,
                })
                self.assertEqual(response.status_code, 201, response.text)
                user = response.json()
                self.assertEqual(user["name"], "Test Person")
                self.assertEqual(user["role"], fields["role"])
                self.assertEqual(user["verification_status"], "unverified")
                self.assertTrue(user["id"])
                self.assertTrue(user["created_at"])
                for key, value in fields.items():
                    if key == "company_website":
                        self.assertEqual(user[key].rstrip("/"), value)
                    else:
                        self.assertEqual(user[key], value)
                self.assertNotIn("password", user)
                self.assertNotIn("password_hash", user)
                self.assertNotIn(PASSWORD, response.text)
                self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_duplicate_email_is_case_insensitive(self):
        payload = {"name": "Test", "role": "student", "email": "Unique@Example.com", "password": PASSWORD}
        self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 201)
        duplicate = self.client.post("/auth/register", json={**payload, "email": " unique@example.COM "})
        self.assertEqual(duplicate.status_code, 409)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_password_hash_uses_random_salt_and_strong_pbkdf2(self):
        self.user()
        self.user()
        with closing(sqlite3.connect(self.path)) as db:
            hashes = [row[0] for row in db.execute("SELECT password_hash FROM users")]
        self.assertEqual(len(hashes), 2)
        self.assertNotEqual(hashes[0], hashes[1])
        for encoded in hashes:
            algorithm, iterations, salt, digest = encoded.split("$")
            self.assertEqual(algorithm, "pbkdf2_sha256")
            self.assertGreaterEqual(int(iterations), 600000)
            self.assertGreaterEqual(len(bytes.fromhex(salt)), 16)
            calculated = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), bytes.fromhex(salt), int(iterations)).hex()
            self.assertEqual(calculated, digest)
            self.assertNotIn(PASSWORD, encoded)
        self.assertNotIn(PASSWORD.encode(), self.path.read_bytes())

    def test_login_and_me_use_httponly_cookie_and_hashed_server_session(self):
        payload = {"name": "Test", "role": "business", "email": "login@example.com", "password": PASSWORD}
        self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 201)
        response = self.client.post("/auth/login", json={"email": "LOGIN@EXAMPLE.COM", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)
        token = self.client.cookies.get(COOKIE)
        self.assertTrue(token)
        self.assertEqual(self.client.get("/auth/me").json(), response.json())
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn("password_hash", response.json())
        self.assertNotIn(token, response.text)
        with closing(sqlite3.connect(self.path)) as db:
            session = db.execute("SELECT token_hash, created_at, expires_at FROM auth_sessions").fetchone()
        self.assertEqual(session[0], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(session[0], token)
        self.assertEqual(session[2] - session[1], 12 * 60 * 60)

    def test_invalid_password_and_unknown_email_return_same_safe_error(self):
        client, user = self.user()
        wrong_password = "Wrong-test-password!"
        wrong = client.post("/auth/login", json={"email": user["email"], "password": wrong_password})
        unknown = self.client.post("/auth/login", json={"email": "absent@example.com", "password": wrong_password})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertNotIn(wrong_password, wrong.text)
        self.assertNotIn(user["email"], wrong.text)

    def test_password_whitespace_is_preserved(self):
        password = "  Space-sensitive-password!  "
        self.assertEqual(self.client.post("/auth/register", json={
            "name": "Test", "email": "spaces@example.com", "password": password, "role": "student",
        }).status_code, 201)
        self.assertEqual(self.client.post("/auth/login", json={
            "email": "spaces@example.com", "password": password.strip(),
        }).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={
            "email": "spaces@example.com", "password": password,
        }).status_code, 200)

    def test_validation_never_echoes_password_or_allows_privilege_injection(self):
        body = {"name": "Test", "email": "test@example.com", "password": PASSWORD, "role": "business"}
        for changes in [
            {"verification_status": "verified"}, {"password_hash": "attacker"},
            {"role": "admin"}, {"password": "pW9!zQ"}, {"password": "x" * 129},
            {"email": "not-an-email"},
        ]:
            with self.subTest(fields=list(changes)):
                response = self.client.post("/auth/register", json={**body, **changes})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn('"input"', response.text)
                self.assertNotIn(PASSWORD, response.text)
                if "password" in changes:
                    self.assertNotIn(changes["password"], response.text)
        invalid_login = self.client.post("/auth/login", json={"email": "bad", "password": PASSWORD})
        self.assertEqual(invalid_login.status_code, 422)
        self.assertNotIn(PASSWORD, invalid_login.text)

    def test_unauthenticated_protected_actions_require_login(self):
        owner, _, card = self.published()
        student, _ = self.user(role="student", verified=True)
        proposal = student.post(f'/challenges/{card["id"]}/proposals', json=TEAM).json()
        url = f'/challenges/{card["id"]}'
        requests = [
            ("post", "/challenges", {"draft": "Anonymous"}),
            ("patch", url, {"title": "Unauthorized"}),
            ("post", url + "/publish", {"confirmed": True}),
            ("post", url + "/proposals", TEAM),
            ("post", url + f'/proposals/{proposal["id"]}/accept', None),
            ("post", url + f'/proposals/{proposal["id"]}/reject', None),
            ("post", url + "/analysis", None),
            ("post", url + "/readiness", None),
        ]
        for method, endpoint, body in requests:
            with self.subTest(endpoint=endpoint):
                response = getattr(self.client, method)(endpoint, **({"json": body} if body is not None else {}))
                self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.client.get(url + "/proposals").status_code, 401)
        self.assertEqual(owner.get(url + "/proposals").json()[0]["status"], "pending")

    def test_unverified_pending_rejected_student_cannot_submit(self):
        _, _, card = self.published()
        student, user = self.user(role="student")
        for state in ("unverified", "pending", "rejected"):
            set_verification(self.path, user["id"], state)
            response = student.post(f'/challenges/{card["id"]}/proposals', json=TEAM)
            self.assertEqual(response.status_code, 403, response.text)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM student_proposals").fetchone()[0], 0)

    def test_verified_student_can_submit(self):
        owner, _, card = self.published()
        student, _ = self.user(role="student", verified=True)
        url = f'/challenges/{card["id"]}/proposals'
        response = student.post(url, json=TEAM)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(owner.get(url).json(), [response.json()])

    def test_student_cannot_create_edit_or_publish_challenge(self):
        owner, _ = self.user(verified=True)
        card = self.draft(owner)
        student, _ = self.user(role="student", verified=True)
        url = f'/challenges/{card["id"]}'
        self.assertEqual(student.post("/challenges", json={"draft": "Forbidden"}).status_code, 403)
        self.assertEqual(student.patch(url, json={"title": "Forbidden"}).status_code, 403)
        self.assertEqual(student.post(url + "/publish", json={"confirmed": True}).status_code, 403)
        self.assertFalse(owner.get(url).json()["published"])

    def test_unverified_business_can_prepare_but_not_publish(self):
        owner, user = self.user()
        card = self.draft(owner)
        url = f'/challenges/{card["id"]}'
        self.assertEqual(owner.patch(url, json={"context": "Shop"}).status_code, 200)
        self.assertEqual(owner.post(url + "/readiness").json()["readiness_score"], 10)
        for state in ("unverified", "pending", "rejected"):
            set_verification(self.path, user["id"], state)
            self.assertEqual(owner.post(url + "/publish", json={"confirmed": True}).status_code, 403)
        self.assertFalse(owner.get(url).json()["published"])

    def test_verified_business_can_publish_even_with_zero_score(self):
        owner, _, card = self.published()
        self.assertTrue(card["published"])
        self.assertEqual(card["readiness_score"], 0)
        self.assertEqual(owner.get(f'/challenges/{card["id"]}').json(), card)

    def test_business_cannot_submit_student_proposal(self):
        _, _, card = self.published()
        business, _ = self.user(verified=True)
        self.assertEqual(business.post(f'/challenges/{card["id"]}/proposals', json=TEAM).status_code, 403)

    def test_other_business_cannot_manage_owner_proposals_or_card(self):
        owner, _, card = self.published()
        other, _ = self.user(verified=True)
        student, _ = self.user(role="student", verified=True)
        url = f'/challenges/{card["id"]}'
        proposal = student.post(url + "/proposals", json=TEAM).json()
        for action in ("accept", "reject"):
            self.assertEqual(other.post(url + f'/proposals/{proposal["id"]}/{action}').status_code, 403)
        self.assertEqual(other.get(url + "/proposals").status_code, 403)
        self.assertEqual(other.patch(url, json={"contact": "Intruder"}).status_code, 403)
        self.assertEqual(other.post(url + "/publish", json={"confirmed": True}).status_code, 403)
        self.assertEqual(other.post(url + "/analysis").status_code, 403)
        self.assertEqual(other.post(url + "/readiness").status_code, 403)
        self.assertEqual(owner.get(url).json(), card)
        self.assertEqual(owner.get(url + "/proposals").json()[0]["status"], "pending")
        self.provider.analyze.assert_not_called()
        self.assertEqual(owner.post(url + f'/proposals/{proposal["id"]}/accept').status_code, 200)

    def test_unverified_owner_cannot_accept_or_reject(self):
        owner, user, card = self.published()
        student, _ = self.user(role="student", verified=True)
        url = f'/challenges/{card["id"]}'
        proposal = student.post(url + "/proposals", json=TEAM).json()
        set_verification(self.path, user["id"], "pending")
        for action in ("accept", "reject"):
            self.assertEqual(owner.post(url + f'/proposals/{proposal["id"]}/{action}').status_code, 403)
        self.assertEqual(owner.get(url + "/proposals").json()[0]["status"], "pending")

    def test_logout_revokes_copied_cookie(self):
        client, _ = self.user()
        replay = self.new_client()
        replay.cookies.update(client.cookies)
        self.assertEqual(client.post("/auth/logout").status_code, 204)
        self.assertEqual(client.get("/auth/me").status_code, 401)
        self.assertEqual(replay.get("/auth/me").status_code, 401)
        self.assertEqual(client.post("/auth/logout").status_code, 204)

    def test_expired_or_forged_session_is_rejected(self):
        client, _ = self.user()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE auth_sessions SET expires_at = ?", (int(time.time()) - 1,))
        self.assertEqual(client.get("/auth/me").status_code, 401)
        self.assertEqual(client.post("/challenges", json={"draft": "Expired"}).status_code, 401)
        forged = self.new_client()
        forged.cookies.set(COOKIE, "attacker-controlled-token")
        self.assertEqual(forged.get("/auth/me").status_code, 401)

    def test_unsafe_requests_reject_foreign_or_missing_origin(self):
        client, _ = self.user()
        for origin in ("https://evil.example", "null", "http://localhost:5173.evil.example"):
            with self.subTest(origin=origin):
                response = client.post("/challenges", json={"draft": "Forbidden"}, headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)
        del client.headers["Origin"]
        self.assertEqual(client.post("/challenges", json={"draft": "Missing origin"}).status_code, 403)
        self.assertEqual(client.get("/auth/me").status_code, 200)
        self.assertEqual(client.post("/challenges", json={"draft": "Trusted"}, headers={"Origin": ORIGIN}).status_code, 201)

    def test_request_verification_is_explicit_mvp_pending(self):
        self.assertEqual(self.client.post("/auth/request-verification").status_code, 401)
        client, user = self.user(role="student")
        self.assertEqual(user["verification_status"], "unverified")
        response = client.post("/auth/request-verification")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["verification_status"], "pending")
        self.assertEqual(client.get("/auth/me").json()["verification_status"], "pending")
        self.assertEqual(client.post("/auth/request-verification").json()["verification_status"], "pending")
        for state in ("verified", "rejected"):
            set_verification(self.path, user["id"], state)
            repeated = client.post("/auth/request-verification")
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.json()["verification_status"], state)

    def test_catalog_is_public_and_draft_is_private(self):
        owner, _, published = self.published()
        draft = self.draft(owner)
        other, _ = self.user()
        self.assertEqual(self.client.get("/challenges").json(), [published])
        self.assertEqual(self.client.get(f'/challenges/{published["id"]}').json(), published)
        self.assertEqual(self.client.get(f'/challenges/{draft["id"]}').status_code, 401)
        self.assertEqual(other.get(f'/challenges/{draft["id"]}').status_code, 403)

    def test_ownership_is_assigned_server_side_and_cannot_be_spoofed(self):
        owner, user = self.user(verified=True)
        card = self.draft(owner)
        self.assertEqual(card["owner_id"], user["id"])
        url = f'/challenges/{card["id"]}'
        for key, value in (("owner_id", str(uuid4())), ("verification_status", "verified")):
            self.assertEqual(owner.post("/challenges", json={"draft": "Spoof", key: value}).status_code, 422)
            self.assertEqual(owner.patch(url, json={key: value}).status_code, 422)
        owner.post(url + "/publish", json={"confirmed": True})
        student, _ = self.user(role="student", verified=True)
        self.assertEqual(student.post(url + "/proposals", json={**TEAM, "student_id": str(uuid4())}).status_code, 422)
        self.assertEqual(owner.get(url).json()["owner_id"], user["id"])

    def test_other_business_cannot_read_or_confirm_ai_history(self):
        owner, _ = self.user()
        card = self.draft(owner)
        other, _ = self.user()
        url = f'/challenges/{card["id"]}'
        proposal_id = str(uuid4())
        for client, expected in ((self.client, 401), (other, 403)):
            self.assertEqual(client.get(url + f"/card-proposals/{proposal_id}").status_code, expected)
            self.assertEqual(client.post(url + f"/card-proposals/{proposal_id}/confirm", json={"confirmed": True}).status_code, expected)
            self.assertEqual(client.post(url + "/card-proposals", json={
                "analysis_id": str(uuid4()), "answers": [{"question_id": "q1", "text": "Spoof"}],
            }).status_code, expected)
        self.assertEqual(owner.get(url).json(), card)
        self.provider.propose.assert_not_called()


class IdentityMigrationTests(unittest.TestCase):
    def test_existing_data_is_preserved_with_read_only_ownerless_challenges(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.sqlite3"
            cid, workflow_id, proposal_id = (str(uuid4()) for _ in range(3))
            payload = ChallengeCreate(draft="Preserved legacy draft", context="Shop").model_dump_json()
            result = json.dumps({"history": "Keep this evidence"})
            proposal_payload = json.dumps(TEAM)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE challenges (id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1)))")
                db.execute("INSERT INTO challenges VALUES (?, ?, 1)", (cid, payload))
                db.execute("CREATE TABLE ai_workflows (id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL, kind TEXT NOT NULL, base_payload TEXT NOT NULL, result TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0)")
                db.execute("INSERT INTO ai_workflows VALUES (?, ?, 'analysis', ?, ?, 0)", (workflow_id, cid, payload, result))
                db.execute("CREATE TABLE student_proposals (id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL REFERENCES challenges(id), payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending')")
                db.execute("INSERT INTO student_proposals VALUES (?, ?, ?, 'accepted')", (proposal_id, cid, proposal_payload))

            # Opening the same persisted database twice also checks idempotence.
            for _ in range(2):
                with browser_client(create_app(path)) as public:
                    card = public.get(f"/challenges/{cid}").json()
                    self.assertEqual(card["draft"], "Preserved legacy draft")
                    self.assertIsNone(card["owner_id"])
                    self.assertTrue(card["published"])
                    self.assertEqual(public.get("/challenges").json(), [card])
            with browser_client(create_app(path)) as business, browser_client(create_app(path)) as student:
                register_and_login(business, path, verified=True)
                register_and_login(student, path, role="student", verified=True)
                url = f"/challenges/{cid}"
                self.assertEqual(business.patch(url, json={"title": "Claimed"}).status_code, 409)
                self.assertEqual(business.post(url + "/publish", json={"confirmed": True}).status_code, 409)
                self.assertEqual(business.post(url + f"/proposals/{proposal_id}/reject").status_code, 409)
                self.assertEqual(student.post(url + "/proposals", json=TEAM).status_code, 409)
                self.assertEqual(business.post(url + "/claim").status_code, 404)
                self.assertEqual(business.post("/auth/demo-verify").status_code, 404)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT id, payload, published, owner_id FROM challenges").fetchall(), [(cid, payload, 1, None)])
                self.assertEqual(db.execute("SELECT id, challenge_id, base_payload, result, confirmed FROM ai_workflows").fetchall(), [(workflow_id, cid, payload, result, 0)])
                self.assertEqual(db.execute("SELECT id, challenge_id, payload, status FROM student_proposals").fetchall(), [(proposal_id, cid, proposal_payload, "accepted")])
