from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "mt_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Meeting(Base, TimestampMixin):
    __tablename__ = "mt_meeting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("mt_user.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agenda: Mapped[str] = mapped_column(Text, default="")
    participants_json: Mapped[str] = mapped_column(Text, default="[]")


class MeetingAsset(Base, TimestampMixin):
    __tablename__ = "mt_asset"
    __table_args__ = (UniqueConstraint("meeting_id", "sha256", name="uq_mt_asset_meeting_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("mt_meeting.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="document")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class Job(Base, TimestampMixin):
    __tablename__ = "mt_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_mt_job_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("mt_meeting.id"), nullable=True, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("mt_asset.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TranscriptSegment(Base, TimestampMixin):
    __tablename__ = "mt_transcript_segment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("mt_meeting.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker_label: Mapped[str] = mapped_column(String(40), default="speaker-0")
    speaker_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64), default="")


class MinutesVersion(Base, TimestampMixin):
    __tablename__ = "mt_minutes_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("mt_meeting.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    source_digest: Mapped[str] = mapped_column(String(64), default="")
    content_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("mt_user.id"))


class ActionItem(Base, TimestampMixin):
    __tablename__ = "mt_action_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("mt_meeting.id"), index=True)
    minutes_version_id: Mapped[int] = mapped_column(ForeignKey("mt_minutes_version.id"))
    title: Mapped[str] = mapped_column(String(240))
    owner_name: Mapped[str] = mapped_column(String(80), default="待确认")
    due_text: Mapped[str] = mapped_column(String(80), default="待确认")
    status: Mapped[str] = mapped_column(String(24), default="open")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")


class AgentRun(Base, TimestampMixin):
    __tablename__ = "mt_agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("mt_meeting.id"), index=True)
    minutes_version_id: Mapped[int] = mapped_column(ForeignKey("mt_minutes_version.id"))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=2)
    score: Mapped[float] = mapped_column(Float, default=0)
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    revised_json: Mapped[str] = mapped_column(Text, default="{}")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_reason: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=0)


class AgentStep(Base, TimestampMixin):
    __tablename__ = "mt_agent_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("mt_agent_run.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(24), default="succeeded")
    summary: Mapped[str] = mapped_column(String(500), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class AiCallLog(Base, TimestampMixin):
    __tablename__ = "mt_ai_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("mt_meeting.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(500), default="")
