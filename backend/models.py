"""API contracts. Draft text never implicitly fills structured fields."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(strict=True, max_length=10000)]
DraftText = Annotated[str, Field(strict=True, min_length=1, max_length=20000)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChallengeFields(InputModel):
    title: Text = ""
    context: Text = ""
    need: Text = ""
    users: Text = ""
    data_and_materials: Text = ""
    constraints: Text = ""
    expected_result: Text = ""
    success_criteria: Text = ""
    contact: Text = ""
    interaction_format: Text = ""
    industry: Text = ""


class ChallengeCreate(ChallengeFields):
    draft: DraftText


class ChallengeUpdate(InputModel):
    draft: DraftText | None = None
    title: Text | None = None
    context: Text | None = None
    need: Text | None = None
    users: Text | None = None
    data_and_materials: Text | None = None
    constraints: Text | None = None
    expected_result: Text | None = None
    success_criteria: Text | None = None
    contact: Text | None = None
    interaction_format: Text | None = None
    industry: Text | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Use an empty string to clear a field; null is not allowed")
        return value


class Criterion(BaseModel):
    score: int
    max_score: int


class Readiness(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    readiness_level: Literal["Draft", "Working", "Ready", "Priority"]
    breakdown: dict[str, Criterion]
    missing_information: list[str]
    recommendations: list[str]


class Challenge(ChallengeCreate, Readiness):
    id: str
    published: bool = False
