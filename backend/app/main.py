from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
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
    Job,
    Meeting,
    MeetingAsset,
    MinutesVersion,
    TranscriptSegment,
    User,
)
from .schemas import LoginRequest, MeetingCreate, MeetingUpdate, RunDecision, SegmentUpdate
from .security import current_user, issue_token, require_admin, verify_password
from .seed import seed
from .utils import iso, json_dumps, json_loads
from .worker import create_job, sign_asset


settings = get_settings()


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
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_meeting(db: Session, meeting_id: int) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")
    return meeting


def ensure_run(db: Session, run_id: int) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="审校运行不存在")
    return run


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
def dashboard(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    meetings = list(db.scalars(select(Meeting).order_by(Meeting.starts_at.desc()).limit(6)))
    action_items = list(db.scalars(select(ActionItem).where(ActionItem.status == "open").order_by(ActionItem.created_at.desc()).limit(8)))
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
    }


@app.get("/meetings")
def list_meetings(
    query: str = Query(default="", max_length=120),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict[str, Any]:
    statement = select(Meeting).order_by(Meeting.starts_at.desc())
    if query.strip():
        statement = statement.where(Meeting.title.like(f"%{query.strip()}%"))
    items = list(db.scalars(statement.limit(100)))
    return {"items": [meeting_dict(db, item) for item in items], "total": len(items)}


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
def get_meeting(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return meeting_dict(db, ensure_meeting(db, meeting_id), detailed=True)


@app.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: int, payload: MeetingUpdate, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    meeting = ensure_meeting(db, meeting_id)
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
    _: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
    safe_name = Path(file.filename or "upload.bin").name
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
        media_type = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
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
def queue_transcription(meeting_id: int, asset_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
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
def transcript(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ordinal)))
    return {"items": [segment_dict(item) for item in segments], "total": len(segments)}


@app.patch("/transcript-segments/{segment_id}")
def update_segment(segment_id: int, payload: SegmentUpdate, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    segment = db.get(TranscriptSegment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="转写片段不存在")
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
    _: User = Depends(current_user),
) -> dict[str, Any]:
    meeting = ensure_meeting(db, meeting_id)
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
def queue_minutes(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ordinal)))
    if not segments:
        raise HTTPException(status_code=422, detail="请先完成会议转写")
    source_digest = hashlib.sha256("\n".join(item.text for item in segments).encode()).hexdigest()
    job = create_job(db, "minutes_generation", meeting_id, f"minutes:{meeting_id}:{source_digest}")
    if job.status == "failed":
        raise HTTPException(status_code=409, detail="纪要生成已达到最大重试次数，请修改转写后重试")
    return job_dict(job)


@app.get("/meetings/{meeting_id}/minutes")
def get_minutes(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
    versions = list(db.scalars(select(MinutesVersion).where(MinutesVersion.meeting_id == meeting_id).order_by(MinutesVersion.version.desc())))
    return {"current": version_dict(db, versions[0]) if versions else None, "versions": [version_dict(db, item) for item in versions]}


@app.post("/meetings/{meeting_id}/review-runs", status_code=202)
def queue_review(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    ensure_meeting(db, meeting_id)
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
def get_review(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return run_dict(db, ensure_run(db, run_id))


@app.get("/review-runs/{run_id}/events")
def review_events(
    request: Request,
    run_id: int,
    token: str = Query(default=""),
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    # EventSource cannot set Authorization headers, so validate a short-lived bearer token from the query.
    from .security import bearer as _unused  # noqa: F401
    import jwt

    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc

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
    run = ensure_run(db, run_id)
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
def export_minutes(meeting_id: int, format: str = Query(default="docx", pattern="^(docx|pdf)$"), db: Session = Depends(get_db), _: User = Depends(current_user)) -> Response:
    meeting = ensure_meeting(db, meeting_id)
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


@app.get("/admin/observability")
def observability(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(30)))
    calls = list(db.scalars(select(AiCallLog).order_by(AiCallLog.created_at.desc()).limit(30)))
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
            "jobs_queued": db.scalar(select(func.count(Job.id)).where(Job.status == "queued")) or 0,
            "jobs_failed": db.scalar(select(func.count(Job.id)).where(Job.status == "failed")) or 0,
            "ai_calls": db.scalar(select(func.count(AiCallLog.id))) or 0,
            "ai_failures": db.scalar(select(func.count(AiCallLog.id)).where(AiCallLog.success.is_(False))) or 0,
        },
    }
