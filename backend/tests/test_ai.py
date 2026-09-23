"""No paid calls: provider injected in API tests, SDK mocked in adapter tests."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from openai import OpenAIError
from openai.lib._pydantic import to_strict_json_schema

from backend.ai_models import AnalysisOutput, ExtractedCard
from backend.ai_provider import AIUnavailable, OpenAIProvider
from backend.main import create_app
from backend.models import ChallengeFields
from backend.tests.auth_helpers import browser_client, register_and_login

DRAFT = "У нас магазин. Нужно сократить повторные обращения."


def extracted(**values):
    return {field: values.get(field) for field in ChallengeFields.model_fields}


def evidence(quote, source="draft"):
    return {"source_id": source, "quote": quote}


def analysis_output():
    return {
        "known_information": extracted(context=evidence("У нас магазин."),
                                       need=evidence("Нужно сократить повторные обращения.")),
        "questions": [
            {"field": "users", "kind": "missing", "text": "Кто в магазине будет пользоваться решением для обращений?"},
            {"field": "data_and_materials", "kind": "missing", "text": "Есть ли история обращений покупателей магазина?"},
            {"field": "success_criteria", "kind": "missing", "text": "Как измерите сокращение повторных обращений?"},
        ],
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "test.sqlite3"
        # If any API accidentally bypasses the injected provider, fail instead of spending.
        self.enterContext(patch("backend.ai_provider.OpenAI", side_effect=AssertionError("Real AI forbidden")))
        self.provider = MagicMock()
        self.provider.analyze.return_value = analysis_output()
        self.provider.propose.return_value = extracted(
            context=evidence("У нас магазин."),
            need=evidence("Нужно сократить повторные обращения."),
            users=evidence("Менеджеры поддержки", "answer:q1"),
        )
        self.client = self.enterContext(browser_client(create_app(self.path, self.provider)))
        register_and_login(self.client, self.path)
        self.original = self.client.post("/challenges", json={"draft": DRAFT}).json()
        self.url = f'/challenges/{self.original["id"]}'

    def analyze(self):
        response = self.client.post(self.url + "/analysis")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def propose(self):
        analysis = self.analyze()
        response = self.client.post(self.url + "/card-proposals", json={
            "analysis_id": analysis["analysis_id"],
            "answers": [{"question_id": "q1", "text": "Менеджеры поддержки"}],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_analysis_questions_missing_and_no_mutation(self):
        result = self.analyze()
        self.assertGreaterEqual(len(result["questions"]), 3)
        self.assertEqual(result["known_information"]["context"], "У нас магазин.")
        self.assertNotIn("context", result["missing_information"])
        self.assertNotIn("need", result["missing_information"])
        self.assertIn("contact", result["missing_information"])
        self.assertEqual(len({q["id"] for q in result["questions"]}), 3)
        self.assertEqual(self.client.get(self.url).json(), self.original)
        self.provider.analyze.assert_called_once_with(DRAFT)

    def test_proposal_stays_separate_and_unknowns_empty(self):
        result = self.propose()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["proposed_card"]["users"], "Менеджеры поддержки")
        self.assertEqual(result["proposed_card"]["contact"], "")
        self.assertEqual(result["proposed_card"]["industry"], "")
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(self.client.get(self.url).json(), self.original)
        self.assertEqual(self.client.get(self.url + '/card-proposals/' + result["proposal_id"]).json(), result)

    def test_confirm_edits_recalculates_and_stays_unpublished(self):
        result = self.propose()
        endpoint = self.url + '/card-proposals/' + result["proposal_id"]
        confirmed = self.client.post(endpoint + '/confirm', json={
            "confirmed": True, "edits": {"users": "", "contact": "owner@example.com", "title": "Поддержка"}
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        card = confirmed.json()
        self.assertEqual(card["readiness_score"], 25)
        self.assertEqual(card["readiness_level"], "Draft")
        self.assertEqual(card["breakdown"]["context_and_need"]["score"], 20)
        self.assertIn("users", card["missing_information"])
        self.assertFalse(card["published"])
        self.assertEqual(card["draft"], DRAFT)
        self.assertEqual(card["title"], "Поддержка")
        self.assertEqual(self.client.get(self.url).json(), card)
        self.assertFalse(self.client.get(endpoint).json()["confirmation_required"])
        self.assertEqual(self.client.post(endpoint + '/confirm', json={"confirmed": True}).status_code, 409)

    def test_confirmation_required_and_protected_fields(self):
        proposal = self.propose()
        endpoint = self.url + '/card-proposals/' + proposal["proposal_id"] + '/confirm'
        for body in [{}, {"confirmed": False}, {"confirmed": "true"}, {"confirmed": 1},
                     {"confirmed": True, "edits": {"published": True}},
                     {"confirmed": True, "edits": {"readiness_score": 100}},
                     {"confirmed": True, "edits": {"draft": "Replacement"}},
                     {"confirmed": True, "edits": {"context": None}}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post(endpoint, json=body).status_code, 422)
                self.assertEqual(self.client.get(self.url).json(), self.original)

    def test_invalid_analysis_outputs_are_fallback(self):
        base = analysis_output()
        invalid = [
            {**base, "questions": base["questions"][:2]},
            {**base, "questions": [base["questions"][0]] * 3},
            {**base, "extra": "unexpected"},
            {**base, "known_information": {"context": "wrong type"}},
            {**base, "questions": [{"field": "context", "kind": "missing", "text": "Какой бизнес?"}] + base["questions"][1:]},
        ]
        for output in invalid:
            with self.subTest(output=output):
                self.provider.analyze.return_value = output
                result = self.analyze()
                self.assertEqual(result["status"], "fallback")
                self.assertEqual(result["code"], "invalid_output")
                self.assertNotIn("analysis_id", result)
        self.assertEqual(self.client.get(self.url).json(), self.original)

    def test_fabricated_or_wrong_source_quotes_are_rejected(self):
        for value in [evidence("Есть CRM и бюджет миллион"),
                      evidence("У нас магазин.", "unknown"),
                      evidence("магазин", "answer:q999")]:
            with self.subTest(value=value):
                self.provider.propose.return_value = extracted(context=value)
                result = self.propose()
                self.assertEqual(result["code"], "invalid_output")
                self.assertNotIn("proposal_id", result)
        self.assertEqual(self.client.get(self.url).json(), self.original)

    def test_question_text_is_not_a_fact_source(self):
        self.provider.propose.return_value = extracted(
            users=evidence("Кто в магазине будет пользоваться решением для обращений?", "answer:q1"))
        self.assertEqual(self.propose()["code"], "invalid_output")

    def test_analysis_hallucination_rejected(self):
        output = analysis_output()
        output["known_information"]["contact"] = evidence("fake@example.com")
        self.provider.analyze.return_value = output
        self.assertEqual(self.analyze()["code"], "invalid_output")

    def test_failure_preserves_manual_edit_health_and_scoring(self):
        self.provider.analyze.side_effect = AIUnavailable("unavailable")
        self.assertEqual(self.analyze()["status"], "fallback")
        health = self.client.get('/health').json()
        self.assertEqual({key: value for key, value in health.items() if key != "ai_provider"}, {"status": "ok"})
        self.assertIn(health["ai_provider"], ("openai", "demo"))
        changed = self.client.patch(self.url, json={"context": "Manual"}).json()
        self.assertEqual(changed["readiness_score"], 10)
        self.assertEqual(self.client.post(self.url + '/readiness').json()["readiness_score"], 10)

    def test_proposal_failure_does_not_change_challenge(self):
        self.provider.propose.side_effect = AIUnavailable("unavailable")
        self.assertEqual(self.propose()["status"], "fallback")
        self.assertEqual(self.client.get(self.url).json(), self.original)

    def test_invalid_proposal_schema_is_fallback(self):
        self.provider.propose.return_value = {"context": "Unstructured text"}
        self.assertEqual(self.propose()["code"], "invalid_output")
        self.assertEqual(self.client.get(self.url).json(), self.original)

    def test_complete_draft_uses_detail_questions(self):
        facts = {
            "context": "У нас магазин.", "need": "Нужна обработка обращений.",
            "users": "Пользователи — менеджеры.", "data_and_materials": "Есть CSV обращений.",
            "constraints": "Срок — две недели.", "expected_result": "Ожидаем прототип.",
            "success_criteria": "Успех — 10 тестов пройдено.", "contact": "owner@example.com",
            "interaction_format": "Созвон раз в неделю.",
        }
        complete_draft = " ".join(facts.values())
        self.client.patch(self.url, json={"draft": complete_draft})
        self.provider.analyze.return_value = {
            "known_information": extracted(**{field: evidence(value) for field, value in facts.items()}),
            "questions": [
                {"field": "data_and_materials", "kind": "detail", "text": "Какие столбцы содержит CSV обращений?"},
                {"field": "success_criteria", "kind": "detail", "text": "Какие сценарии покрывают 10 тестов?"},
                {"field": "interaction_format", "kind": "detail", "text": "В какой день удобен еженедельный созвон?"},
            ],
        }
        result = self.analyze()
        self.assertEqual(result["missing_information"], [])
        self.assertEqual(len(result["questions"]), 3)
        self.assertTrue(all(q["kind"] == "detail" for q in result["questions"]))

    def test_stale_proposal_cannot_overwrite_manual_edit(self):
        result = self.propose()
        self.client.patch(self.url, json={"contact": "Manual"})
        response = self.client.post(self.url + '/card-proposals/' + result["proposal_id"] + '/confirm', json={"confirmed": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get(self.url).json()["contact"], "Manual")

    def test_stale_analysis_cannot_build_proposal(self):
        result = self.analyze()
        self.client.patch(self.url, json={"draft": "New draft"})
        response = self.client.post(self.url + '/card-proposals', json={
            "analysis_id": result["analysis_id"], "answers": [{"question_id": "q1", "text": "Answer"}]})
        self.assertEqual(response.status_code, 409)
        self.provider.propose.assert_not_called()

    def test_edit_during_ai_call_is_detected(self):
        def edit_then_respond(draft):
            self.client.patch(self.url, json={"title": "New title"})
            return analysis_output()
        self.provider.analyze.side_effect = edit_then_respond
        self.assertEqual(self.client.post(self.url + '/analysis').status_code, 409)

    def test_proposal_persists_across_restart_and_confirms_without_ai(self):
        result = self.propose()
        with browser_client(create_app(self.path, self.provider)) as restarted:
            restarted.cookies.update(self.client.cookies)
            endpoint = self.url + '/card-proposals/' + result["proposal_id"]
            self.assertEqual(restarted.get(endpoint).json(), result)
            self.provider.propose.side_effect = AssertionError("Confirmation must not call AI")
            self.assertEqual(restarted.post(endpoint + '/confirm', json={"confirmed": True}).status_code, 200)

    def test_missing_and_cross_challenge_records(self):
        proposal = self.propose()
        other = self.client.post('/challenges', json={"draft": "Other"}).json()["id"]
        endpoint = f'/challenges/{other}/card-proposals/{proposal["proposal_id"]}'
        self.assertEqual(self.client.get(endpoint).status_code, 404)
        self.assertEqual(self.client.post(endpoint + '/confirm', json={"confirmed": True}).status_code, 404)
        self.assertEqual(self.client.post(f'/challenges/{uuid4()}/analysis').status_code, 404)
        self.assertEqual(self.client.get(self.url + f'/card-proposals/{uuid4()}').status_code, 404)

    def test_answer_validation(self):
        analysis = self.analyze()
        for answers in [[], [{"question_id": "q1", "text": " "}],
                        [{"question_id": "q999", "text": "Answer"}],
                        [{"question_id": "q1", "text": "Answer"}] * 2]:
            response = self.client.post(self.url + '/card-proposals', json={
                "analysis_id": analysis["analysis_id"], "answers": answers})
            self.assertEqual(response.status_code, 422, response.text)
        self.provider.propose.assert_not_called()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.env_path = Path(temp.name) / '.env'
        self.env_path.write_text('OPENAI_API_KEY=test-only\nOPENAI_MODEL=test-model\n', encoding='utf-8')
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.sdk = self.enterContext(patch('backend.ai_provider.OpenAI'))
        self.client = self.sdk.return_value.__enter__.return_value
        self.client.responses.parse.return_value = SimpleNamespace(
            status='completed', output_parsed=AnalysisOutput.model_validate(analysis_output()))
        self.provider = OpenAIProvider(self.env_path)

    def test_missing_key_or_model_no_network(self):
        for content in ['', 'OPENAI_MODEL=test-model', 'OPENAI_API_KEY=test-only']:
            self.env_path.write_text(content, encoding='utf-8')
            with self.assertRaises(AIUnavailable) as caught:
                self.provider.analyze(DRAFT)
            self.assertEqual(caught.exception.code, 'not_configured')
        self.sdk.assert_not_called()

    def test_responses_api_schema_model_timeout_and_no_storage(self):
        result = self.provider.analyze(DRAFT)
        self.assertEqual(len(result.questions), 3)
        kwargs = self.client.responses.parse.call_args.kwargs
        self.assertEqual(kwargs['model'], 'test-model')
        self.assertIs(kwargs['text_format'], AnalysisOutput)
        self.assertFalse(kwargs['store'])
        self.assertEqual(json.loads(kwargs['input']), {'draft': DRAFT})
        self.assertEqual(self.sdk.call_args.kwargs['timeout'], 30.0)
        self.assertEqual(self.sdk.call_args.kwargs['max_retries'], 0)
        self.assertNotIn('tools', kwargs)

    def test_environment_overrides_dotenv(self):
        with patch.dict(os.environ, {'OPENAI_MODEL': 'override-model'}):
            self.provider.analyze(DRAFT)
        self.assertEqual(self.client.responses.parse.call_args.kwargs['model'], 'override-model')

    def test_proposal_uses_extraction_schema_and_explicit_sources(self):
        self.client.responses.parse.return_value = SimpleNamespace(
            status='completed', output_parsed=ExtractedCard.model_validate(extracted()))
        answers = [{"source_id": "answer:q1", "text": "Staff", "question": "Who?"}]
        self.provider.propose(DRAFT, answers)
        kwargs = self.client.responses.parse.call_args.kwargs
        self.assertIs(kwargs['text_format'], ExtractedCard)
        self.assertEqual(json.loads(kwargs['input']), {'draft': DRAFT, 'answers': answers})

    def test_openai_error_is_sanitized(self):
        self.client.responses.parse.side_effect = OpenAIError('secret/private provider message')
        with self.assertRaises(AIUnavailable) as caught:
            self.provider.analyze(DRAFT)
        self.assertEqual(str(caught.exception), 'unavailable')

    def test_refusal_or_incomplete_output_is_fallback(self):
        for status, parsed in [('completed', None), ('incomplete', None), ('failed', None)]:
            self.client.responses.parse.return_value = SimpleNamespace(status=status, output_parsed=parsed)
            with self.assertRaises(AIUnavailable) as caught:
                self.provider.analyze(DRAFT)
            self.assertEqual(caught.exception.code, 'invalid_output')

    def test_strict_sdk_schema_requires_all_card_fields(self):
        schema = to_strict_json_schema(ExtractedCard)
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']), set(ChallengeFields.model_fields))
        self.assertFalse(schema['$defs']['Evidence']['additionalProperties'])

    def test_real_adapter_missing_config_fallback_endpoint(self):
        self.env_path.write_text('', encoding='utf-8')
        db_path = self.env_path.parent / 'no-key.sqlite3'
        with browser_client(create_app(db_path, self.provider)) as client:
            register_and_login(client, db_path)
            challenge = client.post('/challenges', json={'draft': DRAFT}).json()
            result = client.post(f'/challenges/{challenge["id"]}/analysis')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['code'], 'not_configured')
            self.assertTrue(result.json()['manual_edit_available'])
        self.sdk.assert_not_called()
