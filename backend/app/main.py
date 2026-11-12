from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import secrets
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from docx import Document
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
import jwt
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .ai import QwenClient
from .database import SessionLocal, get_db, init_db
from .models import (
    ActionItem,
    AgentRun,
    AgentStep,
    AiCallLog,
    AiModelConfig,
    Department,
    EmployeeProfile,
    Job,
    Meeting,
    MeetingAsset,
    MinutesVersion,
    PromptTemplate,
    TranscriptSegment,
    User,
)
from .schemas import (
    AiModelConfigUpdate,
    DepartmentCreate,
    EmployeeCreate,
    EmployeeUpdate,
    LoginRequest,
    MeetingCreate,
    MeetingUpdate,
    PromptTemplateCreate,
    RunDecision,
    SegmentUpdate,
)
from .security import authorize_meeting, authorize_run, current_user, hash_password, issue_token, require_admin, verify_password
from .seed import seed
from .utils import iso, json_dumps, json_loads
from .worker import create_job, sign_asset


settings = get_settings()
_used_review_tickets: set[str] = set()
_ALLOWED_UPLOAD_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(
    title="MinutesTrace API",
    version="1.0.0",
    description="Evidence-linked meeting intelligence with human-controlled Agent review.",
    lifespan=lifespan,
    # Interactive API discovery is useful locally but must not be public in production.
    docs_url=None if settings.environment.lower() in {"production", "prod"} else "/docs",
    redoc_url=None if settings.environment.lower() in {"production", "prod"} else "/redoc",
    openapi_url=None if settings.environment.lower() in {"production", "prod"} else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def meeting_dict(db: Session, meeting: Meeting, *, detailed: bool = False) -> dict[str, Any]:
    segment_count = db.scalar(select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting.id)) or 0
    version = db.scalar(
        select(MinutesVersion)
        .where(MinutesVersion.meeting_id == meeting.id)
        .order_by(MinutesVersion.version.desc())
        .limit(1)
    )
    running_job = db.scalar(
        select(Job)
        .where(Job.meeting_id == meeting.id, Job.status.in_(["queued", "running"]))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    result = {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "starts_at": iso(meeting.starts_at),
        "ended_at": iso(meeting.ended_at),
        "participants": json_loads(meeting.participants_json, []),
        "agenda": meeting.agenda,
        "segment_count": segment_count,
        "minutes_version": version.version if version else None,
        "minutes_status": version.status if version else None,
        "active_job": job_dict(running_job) if running_job else None,
        "updated_at": iso(meeting.updated_at),
    }
    if detailed:
        result["assets"] = [asset_dict(item) for item in db.scalars(select(MeetingAsset).where(MeetingAsset.meeting_id == meeting.id).order_by(MeetingAsset.created_at.desc()))]
        result["recent_jobs"] = [job_dict(item) for item in db.scalars(select(Job).where(Job.meeting_id == meeting.id).order_by(Job.created_at.desc()).limit(8))]
    return result


def visible_meetings(statement, user: User):
    """Apply the same owner/admin boundary to collection endpoints."""
    return statement if user.role == "admin" else statement.where(Meeting.owner_id == user.id)


def asset_dict(asset: MeetingAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "kind": asset.kind,
        "created_at": iso(asset.created_at),
    }


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "attempt": job.attempt,
        "max_attempts": settings.job_max_attempts,
        "error": job.error,
        "result": json_loads(job.result_json, {}),
        "updated_at": iso(job.updated_at),
    }


def segment_dict(segment: TranscriptSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "ordinal": segment.ordinal,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "speaker_label": segment.speaker_label,
        "speaker_name": segment.speaker_name,
        "text": segment.text,
        "evidence_hash": segment.evidence_hash,
    }


def version_dict(db: Session, version: MinutesVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "source_digest": version.source_digest,
        "content": json_loads(version.content_json, {}),
        "action_items": [
            {
                "id": item.id,
                "title": item.title,
                "owner": item.owner_name,
                "due": item.due_text,
                "status": item.status,
                "evidence_segment_ids": json_loads(item.evidence_json, []),
            }
            for item in db.scalars(select(ActionItem).where(ActionItem.minutes_version_id == version.id).order_by(ActionItem.id))
        ],
        "created_at": iso(version.created_at),
    }


def run_dict(db: Session, run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "meeting_id": run.meeting_id,
        "minutes_version_id": run.minutes_version_id,
        "status": run.status,
        "current_round": run.current_round,
        "max_rounds": run.max_rounds,
        "score": run.score,
        "issues": json_loads(run.issues_json, []),
        "revised": json_loads(run.revised_json, {}),
        "decision_reason": run.decision_reason,
        "steps": [
            {
                "id": step.id,
                "sequence": step.sequence,
                "node": step.node,
                "status": step.status,
                "summary": step.summary,
                "detail": json_loads(step.detail_json, {}),
                "duration_ms": step.duration_ms,
                "created_at": iso(step.created_at),
            }
            for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence))
        ],
        "updated_at": iso(run.updated_at),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not user.enabled or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return {"token": issue_token(user), "user": {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}}


