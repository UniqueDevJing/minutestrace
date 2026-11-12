from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ActionItem, Meeting, MinutesVersion, TranscriptSegment, User
from .security import hash_password
from .utils import digest_text, json_dumps


DEMO_TRANSCRIPT = [
    (0, 18000, "speaker-0", "林澄", "本次发布评审确认两个目标：先完成证据跳转，再补齐导出格式。"),
    (18000, 39000, "speaker-1", "周岚", "前端证据卡已经完成，点击决策可以定位到对应转写时间。"),
    (39000, 61000, "speaker-2", "陈舟", "后端需要把 segment id 固化到纪要版本，避免后续编辑导致引用失效。"),
    (61000, 82000, "speaker-0", "林澄", "确认由陈舟在周五前完成证据引用校验，并补一组并发测试。"),
    (82000, 104000, "speaker-1", "周岚", "我负责周四前完成纪要版本对比页面和移动端检查。"),
    (104000, 128000, "speaker-2", "陈舟", "风险是模型可能返回不存在的 segment id，后端必须过滤并标记待确认。"),
    (128000, 151000, "speaker-0", "林澄", "决定所有 Agent 修订先进入人工确认，不能直接覆盖正式纪要。"),
    (151000, 174000, "speaker-1", "周岚", "导出先支持 Word，PDF 中文字体在部署环境确认后开放。"),
]


def seed(db: Session) -> None:
    settings = get_settings()
    if not db.scalar(select(User.id).limit(1)):
        db.add_all(
            [
                User(username="demo", display_name="演示成员", password_hash=hash_password(settings.demo_password), role="employee"),
                User(username="admin", display_name="系统管理员", password_hash=hash_password(settings.demo_password), role="admin"),
            ]
        )
        db.commit()
    if db.scalar(select(Meeting.id).limit(1)):
        return
    demo = db.scalar(select(User).where(User.username == "demo"))
    meeting = Meeting(
        title="证据化纪要发布评审",
        status="ended",
        owner_id=demo.id,
        starts_at=datetime.now() - timedelta(days=1),
        ended_at=datetime.now() - timedelta(days=1) + timedelta(minutes=42),
        agenda="确认证据跳转、纪要版本与人工确认流程的发布范围。",
        participants_json=json_dumps(["林澄", "周岚", "陈舟"]),
    )
    db.add(meeting)
    db.flush()
    segments = []
    for ordinal, (start, end, label, name, text) in enumerate(DEMO_TRANSCRIPT, 1):
        segment = TranscriptSegment(
            meeting_id=meeting.id,
            ordinal=ordinal,
            start_ms=start,
            end_ms=end,
            speaker_label=label,
            speaker_name=name,
            text=text,
        )
        db.add(segment)
        segments.append(segment)
    db.flush()
    ids = [segment.id for segment in segments]
    content = {
        "summary": "发布评审确认证据跳转、纪要版本和人工确认三项范围，Word 导出进入首发，PDF 待部署字体验证。",
        "topics": [
            {"title": "证据引用", "summary": "纪要条目绑定稳定的转写片段，并在后端过滤无效引用。", "evidence_segment_ids": ids[:6]},
            {"title": "修订发布", "summary": "Agent 修订必须经过人工确认后才能成为正式版本。", "evidence_segment_ids": [ids[6]]},
        ],
        "decisions": [
            {"text": "Agent 修订不得直接覆盖正式纪要。", "evidence_segment_ids": [ids[6]], "needs_confirmation": False},
            {"text": "首发支持 Word 导出。", "evidence_segment_ids": [ids[7]], "needs_confirmation": False},
        ],
        "action_items": [
            {"text": "完成证据引用校验和并发测试", "owner": "陈舟", "due": "周五前", "evidence_segment_ids": [ids[3]]},
            {"text": "完成版本对比页面和移动端检查", "owner": "周岚", "due": "周四前", "evidence_segment_ids": [ids[4]]},
        ],
        "open_questions": [{"text": "PDF 中文字体需要在部署环境确认。", "evidence_segment_ids": [ids[7]]}],
        "risks": [{"text": "模型可能返回不存在的 segment id。", "evidence_segment_ids": [ids[5]]}],
    }
    version = MinutesVersion(
        meeting_id=meeting.id,
        version=1,
        status="approved",
        source_digest=digest_text([segment.text for segment in segments]),
        content_json=json_dumps(content),
        created_by=demo.id,
    )
    db.add(version)
    db.flush()
    for item in content["action_items"]:
        db.add(
            ActionItem(
                meeting_id=meeting.id,
                minutes_version_id=version.id,
                title=item["text"],
                owner_name=item["owner"],
                due_text=item["due"],
                evidence_json=json_dumps(item["evidence_segment_ids"]),
            )
        )
    db.commit()
