"""Identity contracts: privileges and verification are controlled by the server."""
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


Role = Literal["student", "business"]
VerificationStatus = Literal["unverified", "pending", "verified", "rejected"]
ProfileText = Annotated[str, Field(strict=True, max_length=200)]
Password = Annotated[str, Field(strict=True, min_length=8, max_length=128, repr=False)]


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("Укажите корректный email.")
    return normalized


class AuthInput(BaseModel):
    # Password whitespace is significant; never strip all model strings.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: Annotated[str, Field(strict=True, max_length=254)]
    password: Password

    @field_validator("email")
    @classmethod
    def clean_email(cls, value):
        return normalize_email(value)


class LoginInput(AuthInput):
    pass


class RegisterInput(AuthInput):
    name: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    role: Role
    university: ProfileText | None = None
    company_name: ProfileText | None = None
    position: ProfileText | None = None
    company_industry: ProfileText | None = None
    company_website: Annotated[str, Field(strict=True, max_length=2000)] | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Укажите имя.")
        return value

    @field_validator("university", "company_name", "position", "company_industry", "company_website")
    @classmethod
    def clean_optional_text(cls, value):
        return (value.strip() or None) if value is not None else None

    @field_validator("company_website")
    @classmethod
    def validate_website(cls, value):
        if value is None:
            return value
        try:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or any(char.isspace() for char in value)):
                raise ValueError
            parsed.port
        except ValueError:
            raise ValueError("Сайт компании должен быть HTTP(S) URL без логина и пароля.") from None
        return value


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    verification_status: VerificationStatus
    created_at: str
    university: str | None = None
    company_name: str | None = None
    position: str | None = None
    company_industry: str | None = None
    company_website: str | None = None