@app.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}


@app.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    all_meetings = list(db.scalars(visible_meetings(select(Meeting).order_by(Meeting.starts_at.desc()), user)))
    meetings = all_meetings[:6]
    action_query = select(ActionItem).join(Meeting, Meeting.id == ActionItem.meeting_id).where(ActionItem.status == "open").order_by(ActionItem.created_at.desc()).limit(8)
    action_items = list(db.scalars(action_query if user.role == "admin" else action_query.where(Meeting.owner_id == user.id)))
    minutes_query = select(MinutesVersion).join(Meeting, Meeting.id == MinutesVersion.meeting_id)
    all_minutes = list(db.scalars(minutes_query if user.role == "admin" else minutes_query.where(Meeting.owner_id == user.id)))
    calls_query = select(AiCallLog).join(Meeting, Meeting.id == AiCallLog.meeting_id, isouter=True)
    all_ai_calls = list(db.scalars(calls_query if user.role == "admin" else calls_query.where(Meeting.owner_id == user.id)))
    ai_calls = [item for item in all_ai_calls if item.meeting_id is not None]
    now = datetime.utcnow()
    trend = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        trend.append({"label": day.strftime("%m/%d"), "value": sum(1 for item in all_meetings if item.starts_at and item.starts_at.date() == day)})
    meeting_status_labels = {"ended": "已完成", "draft": "草稿", "scheduled": "待开始", "live": "进行中", "archived": "已归档"}
    meeting_status = []
    for status_name, label in meeting_status_labels.items():
        count = sum(1 for item in all_meetings if item.status == status_name)
        if count:
            meeting_status.append({"label": label, "value": count})
    if not meeting_status:
        meeting_status = [{"label": "暂无数据", "value": 0}]
    review_status_labels = {"approved": "已批准", "draft": "待生成", "waiting_human": "待审核"}
    review_status = []
    for status_name, label in review_status_labels.items():
        count = sum(1 for item in all_minutes if item.status == status_name)
        if count:
            review_status.append({"label": label, "value": count})
    if not review_status:
        review_status = [{"label": "暂无数据", "value": 0}]
    successful_calls = sum(1 for item in ai_calls if item.success)
    token_total = sum((item.prompt_tokens or 0) + (item.completion_tokens or 0) for item in ai_calls)
    avg_latency = round(sum(item.duration_ms or 0 for item in ai_calls) / len(ai_calls)) if ai_calls else 0
    minutes_meeting_ids = {item.meeting_id for item in all_minutes}
    completion_rate = round(sum(1 for item in all_meetings if item.id in minutes_meeting_ids) / len(all_meetings) * 100) if all_meetings else 0
    recent_window = now - timedelta(days=7)
    previous_window = now - timedelta(days=14)
    recent_meetings = sum(1 for item in all_meetings if item.starts_at and item.starts_at >= recent_window)
    previous_meetings = sum(1 for item in all_meetings if item.starts_at and previous_window <= item.starts_at < recent_window)
    meeting_growth = round((recent_meetings - previous_meetings) / previous_meetings * 100) if previous_meetings else 0
    return {
        "stats": {
            "meetings": db.scalar(select(func.count(Meeting.id))) or 0,
            "pending_reviews": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "waiting_human")) or 0,
            "open_actions": db.scalar(select(func.count(ActionItem.id)).where(ActionItem.status == "open")) or 0,
            "evidence_segments": db.scalar(select(func.count(TranscriptSegment.id))) or 0,
        },
        "meetings": [meeting_dict(db, item) for item in meetings],
        "actions": [
            {"id": item.id, "meeting_id": item.meeting_id, "title": item.title, "owner": item.owner_name, "due": item.due_text, "status": item.status}
            for item in action_items
        ],
        "analytics": {
            "meeting_trend": trend,
            "meeting_status": meeting_status,
            "review_status": review_status,
            "review_total": len(all_minutes),
            "minutes_completion_rate": completion_rate,
            "meeting_growth": meeting_growth,
            "ai": {
                "calls": len(ai_calls),
                "success_rate": round(successful_calls / len(ai_calls) * 100) if ai_calls else 100,
                "avg_latency_ms": avg_latency,
                "token_total": token_total,
            },
        },
    }


