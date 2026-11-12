import hashlib
import hmac
import json
import mimetypes
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .agent_graph import build_review_graph
from .ai import QwenClient
from .config import get_settings
from .database import SessionLocal, init_db
from .models import AgentRun, AgentStep, AiCallLog, AiModelConfig, Job, Meeting, MeetingAsset, MinutesVersion, TranscriptSegment, utcnow
from .schemas import MinutesContent
from .seed import seed
from .utils import digest_text, json_dumps, json_loads


TERMINAL_JOBS = {"succeeded", "failed", "cancelled"}


def sign_asset(asset_id: int, expires: int) -> str:
    secret = get_settings().jwt_secret.encode()
    return hmac.new(secret, f"{asset_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def public_asset_url(asset_id: int) -> str:
    expires = int(time.time()) + 3600
    signature = sign_asset(asset_id, expires)
    return f"{get_settings().public_base_url.rstrip('/')}/assets/public/{asset_id}?expires={expires}&sig={signature}"


def create_job(db: Session, kind: str, meeting_id: int, idempotency_key: str, asset_id: int | None = None, run_id: int | None = None) -> Job:
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing and existing.status not in {"failed", "cancelled"}:
        return existing
    if existing:
        if existing.attempt >= get_settings().job_max_attempts:
            return existing
        existing.status = "queued"
        existing.progress = 0
        existing.error = ""
        existing.attempt += 1
        existing.updated_at = utcnow()
        db.commit()
        return existing
    job = Job(kind=kind, meeting_id=meeting_id, asset_id=asset_id, run_id=run_id, idempotency_key=idempotency_key)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def parse_text_transcript(path: Path) -> list[dict[str, Any]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    segments = []
    for index, line in enumerate(lines):
        matched = re.match(r"(?:\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*)?(?:([^：:]{1,24})[：:])?\s*(.+)", line)
        if not matched:
            continue
        hours_or_minutes, minutes_or_seconds, seconds, speaker, text = matched.groups()
        if seconds is None:
            start_ms = ((int(hours_or_minutes or 0) * 60) + int(minutes_or_seconds or 0)) * 1000
        else:
            start_ms = ((int(hours_or_minutes or 0) * 3600) + int(minutes_or_seconds or 0) * 60 + int(seconds)) * 1000
        if start_ms == 0 and index:
            start_ms = index * 15000
        segments.append(
            {
                "start_ms": start_ms,
                "end_ms": start_ms + 15000,
                "speaker_label": f"speaker-{index % 3}",
                "speaker_name": speaker,
                "text": text,
            }
        )
    return segments


def _probe_duration_ms(path: Path) -> int | None:
    settings = get_settings()
    try:
        result = subprocess.run(
            [settings.ffmpeg_path, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    matched = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not matched:
        return None
    hours, minutes, seconds = matched.groups()
    return int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_audio_assets(db: Session, asset: MeetingAsset) -> list[tuple[MeetingAsset, int]]:
    settings = get_settings()
    path = Path(asset.storage_path)
    duration_ms = _probe_duration_ms(path)
    limit_ms = settings.asr_segment_minutes * 60 * 1000
    if not duration_ms or duration_ms <= limit_ms:
        return [(asset, 0)]
    chunk_dir = path.parent / "chunks" / str(asset.id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    pattern = chunk_dir / "part-%03d.wav"
    try:
        subprocess.run(
            [
                settings.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "segment",
                "-segment_time",
                str(settings.asr_segment_minutes * 60),
                "-reset_timestamps",
                "1",
                str(pattern),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # shortcut: if ffmpeg is unavailable, let the provider handle the original file.
        return [(asset, 0)]
    files = sorted(chunk_dir.glob("part-*.wav"))
    if len(files) <= 1:
        return [(asset, 0)]
    chunks: list[tuple[MeetingAsset, int]] = []
    for index, chunk_path in enumerate(files):
        sha256 = _file_sha256(chunk_path)
        chunk = db.scalar(select(MeetingAsset).where(MeetingAsset.sha256 == sha256, MeetingAsset.kind == "audio_chunk"))
        if not chunk:
            chunk = MeetingAsset(
                meeting_id=asset.meeting_id,
                file_name=chunk_path.name,
                media_type="audio/wav",
                size_bytes=chunk_path.stat().st_size,
                sha256=sha256,
                storage_path=str(chunk_path.resolve()),
                kind="audio_chunk",
                metadata_json=json_dumps({"source_asset_id": asset.id, "chunk_index": index}),
            )
            db.add(chunk)
            db.flush()
        chunks.append((chunk, index * limit_ms))
    db.commit()
    return chunks


def asr_transcribe(db: Session, asset: MeetingAsset, offset_ms: int = 0) -> list[dict[str, Any]]:
    settings = get_settings()
    model_config = db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == "transcription"))
    if model_config and not model_config.enabled:
        raise RuntimeError("转写模型已停用")
    asr_model = model_config.model if model_config else settings.asr_model
    asr_base_url = model_config.base_url if model_config else settings.asr_base_url
    started = time.perf_counter()
    success = False
    error = ""
    if not settings.llm_api_key:
        error = "服务器尚未配置百炼 API Key，文本资料仍可直接导入"
        raise RuntimeError(error)
    try:
        submit = httpx.post(
            f"{asr_base_url.rstrip('/')}/services/audio/asr/transcription",
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "X-DashScope-Async": "enable"},
            json={
                "model": asr_model,
                "input": {"file_urls": [public_asset_url(asset.id)]},
                "parameters": {"channel_id": [0], "diarization_enabled": True, "language_hints": ["zh", "en"]},
            },
            timeout=30,
        )
        submit.raise_for_status()
        task_id = submit.json()["output"]["task_id"]
        deadline = time.time() + 1800
        while time.time() < deadline:
            response = httpx.get(
                f"{asr_base_url.rstrip('/')}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
            status = body.get("output", {}).get("task_status")
            if status == "SUCCEEDED":
                result_url = body["output"]["results"][0]["transcription_url"]
                transcript = httpx.get(result_url, timeout=60).json()
                sentences = (transcript.get("transcripts") or [{}])[0].get("sentences") or []
                success = True
                return [
                    {
                        "start_ms": int(sentence.get("begin_time") or 0) + offset_ms,
                        "end_ms": int(sentence.get("end_time") or 0) + offset_ms,
                        "speaker_label": f"speaker-{sentence.get('speaker_id', 0)}",
                        "speaker_name": None,
                        "text": sentence.get("text", "").strip(),
                    }
                    for sentence in sentences
                    if sentence.get("text")
                ]
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise RuntimeError(body.get("output", {}).get("message") or f"转写任务失败：{status}")
            time.sleep(5)
        raise TimeoutError("转写任务超过 30 分钟")
    except Exception as exc:
        error = str(exc)[:500]
        raise
    finally:
        db.add(
            AiCallLog(
                meeting_id=asset.meeting_id,
                purpose="transcription",
                model=asr_model,
                success=success,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )
        )
        db.commit()


def transcribe_job(db: Session, job: Job) -> None:
    asset = db.get(MeetingAsset, job.asset_id)
    if not asset:
        raise RuntimeError("没有可转写的会议资料")
    path = Path(asset.storage_path)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".srt", ".vtt"}:
        segments = parse_text_transcript(path)
    else:
        chunks = split_audio_assets(db, asset)
        segments = []
        for chunk_index, (chunk, offset_ms) in enumerate(chunks):
            part = asr_transcribe(db, chunk, offset_ms)
            if len(chunks) > 1:
                for segment in part:
                    segment["speaker_label"] = f"part-{chunk_index + 1:02d}-{segment['speaker_label']}"
            segments.extend(part)
            job.progress = min(95, 10 + int((chunk_index + 1) / len(chunks) * 80))
            db.commit()
    if not segments:
        raise RuntimeError("资料中没有可用的转写内容")
    db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == job.meeting_id))
    for ordinal, segment in enumerate(segments, 1):
        db.add(TranscriptSegment(meeting_id=job.meeting_id, ordinal=ordinal, **segment))
    job.progress = 100
    job.result_json = json_dumps({"segments": len(segments)})


def fallback_minutes(segments: list[TranscriptSegment]) -> dict[str, Any]:
    evidence = [segment.id for segment in segments]
    text = "".join(segment.text for segment in segments)
    decisions = []
    actions = []
    risks = []
    questions = []
    for segment in segments:
        item = {"text": segment.text, "evidence_segment_ids": [segment.id]}
        if any(word in segment.text for word in ("决定", "确认", "同意", "采用")):
            decisions.append({**item, "needs_confirmation": False})
        if any(word in segment.text for word in ("负责", "完成", "跟进", "提交")):
            actions.append({**item, "owner": segment.speaker_name or "待确认", "due": "待确认"})
        if any(word in segment.text for word in ("风险", "延期", "阻塞", "失败")):
            risks.append(item)
        if any(word in segment.text for word in ("待确认", "还需要", "尚未")):
            questions.append(item)
    return {
        "summary": text[:180] or "会议转写已完成，等待人工补充摘要。",
        "topics": [{"title": "会议讨论", "summary": text[:240], "evidence_segment_ids": evidence[:8]}],
        "decisions": decisions,
        "action_items": actions,
        "open_questions": questions,
        "risks": risks,
    }


def minutes_job(db: Session, job: Job) -> None:
    meeting = db.get(Meeting, job.meeting_id)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == job.meeting_id).order_by(TranscriptSegment.ordinal)))
    if not meeting or not segments:
        raise RuntimeError("请先完成会议转写")
    transcript = [
        {"id": item.id, "start_ms": item.start_ms, "end_ms": item.end_ms, "speaker": item.speaker_name or item.speaker_label, "text": item.text}
        for item in segments
    ]
    content = QwenClient(db, meeting.id).generate_minutes(transcript, meeting.title) or fallback_minutes(segments)
    content = MinutesContent.model_validate(content).model_dump(mode="json")
    valid_ids = {item.id for item in segments}
    for field in ("topics", "decisions", "action_items", "open_questions", "risks"):
        for item in content.get(field) or []:
            item["evidence_segment_ids"] = [int(value) for value in item.get("evidence_segment_ids", []) if int(value) in valid_ids]
    next_version = (db.scalar(select(func.max(MinutesVersion.version)).where(MinutesVersion.meeting_id == meeting.id)) or 0) + 1
    version = MinutesVersion(
        meeting_id=meeting.id,
        version=next_version,
        status="draft",
        source_digest=digest_text([segment.text for segment in segments]),
        content_json=json_dumps(content),
        created_by=meeting.owner_id,
    )
    db.add(version)
    db.flush()
    job.progress = 100
    job.result_json = json_dumps({"minutes_version_id": version.id})


