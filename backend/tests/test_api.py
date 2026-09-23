from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.main import create_app
from backend.tests.auth_helpers import browser_client, register_and_login


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        self.client = self.enterContext(browser_client(create_app(self.db_path)))
        register_and_login(self.client, self.db_path)

    def create(self, **fields):
        response = self.client.post("/challenges", json={"draft": "Нужно улучшить заявки", **fields})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_health_and_existing_cors(self):
        response = self.client.get("/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertEqual(self.client.get("/").json(), {"message": "Adaptive Learning Agent is running"})

    def test_create_get_without_invented_facts(self):
        data = self.create()
        self.assertEqual(data["readiness_score"], 0)
        self.assertEqual(data["readiness_level"], "Draft")
        self.assertFalse(data["published"])
        for field in ("title", "context", "need", "users", "data_and_materials",
                      "constraints", "expected_result", "success_criteria", "contact",
                      "interaction_format", "industry"):
            self.assertEqual(data[field], "")
        self.assertEqual(self.client.get(f'/challenges/{data["id"]}').json(), data)

    def test_edit_recalculate_clear_and_preserve(self):
        data = self.create(title="Original", context="Business context")
        url = f'/challenges/{data["id"]}'
        changed = self.client.patch(url, json={"need": "Need", "data_and_materials": "CSV"}).json()
        self.assertEqual(changed["readiness_score"], 40)
        self.assertEqual(changed["readiness_level"], "Working")
        self.assertEqual(changed["title"], "Original")
        self.assertEqual(changed["context"], "Business context")
        result = self.client.post(url + "/readiness")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["readiness_score"], 40)
        cleared = self.client.patch(url, json={"context": " \t "}).json()
        self.assertEqual(cleared["readiness_score"], 30)
        self.assertIn("context", cleared["missing_information"])
        self.assertEqual(self.client.get(url).json(), cleared)

    def test_full_score_does_not_publish(self):
        data = self.create(context="Shop", need="Automate", users="Staff",
                           data_and_materials="CSV", constraints="Two weeks",
                           expected_result="Prototype", success_criteria="10 sample cases",
                           contact="Owner", interaction_format="Weekly call")
        self.assertEqual(data["readiness_score"], 100)
        self.assertEqual(data["readiness_level"], "Priority")
        self.assertFalse(data["published"])
        self.assertEqual(data["missing_information"], [])
        self.assertEqual(data["recommendations"], [])

    def test_persistence_across_app_instances(self):
        data = self.create(context="Persistent context")
        with browser_client(create_app(self.db_path)) as restarted:
            restarted.cookies.update(self.client.cookies)
            response = restarted.get(f'/challenges/{data["id"]}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), data)

    def test_create_validation(self):
        for body in ({}, {"draft": "  "}, {"draft": 123}, {"draft": "x" * 20001},
                     {"draft": "x", "context": None}, {"draft": "x", "users": []},
                     {"draft": "x", "title": "x" * 10001}, {"draft": "x", "unknown": "x"}):
            with self.subTest(body_keys=list(body)):
                response = self.client.post("/challenges", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertIn("detail", response.json())

    def test_server_fields_cannot_be_set(self):
        data = self.create()
        url = f'/challenges/{data["id"]}'
        for field, value in [("published", True), ("readiness_score", 100),
                             ("readiness_level", "Priority"), ("id", str(uuid4()))]:
            with self.subTest(field=field):
                self.assertEqual(self.client.post("/challenges", json={"draft": "x", field: value}).status_code, 422)
                self.assertEqual(self.client.patch(url, json={field: value}).status_code, 422)
        self.assertEqual(self.client.get(url).json(), data)

    def test_patch_validation_is_atomic(self):
        data = self.create(context="Keep this")
        url = f'/challenges/{data["id"]}'
        for body in ({}, {"draft": ""}, {"context": None}, {"context": 123},
                     {"context": "Changed", "published": True}):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch(url, json=body).status_code, 422)
                self.assertEqual(self.client.get(url).json(), data)

    def test_missing_and_malformed_ids(self):
        for challenge_id, expected in [(str(uuid4()), 404), ("not-a-uuid", 422)]:
            url = f"/challenges/{challenge_id}"
            self.assertEqual(self.client.get(url).status_code, expected)
            self.assertEqual(self.client.patch(url, json={"title": "New"}).status_code, expected)
            self.assertEqual(self.client.post(url + "/readiness").status_code, expected)

    def test_database_error_is_safe(self):
        with patch("backend.database.ChallengeStore.get", side_effect=sqlite3.OperationalError("private path")):
            response = self.client.get(f"/challenges/{uuid4()}")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private path", response.text)
        self.assertIn("detail", response.json())