@app.get("/meetings")
def list_meetings(
    query: str = Query(default="", max_length=120),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    statement = visible_meetings(select(Meeting).order_by(Meeting.starts_at.desc()), user)
    if query.strip():
        statement = statement.where(Meeting.title.like(f"%{query.strip()}%"))
    items = list(db.scalars(statement.limit(100)))
    return {"items": [meeting_dict(db, item) for item in items], "total": len(items)}


def meeting_center_rows(db: Session, meetings: list[Meeting]) -> list[dict[str, Any]]:
    """Batch-load related rows so the meeting-center table does not issue N+1 queries."""
    if not meetings:
        return []
    meeting_ids = [meeting.id for meeting in meetings]
    assets_by: dict[int, list[MeetingAsset]] = {}
    for asset in db.scalars(select(MeetingAsset).where(MeetingAsset.meeting_id.in_(meeting_ids)).order_by(MeetingAsset.created_at.desc())):
        assets_by.setdefault(asset.meeting_id, []).append(asset)
    jobs_by: dict[int, list[Job]] = {}
    for job in db.scalars(select(Job).where(Job.meeting_id.in_(meeting_ids)).order_by(Job.created_at.desc())):
        bucket = jobs_by.setdefault(job.meeting_id, [])
        if len(bucket) < 8:
            bucket.append(job)
    latest_minutes_by: dict[int, MinutesVersion] = {}
    for item in db.scalars(select(MinutesVersion).where(MinutesVersion.meeting_id.in_(meeting_ids)).order_by(MinutesVersion.version.desc())):
        latest_minutes_by.setdefault(item.meeting_id, item)
    latest_review_by: dict[int, AgentRun] = {}
    for item in db.scalars(select(AgentRun).where(AgentRun.meeting_id.in_(meeting_ids)).order_by(AgentRun.created_at.desc())):
        latest_review_by.setdefault(item.meeting_id, item)
    owners = {user.id: user.display_name for user in db.scalars(select(User).where(User.id.in_({meeting.owner_id for meeting in meetings})))}
    model = db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == "minutes_generation"))
    rows = []
    for meeting in meetings:
        assets = assets_by.get(meeting.id, [])
        jobs = jobs_by.get(meeting.id, [])
        latest_minutes = latest_minutes_by.get(meeting.id)
        latest_review = latest_review_by.get(meeting.id)
        minutes_job = next((job for job in jobs if job.kind == "minutes_generation"), None)
        transcription_job = next((job for job in jobs if job.kind == "transcription"), None)
        media = next((asset for asset in assets if asset.kind == "audio"), assets[0] if assets else None)
        progress = latest_minutes and 100 or (minutes_job.progress if minutes_job else (transcription_job.progress if transcription_job else 0))
        rows.append({
            "meeting_id": meeting.id,
            "title": meeting.title,
            "audio_file": media.file_name if media else "—",
            "asset_count": len(assets),
            "status": latest_minutes.status if latest_minutes else (minutes_job.status if minutes_job else meeting.status),
            "progress": progress,
            "model": model.model if model and model.enabled else "未配置",
            "creator": owners.get(meeting.owner_id, "未知"),
            "created_at": iso(meeting.created_at),
            "meeting_status": meeting.status,
            "minutes_version": latest_minutes.version if latest_minutes else None,
            "review_status": latest_review.status if latest_review else None,
            "active_job": job_dict(minutes_job or transcription_job) if (minutes_job or transcription_job) else None,
        })
    return rows


