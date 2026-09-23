from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StrictBool, model_validator

from .models import InputModel

RequiredText = Annotated[str, Field(strict=True, min_length=1, max_length=10000)]


class PublishRequest(InputModel):
    confirmed: StrictBool

    @model_validator(mode="after")
    def explicit_confirmation(self):
        if not self.confirmed:
            raise ValueError("Для публикации требуется confirmed=true")
        return self


class ProposalCreate(InputModel):
    team_name: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    skills: RequiredText
    solution_idea: RequiredText
    plan: RequiredText
    estimated_time: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    prototype_url: HttpUrl | None = None


class Proposal(ProposalCreate):
    id: str
    challenge_id: str
    status: Literal["pending", "accepted", "rejected"]
