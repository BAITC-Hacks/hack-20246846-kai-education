"""Evidence validation and storage, separate from the network adapter."""
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from .ai_models import (AIFallback, AnalysisOutput, AnalysisResult, ExtractedCard,
                        ProposalResult, Question)
from .ai_provider import AIUnavailable
from .database import WorkflowConflict
from .models import ChallengeFields
from .scoring import HINTS


def validated(schema, output):
    # Revalidate even injected providers and already-created Pydantic objects.
    return schema.model_validate(output.model_dump() if isinstance(output, BaseModel) else output)


def grounded_card(extracted: ExtractedCard, sources: dict[str, str]) -> ChallengeFields:
    values = {}
    for field in ChallengeFields.model_fields:
        evidence = getattr(extracted, field)
        if evidence is None:
            values[field] = ""
        elif evidence.source_id not in sources or evidence.quote not in sources[evidence.source_id]:
            raise AIUnavailable("invalid_output")
        else:
            values[field] = evidence.quote
    return ChallengeFields(**values)


def fallback(code):
    messages = {
        "not_configured": "OpenAI не настроен: задайте OPENAI_API_KEY и OPENAI_MODEL в корневом .env или явно выберите AI_PROVIDER=demo и перезапустите backend. Доступно ручное редактирование.",
        "unavailable": "OpenAI недоступен. Повторите позже или заполните карточку вручную.",
        "invalid_output": "AI не вернул корректный ответ с подтверждёнными источниками. Повторите запрос или заполните карточку вручную.",
    }
    return AIFallback(code=code, message=messages[code])


class AIWorkflow:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider

    def analyze(self, challenge_id, base):
        try:
            output = validated(AnalysisOutput, self.provider.analyze(base.draft))
            card = grounded_card(output.known_information, {"draft": base.draft})
            missing = [field for field in HINTS if not getattr(card, field)]
            texts = set()
            for question in output.questions:
                normalized = " ".join(question.text.casefold().split())
                if normalized in texts:
                    raise AIUnavailable("invalid_output")
                texts.add(normalized)
                if question.kind == "missing" and question.field not in missing:
                    raise AIUnavailable("invalid_output")
            result = AnalysisResult(
                analysis_id=str(uuid4()), challenge_id=challenge_id,
                known_information=card, evidence=output.known_information,
                missing_information=missing,
                questions=[Question(id=f"q{index}", **question.model_dump())
                           for index, question in enumerate(output.questions, 1)],
            )
        except AIUnavailable as exc:
            return fallback(exc.code)
        except ValidationError:
            return fallback("invalid_output")
        self.store.save_workflow(result.analysis_id, challenge_id, "analysis", base, result.model_dump())
        return result

    def propose(self, challenge_id, base, request):
        analysis = self.store.get_workflow(str(request.analysis_id), challenge_id, "analysis")
        if analysis is None:
            raise HTTPException(404, "Анализ для этой задачи не найден")
        if analysis["base"] != base.model_dump():
            raise WorkflowConflict("Задача изменилась. Повторите анализ.")
        questions = {q["id"]: q for q in analysis["result"]["questions"]}
        if any(answer.question_id not in questions for answer in request.answers):
            raise HTTPException(422, "Ответ содержит неизвестный question_id")
        sources = {"draft": base.draft}
        answers = []
        for answer in request.answers:
            source_id = f"answer:{answer.question_id}"
            sources[source_id] = answer.text
            answers.append({"source_id": source_id, "text": answer.text,
                            "question": questions[answer.question_id]["text"]})
        try:
            extracted = validated(ExtractedCard, self.provider.propose(base.draft, answers))
            card = grounded_card(extracted, sources)
            result = ProposalResult(
                proposal_id=str(uuid4()), challenge_id=challenge_id,
                current_card=ChallengeFields(**{field: getattr(base, field) for field in ChallengeFields.model_fields}),
                proposed_card=card, evidence=extracted,
            )
        except AIUnavailable as exc:
            return fallback(exc.code)
        except ValidationError:
            return fallback("invalid_output")
        # User answers remain in the separate workflow record, not the Challenge.
        record = result.model_dump()
        record["answers"] = [a.model_dump() for a in request.answers]
        self.store.save_workflow(result.proposal_id, challenge_id, "proposal", base, record)
        return result

    def get_proposal(self, challenge_id, proposal_id):
        record = self.store.get_workflow(proposal_id, challenge_id, "proposal")
        if record is None:
            raise HTTPException(404, "Предложение для этой задачи не найдено")
        result = {key: value for key, value in record["result"].items() if key != "answers"}
        result["confirmation_required"] = not record["confirmed"]
        return ProposalResult.model_validate(result)