@app.get("/meeting-center/minutes")
def meeting_center_minutes(
    query: str = Query(default="", max_length=120),
    status_filter: str = Query(default="", alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    meetings = list(db.scalars(visible_meetings(select(Meeting).order_by(Meeting.created_at.desc()).limit(200), user)))
    rows = meeting_center_rows(db, meetings)
    if query.strip():
        rows = [row for row in rows if query.strip().lower() in row["title"].lower()]
    if status_filter.strip():
        rows = [row for row in rows if row["status"] == status_filter.strip()]
    return {"items": rows, "total": len(rows)}


@app.get("/meeting-center/materials")
def meeting_center_materials(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    meetings = {meeting.id: meeting for meeting in db.scalars(visible_meetings(select(Meeting), user))}
    owners = {user.id: user.display_name for user in db.scalars(select(User))}
    items = []
    asset_query = select(MeetingAsset).join(Meeting, Meeting.id == MeetingAsset.meeting_id).order_by(MeetingAsset.created_at.desc()).limit(200)
    if user.role != "admin":
        asset_query = asset_query.where(Meeting.owner_id == user.id)
    for asset in db.scalars(asset_query):
        meeting = meetings.get(asset.meeting_id)
        items.append(asset_dict(asset) | {"meeting_title": meeting.title if meeting else "—", "creator": owners.get(meeting.owner_id, "未知") if meeting else "未知"})
    return {"items": items, "total": len(items)}


@app.get("/meeting-center/transcription")
def meeting_center_transcription(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    meetings = {meeting.id: meeting for meeting in db.scalars(visible_meetings(select(Meeting), user))}
    items = []
    job_query = select(Job).join(Meeting, Meeting.id == Job.meeting_id).where(Job.kind == "transcription").order_by(Job.created_at.desc()).limit(200)
    if user.role != "admin":
        job_query = job_query.where(Meeting.owner_id == user.id)
    for job in db.scalars(job_query):
        meeting = meetings.get(job.meeting_id)
        items.append(job_dict(job) | {"meeting_id": job.meeting_id, "meeting_title": meeting.title if meeting else "—"})
    return {"items": items, "total": len(items)}


@app.get("/assistant/runs")
def assistant_runs(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    meetings = {meeting.id: meeting for meeting in db.scalars(visible_meetings(select(Meeting), user))}
    items = []
    run_query = select(AgentRun).join(Meeting, Meeting.id == AgentRun.meeting_id).order_by(AgentRun.created_at.desc()).limit(200)
    if user.role != "admin":
        run_query = run_query.where(Meeting.owner_id == user.id)
    for run in db.scalars(run_query):
        meeting = meetings.get(run.meeting_id)
        items.append(run_dict(db, run) | {"meeting_title": meeting.title if meeting else "—"})
    return {"items": items, "total": len(items)}


@app.post("/meetings", status_code=201)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    meeting = Meeting(
        title=payload.title,
        starts_at=payload.starts_at.replace(tzinfo=None),
        owner_id=user.id,
        agenda=payload.agenda,
        participants_json=json_dumps(payload.participants),
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting_dict(db, meeting, detailed=True)


@app.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return meeting_dict(db, authorize_meeting(db, meeting_id, user), detailed=True)


@app.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: int, payload: MeetingUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    meeting = authorize_meeting(db, meeting_id, user)
    values = payload.model_dump(exclude_unset=True)
    if "participants" in values:
        meeting.participants_json = json_dumps(values.pop("participants"))
    if "status" in values and values["status"] not in {"draft", "scheduled", "live", "ended", "archived"}:
        raise HTTPException(status_code=422, detail="无效会议状态")
    for field, value in values.items():
        setattr(meeting, field, value)
    db.commit()
    return meeting_dict(db, meeting, detailed=True)


@app.post("/meetings/{meeting_id}/assets", status_code=201)
async def upload_asset(
    meeting_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    safe_name = Path(file.filename or "upload.bin").name
    extension = Path(safe_name).suffix.lower()
    expected_type = _ALLOWED_UPLOAD_TYPES.get(extension)
    if not expected_type:
        raise HTTPException(status_code=415, detail="仅支持 TXT、Markdown、PDF、DOCX、MP3、WAV、M4A、MP4 文件")
    declared_type = (file.content_type or mimetypes.guess_type(safe_name)[0] or "").lower()
    if declared_type and declared_type != expected_type and not (extension == ".wav" and declared_type == "audio/x-wav"):
        raise HTTPException(status_code=415, detail="文件类型与扩展名不匹配")
    digest = hashlib.sha256()
    meeting_dir = settings.storage_dir / str(meeting_id)
    meeting_dir.mkdir(parents=True, exist_ok=True)
    temp_path = meeting_dir / f".{time.time_ns()}.upload"
    size = 0
    try:
        with temp_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.upload_limit_mb} MB")
                digest.update(chunk)
                output.write(chunk)
        sha256 = digest.hexdigest()
        existing = db.scalar(select(MeetingAsset).where(MeetingAsset.meeting_id == meeting_id, MeetingAsset.sha256 == sha256))
        if existing:
            temp_path.unlink(missing_ok=True)
            return asset_dict(existing)
        final_path = meeting_dir / f"{sha256[:16]}-{safe_name}"
        temp_path.replace(final_path)
        media_type = expected_type
        kind = "audio" if media_type.startswith(("audio/", "video/")) else "document"
        asset = MeetingAsset(
            meeting_id=meeting_id,
            file_name=safe_name,
            media_type=media_type,
            size_bytes=size,
            sha256=sha256,
            storage_path=str(final_path.resolve()),
            kind=kind,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset_dict(asset)
    finally:
        await file.close()
        temp_path.unlink(missing_ok=True)


@app.get("/assets/public/{asset_id}", include_in_schema=False)
def public_asset(asset_id: int, expires: int, sig: str, db: Session = Depends(get_db)) -> FileResponse:
    if expires < int(time.time()) or not __import__("hmac").compare_digest(sign_asset(asset_id, expires), sig):
        raise HTTPException(status_code=403, detail="资源链接已失效")
    asset = db.get(MeetingAsset, asset_id)
    if not asset or not Path(asset.storage_path).is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    return FileResponse(asset.storage_path, media_type=asset.media_type, filename=asset.file_name)


@app.post("/meetings/{meeting_id}/transcription", status_code=202)
def queue_transcription(meeting_id: int, asset_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    if asset_id is None:
        asset_id = db.scalar(select(MeetingAsset.id).where(MeetingAsset.meeting_id == meeting_id).order_by(MeetingAsset.created_at.desc()).limit(1))
    asset = db.get(MeetingAsset, asset_id) if asset_id else None
    if not asset or asset.meeting_id != meeting_id:
        raise HTTPException(status_code=422, detail="请先上传会议录音或文本")
    job = create_job(db, "transcription", meeting_id, f"transcription:{asset.id}:{asset.sha256}", asset_id=asset.id)
    if job.status == "failed":
        raise HTTPException(status_code=409, detail="转写已达到最大重试次数，请更换资料后重试")
    return job_dict(job)


@app.get("/meetings/{meeting_id}/transcript")
def transcript(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ordinal)))
    return {"items": [segment_dict(item) for item in segments], "total": len(segments)}


@app.patch("/transcript-segments/{segment_id}")
def update_segment(segment_id: int, payload: SegmentUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    segment = db.get(TranscriptSegment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="转写片段不存在")
    authorize_meeting(db, segment.meeting_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    segment.evidence_hash = hashlib.sha256(f"{segment.start_ms}:{segment.end_ms}:{segment.text}".encode()).hexdigest()
    db.commit()
    return segment_dict(segment)


@app.post("/meetings/{meeting_id}/speaker-suggestions")
def speaker_suggestions(
    meeting_id: int,
    use_ai: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    meeting = authorize_meeting(db, meeting_id, user)
    participants = json_loads(meeting.participants_json, [])
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ordinal)))
    labels = list(dict.fromkeys(segment.speaker_label for segment in segments))
    suggestions = []
    if use_ai and segments:
        transcript = [
            {"id": item.id, "speaker": item.speaker_name or item.speaker_label, "text": item.text}
            for item in segments[:120]
        ]
        suggestions = QwenClient(db, meeting_id).suggest_speakers(participants, transcript)
    by_label = {item.get("speaker_label"): item for item in suggestions if isinstance(item, dict)}
    items = []
    for index, label in enumerate(labels):
        item = by_label.get(label, {})
        suggested_name = item.get("suggested_name") if item.get("suggested_name") in participants else (participants[index] if index < len(participants) else "待确认")
        items.append(
            {
                "speaker_label": label,
                "suggested_name": suggested_name,
                "confidence": float(item.get("confidence") or (0.72 if index < len(participants) else 0.0)),
                "reason": str(item.get("reason") or ("按参会人顺序生成的初始建议" if not use_ai else "模型未提供可用建议")),
                "source": "ai" if item else "fallback",
            }
        )
    return {"items": items}


@app.post("/meetings/{meeting_id}/minutes/generate", status_code=202)
def queue_minutes(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ordinal)))
    if not segments:
        raise HTTPException(status_code=422, detail="请先完成会议转写")
    source_digest = hashlib.sha256("\n".join(item.text for item in segments).encode()).hexdigest()
    job = create_job(db, "minutes_generation", meeting_id, f"minutes:{meeting_id}:{source_digest}")
    if job.status == "failed":
        raise HTTPException(status_code=409, detail="纪要生成已达到最大重试次数，请修改转写后重试")
    return job_dict(job)


@app.get("/meetings/{meeting_id}/minutes")
def get_minutes(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    versions = list(db.scalars(select(MinutesVersion).where(MinutesVersion.meeting_id == meeting_id).order_by(MinutesVersion.version.desc())))
    return {"current": version_dict(db, versions[0]) if versions else None, "versions": [version_dict(db, item) for item in versions]}


@app.post("/meetings/{meeting_id}/review-runs", status_code=202)
def queue_review(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_meeting(db, meeting_id, user)
    version = db.scalar(select(MinutesVersion).where(MinutesVersion.meeting_id == meeting_id).order_by(MinutesVersion.version.desc()).limit(1))
    if not version:
        raise HTTPException(status_code=422, detail="请先生成会议纪要")
    active = db.scalar(select(AgentRun).where(AgentRun.meeting_id == meeting_id, AgentRun.status.in_(["queued", "running", "waiting_human"])).order_by(AgentRun.created_at.desc()).limit(1))
    if active:
        return run_dict(db, active)
    run = AgentRun(meeting_id=meeting_id, minutes_version_id=version.id, status="queued")
    db.add(run)
    db.flush()
    create_job(db, "agent_review", meeting_id, f"review:{version.id}:{run.id}", run_id=run.id)
    db.refresh(run)
    return run_dict(db, run)


@app.get("/review-runs/{run_id}")
def get_review(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return run_dict(db, authorize_run(db, run_id, user))


@app.post("/review-runs/{run_id}/events-ticket")
def create_review_events_ticket(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    authorize_run(db, run_id, user)
    expires = int(time.time()) + 60
    ticket_id = secrets.token_urlsafe(18)
    ticket = jwt.encode(
        {"typ": "review_stream", "sub": str(user.id), "run_id": run_id, "jti": ticket_id, "exp": expires},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"ticket": ticket, "expires_in": 60}


@app.get("/review-runs/{run_id}/events")
def review_events(
    request: Request,
    run_id: int,
    ticket: str = Query(default=""),
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        claims = jwt.decode(ticket, settings.jwt_secret, algorithms=["HS256"])
        if claims.get("typ") != "review_stream" or int(claims.get("run_id")) != run_id:
            raise ValueError("审校流 ticket 无效")
        user_id = int(claims["sub"])
        ticket_id = str(claims["jti"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc

    if ticket_id in _used_review_tickets:
        raise HTTPException(status_code=401, detail="审校流 ticket 已使用")
    if len(_used_review_tickets) > 10000:
        # shortcut: this single-process service keeps a bounded replay cache; move it to Redis for multi-worker scale.
        _used_review_tickets.clear()
    _used_review_tickets.add(ticket_id)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.enabled:
            raise HTTPException(status_code=401, detail="账号不可用")
        authorize_run(db, run_id, user)

    async def stream():
        last_signature = ""
        deadline = time.time() + 300
        while time.time() < deadline:
            if await request.is_disconnected():
                break
            with SessionLocal() as db:
                run = db.get(AgentRun, run_id)
                if not run:
                    yield "event: error\ndata: {\"detail\":\"审校运行不存在\"}\n\n"
                    break
                data = run_dict(db, run)
                signature = f"{run.updated_at}:{len(data['steps'])}:{run.status}"
                if signature != last_signature:
                    yield f"id: {len(data['steps'])}\nevent: run\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                    last_signature = signature
                if run.status in {"waiting_human", "approved", "rejected", "cancelled", "failed"}:
                    break
            yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/review-runs/{run_id}/{action}")
def decide_review(run_id: int, action: str, payload: RunDecision, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    run = authorize_run(db, run_id, user)
    if action == "cancel":
        if run.status not in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="当前状态不能取消")
        next_status = "cancelled" if run.status == "queued" else "running"
        claimed = db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status.in_(["queued", "running"]), AgentRun.version == run.version)
            .values(status=next_status, cancel_requested=True, decision_reason=payload.reason, version=run.version + 1)
        )
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="审校状态已被其他操作更新")
        if next_status == "cancelled":
            db.execute(update(Job).where(Job.run_id == run_id, Job.status == "queued").values(status="cancelled"))
        db.refresh(run)
    elif action == "resume":
        if run.status not in {"cancelled", "failed"}:
            raise HTTPException(status_code=409, detail="当前状态不能恢复")
        if run.current_round >= run.max_rounds:
            raise HTTPException(status_code=409, detail="审校轮次已用完，请重新发起审校")
        claimed = db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status.in_(["cancelled", "failed"]), AgentRun.version == run.version)
            .values(status="queued", cancel_requested=False, decision_reason=payload.reason, version=run.version + 1)
        )
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="审校状态已被其他操作更新")
        db.refresh(run)
        create_job(db, "agent_review", run.meeting_id, f"review:resume:{run.id}:{run.version}", run_id=run.id)
    elif action == "reject":
        if run.status != "waiting_human":
            raise HTTPException(status_code=409, detail="审校尚未进入人工确认")
        claimed = db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == "waiting_human", AgentRun.version == run.version)
            .values(status="rejected", decision_reason=payload.reason, version=run.version + 1)
        )
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="审校状态已被其他操作更新")
        db.refresh(run)
    elif action == "approve":
        if run.status != "waiting_human":
            raise HTTPException(status_code=409, detail="审校尚未进入人工确认")
        claimed = db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == "waiting_human", AgentRun.version == run.version)
            .values(status="approved", decision_reason=payload.reason, version=run.version + 1)
        )
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="审校状态已被其他操作更新")
        db.refresh(run)
        source = db.get(MinutesVersion, run.minutes_version_id)
        content = json_loads(run.revised_json, {}) or json_loads(source.content_json, {})
        next_version = (db.scalar(select(func.max(MinutesVersion.version)).where(MinutesVersion.meeting_id == run.meeting_id)) or 0) + 1
        approved = MinutesVersion(
            meeting_id=run.meeting_id,
            version=next_version,
            status="approved",
            source_digest=source.source_digest,
            content_json=json_dumps(content),
            created_by=user.id,
        )
        db.add(approved)
        db.flush()
        for item in content.get("action_items") or []:
            db.add(ActionItem(
                meeting_id=run.meeting_id,
                minutes_version_id=approved.id,
                title=str(item.get("text") or "待确认事项")[:240],
                owner_name=str(item.get("owner") or "待确认")[:80],
                due_text=str(item.get("due") or "待确认")[:80],
                evidence_json=json_dumps(item.get("evidence_segment_ids") or []),
            ))
    else:
        raise HTTPException(status_code=404, detail="未知操作")
    db.commit()
    return run_dict(db, run)


