"""Strict AI output contracts and human workflow inputs."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from .models import ChallengeFields, ChallengeUpdate, InputModel

Category = Literal["context", "need", "users", "data_and_materials", "constraints",
                   "expected_result", "success_criteria", "contact", "interaction_format"]
NonEmpty = Annotated[str, Field(strict=True, min_length=1, max_length=10000)]


class Evidence(InputModel):
    source_id: NonEmpty
    quote: NonEmpty


class ExtractedCard(InputModel):
    # No defaults: all fields are required by the strict structured output schema.
    # Null means unknown. Values are verbatim excerpts, never invented summaries.
    title: Evidence | None
    context: Evidence | None
    need: Evidence | None
    users: Evidence | None
    data_and_materials: Evidence | None
    constraints: Evidence | None
    expected_result: Evidence | None
    success_criteria: Evidence | None
    contact: Evidence | None
    interaction_format: Evidence | None
    industry: Evidence | None


class AIQuestion(InputModel):
    field: Category
    kind: Literal["missing", "detail"]
    text: NonEmpty


class AnalysisOutput(InputModel):
    known_information: ExtractedCard
    questions: list[AIQuestion] = Field(min_length=3, max_length=12)


class Question(AIQuestion):
    id: str


class AnalysisResult(InputModel):
    status: Literal["ok"] = "ok"
    analysis_id: str
    challenge_id: str
    known_information: ChallengeFields
    evidence: ExtractedCard
    missing_information: list[Category]
    questions: list[Question]


class Answer(InputModel):
    question_id: Annotated[str, Field(strict=True, min_length=1, max_length=20)]
    text: NonEmpty


class ProposalRequest(InputModel):
    analysis_id: UUID
    answers: list[Answer] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_answers(self):
        ids = [answer.question_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("Каждый question_id должен встречаться один раз")
        if sum(len(answer.text) for answer in self.answers) > 30000:
            raise ValueError("Суммарная длина ответов не должна превышать 30000 символов")
        return self


class ProposalResult(InputModel):
    status: Literal["ok"] = "ok"
    proposal_id: str
    challenge_id: str
    current_card: ChallengeFields
    proposed_card: ChallengeFields
    evidence: ExtractedCard
    confirmation_required: bool = True


class CardEdits(ChallengeUpdate):
    @model_validator(mode="after")
    def no_draft_edit(self):
        if "draft" in self.model_fields_set:
            raise ValueError("Изменяйте draft через PATCH Challenge и повторите анализ")
        return self


class ConfirmRequest(InputModel):
    confirmed: StrictBool
    edits: CardEdits = Field(default_factory=CardEdits)

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirmed:
            raise ValueError("Для сохранения требуется явное confirmed=true")
        return self


class AIFallback(InputModel):
    status: Literal["fallback"] = "fallback"
    code: Literal["not_configured", "unavailable", "invalid_output"]
    message: str
    manual_edit_available: bool = True
