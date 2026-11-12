from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class MeetingCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    starts_at: datetime
    participants: list[str] = Field(default_factory=list, max_length=50)
    agenda: str = Field(default="", max_length=4000)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    status: str | None = None
    agenda: str | None = Field(default=None, max_length=4000)
    participants: list[str] | None = Field(default=None, max_length=50)


class SegmentUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=8000)
    speaker_name: str | None = Field(default=None, max_length=80)


class RunDecision(BaseModel):
    reason: str = Field(default="", max_length=500)
