import json
from contextlib import closing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4


from backend.database import ChallengeStore, WorkflowConflict
from backend.main import create_app
from backend.models import ChallengeCreate
from backend.proposal_models import ProposalCreate
from backend.tests.auth_helpers import browser_client, register_and_login


TEAM = {"team_name": "Students", "skills": "Python, React",
        "solution_idea": "FAQ assistant", "plan": "Collect examples, build, test",
        "estimated_time": "5 hours"}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'test.sqlite3'
        self.client = self.enterContext(browser_client(create_app(self.path)))
        register_and_login(self.client, self.path, verified=True)
        self.student = self.enterContext(browser_client(create_app(self.path)))
        register_and_login(self.student, self.path, role='student', verified=True)

    def create(self, **fields):
        result = self.client.post('/challenges', json={"draft": "Business draft", **fields})
        self.assertEqual(result.status_code, 201)
        return result.json()

    def publish(self, card):
        result = self.client.post(f'/challenges/{card["id"]}/publish', json={"confirmed": True})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def submit(self, card):
        result = self.student.post(f'/challenges/{card["id"]}/proposals', json=TEAM)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def endpoint(self, card, proposal, action):
        return f'/challenges/{card["id"]}/proposals/{proposal["id"]}/{action}'

    def test_low_score_publish_is_idempotent_and_preserves_score(self):
        original = self.create()
        self.assertFalse(original['published'])
        published = self.publish(original)
        self.assertEqual(published, {**original, 'published': True})
        self.assertEqual(self.publish(original), published)
        self.assertEqual(self.client.get(f'/challenges/{original["id"]}').json(), published)
        self.assertEqual(self.client.get('/challenges').json(), [published])

    def test_publication_requires_explicit_confirmation(self):
        card = self.create()
        url = f'/challenges/{card["id"]}/publish'
        for body in ({}, {"confirmed": False}, {"confirmed": "true"}, {"confirmed": 1}, {"confirmed": True, "score": 100}):
            self.assertEqual(self.client.post(url, json=body).status_code, 422)
        self.assertEqual(self.client.post(url).status_code, 422)
        self.assertEqual(self.client.get('/challenges').json(), [])

    def test_catalog_excludes_drafts_and_sorts_descending(self):
        self.create(context="Hidden", need="Hidden")
        low = self.publish(self.create())
        high = self.publish(self.create(context="Shop", need="FAQ", data_and_materials="CSV"))
        medium = self.publish(self.create(context="Shop"))
        cards = self.client.get('/challenges').json()
        self.assertEqual([c['id'] for c in cards], [high['id'], medium['id'], low['id']])
        self.assertEqual([c['readiness_score'] for c in cards], [40, 10, 0])

    def test_catalog_filters_industry_and_level(self):
        a = self.publish(self.create(industry="Retail", context="Shop", need="FAQ", data_and_materials="CSV"))
        self.publish(self.create(industry="Retail"))
        self.publish(self.create(industry="Education", context="School"))
        self.assertEqual(len(self.client.get('/challenges', params={'industry': ' retail '}).json()), 2)
        self.assertEqual(self.client.get('/challenges', params={'readiness_level': 'Working'}).json(), [a])
        self.assertEqual(self.client.get('/challenges', params={'industry': 'Retail', 'readiness_level': 'Working'}).json(), [a])
        self.assertEqual(self.client.get('/challenges', params={'industry': 'Unknown'}).json(), [])
        self.assertEqual(self.client.get('/challenges', params={'readiness_level': 'invalid'}).status_code, 422)

    def test_catalog_recalculates_after_edit_without_unpublishing(self):
        card = self.publish(self.create())
        edited = self.client.patch(f'/challenges/{card["id"]}', json={'context': 'Shop'}).json()
        self.assertTrue(edited['published'])
        self.assertEqual(self.client.get('/challenges').json()[0]['readiness_score'], 10)

    def test_card_confirmation_does_not_publish_or_unpublish(self):
        # The same stage-2 confirmation preserves the independently managed flag.
        for published in (False, True):
            with self.subTest(published=published):
                card = self.create()
                if published:
                    self.publish(card)
                store = ChallengeStore(self.path)
                base = store.get(card['id'])
                proposal_id = str(uuid4())
                fields = base.model_dump(exclude={'draft'})
                fields['context'] = 'Shop'
                store.save_workflow(proposal_id, card['id'], 'proposal', base,
                                    {'proposed_card': fields})
                result = self.client.post(
                    f'/challenges/{card["id"]}/card-proposals/{proposal_id}/confirm',
                    json={'confirmed': True})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['published'], published)
                self.assertEqual(result.json()['readiness_score'], 10)

    def test_submit_requires_published_challenge(self):
        card = self.create()
        url = f'/challenges/{card["id"]}/proposals'
        self.assertEqual(self.student.post(url, json=TEAM).status_code, 409)
        self.assertEqual(self.client.get(url).json(), [])
        self.publish(card)
        proposal = self.submit(card)
        self.assertEqual(proposal['status'], 'pending')
        self.assertIsNone(proposal['prototype_url'])
        self.assertEqual(self.client.get(url).json(), [proposal])

    def test_proposal_validation(self):
        card = self.publish(self.create())
        url = f'/challenges/{card["id"]}/proposals'
        for body in ({}, {**TEAM, 'team_name': '  '}, {**TEAM, 'skills': []},
                     {**TEAM, 'prototype_url': 'javascript:alert(1)'}, {**TEAM, 'status': 'accepted'},
                     {**TEAM, 'plan': 'x' * 10001}):
            self.assertEqual(self.student.post(url, json=body).status_code, 422)
        result = self.student.post(url, json={**TEAM, 'prototype_url': 'https://example.com/demo'})
        self.assertEqual(result.status_code, 201)

    def test_accept_only_one_and_other_pending_unchanged(self):
        card = self.publish(self.create())
        first, second = self.submit(card), self.submit(card)
        url = self.endpoint(card, first, 'accept')
        accepted = self.client.post(url)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()['status'], 'accepted')
        self.assertEqual(self.client.post(url).json(), accepted.json())
        self.assertEqual(self.client.post(self.endpoint(card, second, 'accept')).status_code, 409)
        listed = self.client.get(f'/challenges/{card["id"]}/proposals').json()
        self.assertEqual([p['status'] for p in listed], ['accepted', 'pending'])

    def test_reject_and_invalid_status_transitions(self):
        card = self.publish(self.create())
        rejected, accepted = self.submit(card), self.submit(card)
        url = self.endpoint(card, rejected, 'reject')
        self.assertEqual(self.client.post(url).json()['status'], 'rejected')
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(self.endpoint(card, rejected, 'accept')).status_code, 409)
        self.assertEqual(self.client.post(self.endpoint(card, accepted, 'accept')).status_code, 200)
        self.assertEqual(self.client.post(self.endpoint(card, accepted, 'reject')).status_code, 409)

    def test_cross_challenge_decisions_and_missing_ids(self):
        first, other = self.publish(self.create()), self.publish(self.create())
        proposal = self.submit(first)
        for action in ('accept', 'reject'):
            self.assertEqual(self.client.post(self.endpoint(other, proposal, action)).status_code, 404)
        self.assertEqual(self.client.get(f'/challenges/{other["id"]}/proposals').json(), [])
        for suffix, method, body in [('publish', 'post', {'confirmed': True}),
                                     ('proposals', 'post', TEAM), ('proposals', 'get', None)]:
            kwargs = {'json': body} if body is not None else {}
            client = self.student if suffix == 'proposals' and method == 'post' else self.client
            self.assertEqual(getattr(client, method)(f'/challenges/{uuid4()}/{suffix}', **kwargs).status_code, 404)

    def test_publication_and_decision_survive_restart(self):
        card = self.publish(self.create())
        proposal = self.submit(card)
        self.client.post(self.endpoint(card, proposal, 'accept'))
        with browser_client(create_app(self.path)) as restarted:
            restarted.cookies.update(self.client.cookies)
            self.assertTrue(restarted.get(f'/challenges/{card["id"]}').json()['published'])
            self.assertEqual(restarted.get(f'/challenges/{card["id"]}/proposals').json()[0]['status'], 'accepted')

    def test_concurrent_accept_and_database_unique_constraint(self):
        card = self.publish(self.create())
        proposals = [self.submit(card), self.submit(card)]
        def accept(proposal):
            try:
                ChallengeStore(self.path).decide_student_proposal(card['id'], proposal['id'], 'accepted')
                return 'accepted'
            except WorkflowConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(accept, proposals)), ['accepted', 'conflict'])
        with closing(sqlite3.connect(self.path)) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE student_proposals SET status = 'accepted' WHERE challenge_id = ?", (card['id'],))

    def test_foreign_key_prevents_orphans(self):
        with ChallengeStore(self.path).connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO student_proposals(id, challenge_id, payload) VALUES (?, ?, ?)",
                           (str(uuid4()), str(uuid4()), ProposalCreate(**TEAM).model_dump_json()))


class MigrationTests(unittest.TestCase):
    def test_stage_two_database_migrates_without_data_loss(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'legacy.sqlite3'
            cid, workflow_id = str(uuid4()), str(uuid4())
            payload = ChallengeCreate(draft='Preserved draft', context='Shop').model_dump_json()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE challenges (id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0 CHECK (published = 0))')
                db.execute('INSERT INTO challenges VALUES (?, ?, 0)', (cid, payload))
                db.execute('CREATE TABLE ai_workflows (id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL, kind TEXT NOT NULL, base_payload TEXT NOT NULL, result TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0)')
                db.execute('INSERT INTO ai_workflows VALUES (?, ?, ?, ?, ?, 0)', (workflow_id, cid, 'analysis', payload, '{}'))
            store = ChallengeStore(path)
            store.initialize()
            store.initialize()
            self.assertEqual(store.get(cid).model_dump(), json.loads(payload))
            self.assertIsNotNone(store.get_workflow(workflow_id, cid, 'analysis'))
            self.assertFalse(store.is_published(cid))
            store.publish(cid)
            self.assertTrue(store.is_published(cid))
            store.create_student_proposal(cid, ProposalCreate(**TEAM))