def review_job(db: Session, job: Job) -> None:
    run = db.get(AgentRun, job.run_id)
    if not run:
        raise RuntimeError("Agent 运行不存在")
    version = db.get(MinutesVersion, run.minutes_version_id)
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == run.meeting_id).order_by(TranscriptSegment.ordinal)))
    transcript = [
        {"id": item.id, "start_ms": item.start_ms, "end_ms": item.end_ms, "speaker": item.speaker_name or item.speaker_label, "text": item.text}
        for item in segments
    ]
    state: dict[str, Any] = {
        "minutes": json_loads(run.revised_json, {}) or json_loads(version.content_json, {}),
        "transcript": transcript,
        "issues": [],
        "score": 0.0,
        "passed": False,
        "current_round": run.current_round,
        "max_rounds": run.max_rounds,
    }
    run.status = "running"
    db.commit()
    graph = build_review_graph(QwenClient(db, run.meeting_id))
    sequence = db.scalar(select(func.max(AgentStep.sequence)).where(AgentStep.run_id == run.id)) or 0
    for update_event in graph.stream(state, stream_mode="updates"):
        db.refresh(run)
        if run.cancel_requested:
            run.status = "cancelled"
            job.status = "cancelled"
            db.commit()
            return
        for node, changes in update_event.items():
            started = time.perf_counter()
            state.update(changes)
            sequence += 1
            run.current_round = state["current_round"]
            run.score = state["score"]
            run.issues_json = json_dumps(state["issues"])
            run.revised_json = json_dumps(state["minutes"])
            db.add(
                AgentStep(
                    run_id=run.id,
                    sequence=sequence,
                    node=node,
                    summary="审查纪要完整性与可落实性" if node == "audit" else "按问题清单生成修订稿",
                    detail_json=json_dumps(changes),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            db.commit()
    run.status = "waiting_human"
    job.progress = 100
    job.result_json = json_dumps({"run_id": run.id, "score": run.score})


def process(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        job.attempt += 1
        job.status = "running"
        job.progress = 5
        job.heartbeat_at = utcnow()
        db.commit()
        try:
            if job.kind == "transcription":
                transcribe_job(db, job)
            elif job.kind == "minutes_generation":
                minutes_job(db, job)
            elif job.kind == "agent_review":
                review_job(db, job)
            else:
                raise RuntimeError(f"未知任务类型：{job.kind}")
            if job.status not in TERMINAL_JOBS:
                job.status = "succeeded"
            job.progress = 100
        except Exception as exc:
            should_retry = job.attempt < get_settings().job_max_attempts
            job.status = "queued" if should_retry else "failed"
            job.error = str(exc)[:2000]
            if job.run_id:
                run = db.get(AgentRun, job.run_id)
                if run:
                    run.status = "queued" if should_retry else "failed"
        finally:
            job.heartbeat_at = utcnow()
            db.commit()


def claim_next_job(db: Session) -> int | None:
    job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1))
    if not job:
        return None
    changed = db.execute(update(Job).where(Job.id == job.id, Job.status == "queued").values(status="running", heartbeat_at=utcnow()))
    db.commit()
    return job.id if changed.rowcount == 1 else None


def recover_stale_jobs(db: Session) -> None:
    cutoff = utcnow() - timedelta(seconds=get_settings().worker_stale_seconds)
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.heartbeat_at < cutoff, Job.attempt < get_settings().job_max_attempts)
        .values(status="queued", error="任务在服务重启后自动恢复")
    )
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.heartbeat_at < cutoff, Job.attempt >= get_settings().job_max_attempts)
        .values(status="failed", error="任务超过最大重试次数")
    )
    db.execute(update(AgentRun).where(AgentRun.status == "running").values(status="queued"))
    db.commit()


def run_forever() -> None:
    init_db()
    with SessionLocal() as db:
        seed(db)
        recover_stale_jobs(db)
    while True:
        with SessionLocal() as db:
            job_id = claim_next_job(db)
        if job_id:
            process(job_id)
        else:
            time.sleep(1.5)


if __name__ == "__main__":
    run_forever()