def export_content(content: dict[str, Any]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [("会议摘要", [content.get("summary") or "暂无摘要"])]
    mapping = (("议题", "topics"), ("会议决策", "decisions"), ("行动项", "action_items"), ("待确认", "open_questions"), ("风险", "risks"))
    for title, field in mapping:
        rows = []
        for item in content.get(field) or []:
            text = item.get("text") or item.get("title") or item.get("summary") or ""
            if field == "action_items":
                text += f"（负责人：{item.get('owner') or '待确认'}；截止：{item.get('due') or '待确认'}）"
            evidence = item.get("evidence_segment_ids") or []
            if evidence:
                text += f" [证据片段：{', '.join(map(str, evidence))}]"
            rows.append(text)
        sections.append((title, rows or ["暂无"]))
    return sections


@app.get("/meetings/{meeting_id}/export")
def export_minutes(meeting_id: int, format: str = Query(default="docx", pattern="^(docx|pdf)$"), db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    meeting = authorize_meeting(db, meeting_id, user)
    version = db.scalar(select(MinutesVersion).where(MinutesVersion.meeting_id == meeting_id).order_by(MinutesVersion.version.desc()).limit(1))
    if not version:
        raise HTTPException(status_code=422, detail="还没有可导出的纪要")
    sections = export_content(json_loads(version.content_json, {}))
    safe_title = "".join(char for char in meeting.title if char not in '\\/:*?\"<>|')[:60] or "会议纪要"
    encoded_title = quote(f"{safe_title}-V{version.version}")
    if format == "docx":
        document = Document()
        document.add_heading(meeting.title, 0)
        document.add_paragraph(f"会议时间：{meeting.starts_at:%Y-%m-%d %H:%M}    纪要版本：V{version.version}")
        for title, rows in sections:
            document.add_heading(title, level=1)
            for row in rows:
                document.add_paragraph(row, style="List Bullet" if len(rows) > 1 else None)
        buffer = io.BytesIO()
        document.save(buffer)
        return Response(buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_title}.docx"})
    buffer = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 52
    pdf.setFont("STSong-Light", 18)
    pdf.drawString(48, y, meeting.title[:34])
    y -= 34
    pdf.setFont("STSong-Light", 10)
    pdf.drawString(48, y, f"会议时间：{meeting.starts_at:%Y-%m-%d %H:%M}    纪要版本：V{version.version}")
    for title, rows in sections:
        y -= 28
        if y < 72:
            pdf.showPage(); y = height - 52
        pdf.setFont("STSong-Light", 14); pdf.drawString(48, y, title)
        pdf.setFont("STSong-Light", 10)
        for row in rows:
            for start in range(0, len(row), 46):
                y -= 18
                if y < 52:
                    pdf.showPage(); y = height - 52; pdf.setFont("STSong-Light", 10)
                pdf.drawString(58, y, row[start:start + 46])
    pdf.save()
    return Response(buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_title}.pdf"})


def observability_payload(db: Session, user: User) -> dict[str, Any]:
    if user.role == "admin":
        jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(30)))
        calls = list(db.scalars(select(AiCallLog).order_by(AiCallLog.created_at.desc()).limit(30)))
        job_summary = select(Job)
        call_summary = select(AiCallLog)
    else:
        job_query = select(Job).join(Meeting, Meeting.id == Job.meeting_id).where(Meeting.owner_id == user.id).order_by(Job.created_at.desc()).limit(30)
        call_query = select(AiCallLog).join(Meeting, Meeting.id == AiCallLog.meeting_id).where(Meeting.owner_id == user.id).order_by(AiCallLog.created_at.desc()).limit(30)
        jobs = list(db.scalars(job_query))
        calls = list(db.scalars(call_query))
        job_summary = select(Job).join(Meeting, Meeting.id == Job.meeting_id).where(Meeting.owner_id == user.id)
        call_summary = select(AiCallLog).join(Meeting, Meeting.id == AiCallLog.meeting_id).where(Meeting.owner_id == user.id)
    by_purpose = {}
    for item in calls:
        bucket = by_purpose.setdefault(item.purpose, {"calls": 0, "success": 0, "tokens": 0, "duration_ms": 0})
        bucket["calls"] += 1
        bucket["success"] += int(item.success)
        bucket["tokens"] += item.prompt_tokens + item.completion_tokens
        bucket["duration_ms"] += item.duration_ms
    return {
        "jobs": [job_dict(item) | {"meeting_id": item.meeting_id, "attempt": item.attempt, "created_at": iso(item.created_at)} for item in jobs],
        "ai_calls": [
            {
                "id": item.id, "meeting_id": item.meeting_id, "purpose": item.purpose, "model": item.model,
                "success": item.success, "prompt_tokens": item.prompt_tokens, "completion_tokens": item.completion_tokens,
                "duration_ms": item.duration_ms, "error": item.error, "created_at": iso(item.created_at),
            }
            for item in calls
        ],
        "summary": {
            "jobs_queued": sum(1 for item in db.scalars(job_summary) if item.status == "queued"),
            "jobs_failed": sum(1 for item in db.scalars(job_summary) if item.status == "failed"),
            "ai_calls": sum(1 for _ in db.scalars(call_summary)),
            "ai_failures": sum(1 for item in db.scalars(call_summary) if not item.success),
            "by_purpose": by_purpose,
        },
    }


