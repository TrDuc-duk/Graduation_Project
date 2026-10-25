"""Dạng request/response của API xác thực (backend_design 11.7). Trường lạ bị từ chối (14.4)."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.core.timeutil import iso_local

LocalTime = Annotated[datetime, PlainSerializer(iso_local, return_type=str)]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str


class TokenOut(BaseModel):
    """Access token chỉ nằm trong body (frontend giữ trong bộ nhớ); refresh token nằm trong cookie HttpOnly."""

    access_token: str
    token_type: str = "bearer"
    expires_at: LocalTime
    user: UserOut


class SessionOut(BaseModel):
    sid: uuid.UUID
    created_at: LocalTime
    last_seen_at: LocalTime
    expires_at: LocalTime
    user_agent: str | None
    ip: str | None
    current: bool
