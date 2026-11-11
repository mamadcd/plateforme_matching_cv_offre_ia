from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["candidate", "recruiter"] = "candidate"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Adresse e-mail invalide")
        return normalized

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return " ".join(value.split())


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: Literal["candidate", "recruiter", "admin"]


class AdminUserResponse(UserResponse):
    is_active: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    role: Literal["candidate", "recruiter", "admin"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_an_update(self):
        if self.role is None and self.is_active is None:
            raise ValueError("Au moins un champ doit être modifié")
        return self