@app.get("/admin/observability")
def observability(db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    return observability_payload(db, user)


@app.get("/assistant/observability")
def assistant_observability(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Employee-safe observability view for the assistant workbench."""
    return observability_payload(db, user)


def model_config_dict(item: AiModelConfig) -> dict[str, Any]:
    return {
        "id": item.id,
        "purpose": item.purpose,
        "provider": item.provider,
        "model": item.model,
        "base_url": item.base_url,
        "enabled": item.enabled,
        "updated_at": iso(item.updated_at),
    }


@app.get("/admin/models")
def list_model_configs(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    items = list(db.scalars(select(AiModelConfig).order_by(AiModelConfig.purpose)))
    return {"items": [model_config_dict(item) for item in items]}


@app.put("/admin/models/{purpose}")
def update_model_config(
    purpose: str,
    payload: AiModelConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    item = db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == purpose))
    if not item:
        item = AiModelConfig(purpose=purpose)
        db.add(item)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return model_config_dict(item)


def prompt_dict(item: PromptTemplate) -> dict[str, Any]:
    return {
        "id": item.id,
        "purpose": item.purpose,
        "version": item.version,
        "name": item.name,
        "template": item.template,
        "variables": json_loads(item.variables_json, []),
        "enabled": item.enabled,
        "created_at": iso(item.created_at),
    }


@app.get("/admin/prompts")
def list_prompts(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    items = list(db.scalars(select(PromptTemplate).order_by(PromptTemplate.purpose, PromptTemplate.version.desc())))
    return {"items": [prompt_dict(item) for item in items]}


@app.post("/admin/prompts", status_code=201)
def create_prompt(payload: PromptTemplateCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    missing = [name for name in payload.variables if "{{" + name + "}}" not in payload.template]
    if missing:
        raise HTTPException(status_code=422, detail=f"Prompt 缺少变量占位符：{', '.join(missing)}")
    latest = db.scalar(select(func.max(PromptTemplate.version)).where(PromptTemplate.purpose == payload.purpose)) or 0
    db.query(PromptTemplate).filter(PromptTemplate.purpose == payload.purpose).update({"enabled": False})
    item = PromptTemplate(
        purpose=payload.purpose,
        version=latest + 1,
        name=payload.name,
        template=payload.template,
        variables_json=json_dumps(payload.variables),
        enabled=True,
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return prompt_dict(item)


@app.get("/admin/departments")
def list_departments(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    items = list(db.scalars(select(Department).order_by(Department.name)))
    return {"items": [{"id": item.id, "name": item.name, "code": item.code, "enabled": item.enabled} for item in items]}


@app.post("/admin/departments", status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    if db.scalar(select(Department).where((Department.name == payload.name) | (Department.code == payload.code))):
        raise HTTPException(status_code=409, detail="部门名称或编码已存在")
    item = Department(name=payload.name, code=payload.code)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "code": item.code, "enabled": item.enabled}


@app.get("/admin/employees")
def list_employees(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    profiles = {item.user_id: item for item in db.scalars(select(EmployeeProfile))}
    departments = {item.id: item for item in db.scalars(select(Department))}
    items = []
    for user in db.scalars(select(User).order_by(User.created_at.desc())):
        profile = profiles.get(user.id)
        department = departments.get(profile.department_id) if profile and profile.department_id else None
        items.append(
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
                "enabled": user.enabled,
                "title": profile.title if profile else "",
                "department_id": profile.department_id if profile else None,
                "department_name": department.name if department else "",
            }
        )
    return {"items": items}


@app.post("/admin/employees", status_code=201)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()
    db.add(EmployeeProfile(user_id=user.id, department_id=payload.department_id, title=payload.title))
    db.commit()
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "enabled": user.enabled}


@app.patch("/admin/employees/{user_id}")
def update_employee(user_id: int, payload: EmployeeUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    values = payload.model_dump(exclude_unset=True)
    profile_values = {key: values.pop(key) for key in ("department_id", "title") if key in values}
    for field, value in values.items():
        setattr(user, field, value)
    profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user.id))
    if not profile:
        profile = EmployeeProfile(user_id=user.id)
        db.add(profile)
    for field, value in profile_values.items():
        setattr(profile, field, value)
    db.commit()
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "enabled": user.enabled}
