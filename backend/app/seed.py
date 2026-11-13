"""Development/demo seed data.

The seed is deterministic and additive: it enriches an empty or partially
seeded workspace without touching user-created meetings. Production never
receives demo identities, files, or meetings.
"""

from datetime import datetime, timedelta
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    ActionItem, AgentRun, AgentStep, AiCallLog, AiModelConfig, Department,
    EmployeeProfile, Job, Meeting, MeetingAsset, MinutesVersion, PromptTemplate,
    TranscriptSegment, User,
)
from .security import hash_password
from .utils import digest_text, json_dumps


DEMO_MEETINGS = [
    {
        "key": "release-review", "title": "证据化纪要发布评审", "status": "ended", "days": -1, "duration": 42,
        "participants": ["林澄", "周岚", "陈舟"], "agenda": "确认证据跳转、纪要版本与人工确认流程的发布范围。", "file": "release-review.md",
        "segments": [
            ("林澄", "本次发布评审确认两个目标：先完成证据跳转，再补齐导出格式。"),
            ("周岚", "前端证据卡已经完成，点击决策可以定位到对应转写时间。"),
            ("陈舟", "后端需要把 segment id 固化到纪要版本，避免后续编辑导致引用失效。"),
            ("林澄", "确认由陈舟在周五前完成证据引用校验，并补一组并发测试。"),
            ("周岚", "我负责周四前完成纪要版本对比页面和移动端检查。"),
            ("陈舟", "风险是模型可能返回不存在的 segment id，后端必须过滤并标记待确认。"),
            ("林澄", "决定所有 Agent 修订先进入人工确认，不能直接覆盖正式纪要。"),
            ("周岚", "导出先支持 Word，PDF 中文字体在部署环境确认后开放。"),
        ],
        "version_status": "approved", "summary": "发布评审确认证据跳转、纪要版本和人工确认三项范围，Word 导出进入首发，PDF 待部署字体验证。",
        "topics": [("证据引用", "纪要条目绑定稳定的转写片段，并在后端过滤无效引用", [0, 1, 2, 3, 5]), ("修订发布", "Agent 修订必须经过人工确认后才能成为正式版本", [6])],
        "decisions": [("Agent 修订不得直接覆盖正式纪要。", [6]), ("首发支持 Word 导出。", [7])],
        "actions": [("完成证据引用校验和并发测试", "陈舟", "周五前", [3]), ("完成版本对比页面和移动端检查", "周岚", "周四前", [4])],
        "questions": [("PDF 中文字体需要在部署环境确认。", [7])], "risks": [("模型可能返回不存在的 segment id。", [5])],
    },
    {
        "key": "growth-retro", "title": "Q4 产品复盘与增长计划", "status": "ended", "days": -3, "duration": 55,
        "participants": ["顾言", "林澄", "沈禾", "许哲"], "agenda": "复盘季度指标，确认下一季度的增长实验和负责人。", "file": "growth-retro.md",
        "segments": [
            ("顾言", "本季度留存率提升到 42%，但新用户首次使用仍然缺少引导。"),
            ("沈禾", "建议把首次导入、证据定位和导出放到同一条新手路径。"),
            ("林澄", "确认下季度优先做新手路径，目标是把首个有效纪要时间降到十分钟。"),
            ("许哲", "我负责埋点方案和漏斗看板，周三前提交第一版字段清单。"),
            ("顾言", "风险是只看点击率会忽略纪要是否真的被复用，需要补充回访指标。"),
            ("沈禾", "待确认是否把客户成功团队纳入每周复盘，先做两周试点。"),
        ],
        "version_status": "waiting_human", "summary": "会议确认以新手路径作为下一季度首要增长实验，并要求同时跟踪纪要复用率与回访结果。",
        "topics": [("增长实验", "围绕首个有效纪要设计连续引导", [0, 1, 2]), ("指标补充", "新增复用率和回访指标", [4, 5])],
        "decisions": [("下季度优先建设新手路径。", [2])],
        "actions": [("提交埋点字段清单", "许哲", "周三前", [3]), ("设计客户成功试点", "沈禾", "两周内", [5])],
        "questions": [("是否把客户成功团队纳入每周复盘。", [5])], "risks": [("单看点击率会忽略纪要复用效果。", [4])],
    },
    {
        "key": "customer-success", "title": "客户成功周会 · 续约风险复盘", "status": "ended", "days": -6, "duration": 36,
        "participants": ["唐宁", "苏芮", "周岚"], "agenda": "检查重点客户续约风险，明确跟进动作和时间节点。", "file": "customer-success.md",
        "segments": [
            ("唐宁", "A 客户的使用频率下降，主要卡在资料导入和权限配置。"),
            ("苏芮", "我负责本周完成权限梳理，并约客户做一次远程配置。"),
            ("周岚", "可以把权限检查加入资料导入前的自检清单，减少重复沟通。"),
            ("唐宁", "决定先用一个客户验证清单，再评估是否推广到全部团队。"),
            ("苏芮", "如果周五仍未恢复使用，需要升级到续约风险观察名单。"),
        ],
        "version_status": "approved", "summary": "会议确定先以 A 客户验证权限自检清单，并设置周五的续约风险升级节点。",
        "topics": [("客户阻塞", "资料导入和权限配置影响使用频率", [0, 1, 2]), ("风险升级", "周五未恢复使用则进入观察名单", [4])],
        "decisions": [("先在 A 客户验证权限自检清单。", [3])],
        "actions": [("完成权限梳理并远程配置", "苏芮", "本周内", [1]), ("复盘周五使用恢复情况", "唐宁", "周五", [4])],
        "questions": [], "risks": [("客户使用频率持续下降可能影响续约。", [0, 4])],
    },
    {
        "key": "iteration-kickoff", "title": "研发迭代启动会 · 证据链体验", "status": "scheduled", "days": 1, "duration": 45,
        "participants": ["陈舟", "沈禾", "许哲"], "agenda": "确认本迭代的证据卡体验、任务拆分和验收口径。", "file": "iteration-kickoff.md",
        "segments": [], "version_status": None, "summary": "待会议结束后导入资料并生成正式纪要。", "topics": [], "decisions": [], "actions": [], "questions": [], "risks": [],
    },
]


def _get_or_create_user(db: Session, username: str, display_name: str, role: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user:
        return user
    user = User(username=username, display_name=display_name, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    return user


def _ensure_demo_asset(settings, db: Session, meeting: Meeting, file_name: str, content: str) -> MeetingAsset:
    asset = db.scalar(select(MeetingAsset).where(MeetingAsset.meeting_id == meeting.id, MeetingAsset.file_name == file_name))
    storage_dir = Path(settings.storage_dir) / "demo"
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / file_name
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if asset:
        asset.storage_path = str(path.resolve()); asset.size_bytes = len(content.encode("utf-8")); asset.sha256 = digest
        return asset
    asset = MeetingAsset(meeting_id=meeting.id, file_name=file_name, media_type="text/markdown", size_bytes=len(content.encode("utf-8")), sha256=digest, storage_path=str(path.resolve()), kind="document", metadata_json=json_dumps({"source": "demo-seed", "editable": False}))
    db.add(asset); db.flush(); return asset


def _content(item: dict, segment_ids: list[int]) -> dict:
    evidence = lambda indexes: [segment_ids[index] for index in indexes if index < len(segment_ids)]
    return {
        "summary": item["summary"],
        "topics": [{"title": title, "summary": summary, "evidence_segment_ids": evidence(indexes)} for title, summary, indexes in item["topics"]],
        "decisions": [{"text": text, "evidence_segment_ids": evidence(indexes), "needs_confirmation": False} for text, indexes in item["decisions"]],
        "action_items": [{"text": text, "owner": owner, "due": due, "evidence_segment_ids": evidence(indexes)} for text, owner, due, indexes in item["actions"]],
        "open_questions": [{"text": text, "evidence_segment_ids": evidence(indexes)} for text, indexes in item["questions"]],
        "risks": [{"text": text, "evidence_segment_ids": evidence(indexes)} for text, indexes in item["risks"]],
    }


def _seed_meeting(db: Session, settings, owner: User, item: dict) -> Meeting:
    meeting = db.scalar(select(Meeting).where(Meeting.title == item["title"]))
    starts_at = datetime.now() + timedelta(days=item["days"])
    if not meeting:
        meeting = Meeting(title=item["title"], status=item["status"], owner_id=owner.id, starts_at=starts_at, ended_at=starts_at + timedelta(minutes=item["duration"]) if item["status"] == "ended" else None, agenda=item["agenda"], participants_json=json_dumps(item["participants"]))
        db.add(meeting); db.flush()
    else:
        if not meeting.participants_json: meeting.participants_json = json_dumps(item["participants"])
        if not meeting.agenda: meeting.agenda = item["agenda"]

    transcript_text = "\n".join(f"{speaker}：{text}" for speaker, text in item["segments"])
    asset = _ensure_demo_asset(settings, db, meeting, item["file"], transcript_text) if item["file"] else None
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id).order_by(TranscriptSegment.ordinal)))
    if item["segments"] and not segments:
        for ordinal, (speaker, text) in enumerate(item["segments"], 1):
            start = (ordinal - 1) * 22000
            db.add(TranscriptSegment(meeting_id=meeting.id, ordinal=ordinal, start_ms=start, end_ms=start + 20000, speaker_label=f"speaker-{(ordinal - 1) % 3}", speaker_name=speaker, text=text, evidence_hash=digest_text([text])))
        db.flush(); segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id).order_by(TranscriptSegment.ordinal)))
    if asset and not db.scalar(select(Job).where(Job.idempotency_key == f"seed:transcription:{item['key']}")):
        db.add(Job(kind="transcription", status="succeeded", progress=100, meeting_id=meeting.id, asset_id=asset.id, idempotency_key=f"seed:transcription:{item['key']}", result_json=json_dumps({"segments": len(segments), "source": "demo-seed"})))

    if item["version_status"] and segments:
        version = db.scalar(select(MinutesVersion).where(MinutesVersion.meeting_id == meeting.id).order_by(MinutesVersion.version.desc()).limit(1))
        if not version:
            segment_ids = [segment.id for segment in segments]
            version = MinutesVersion(meeting_id=meeting.id, version=1, status=item["version_status"], source_digest=digest_text([segment.text for segment in segments]), content_json=json_dumps(_content(item, segment_ids)), created_by=owner.id)
            db.add(version); db.flush()
            for text, action_owner, due, indexes in item["actions"]:
                db.add(ActionItem(meeting_id=meeting.id, minutes_version_id=version.id, title=text, owner_name=action_owner, due_text=due, status="done" if item["key"] == "customer-success" and text.startswith("完成") else "open", evidence_json=json_dumps([segment_ids[index] for index in indexes if index < len(segment_ids)])))
        if not db.scalar(select(AgentRun).where(AgentRun.meeting_id == meeting.id)):
            run_status = "waiting_human" if item["version_status"] == "waiting_human" else "approved"
            score = 86.0 if run_status == "waiting_human" else 96.0
            run = AgentRun(meeting_id=meeting.id, minutes_version_id=version.id, status=run_status, current_round=1, max_rounds=2, score=score, issues_json=json_dumps([{"field": "action_items", "severity": "medium", "message": "请确认负责人和截止时间是否仍然有效。"}]) if run_status == "waiting_human" else "[]", revised_json=version.content_json, decision_reason="演示数据：已完成人工确认" if run_status == "approved" else "演示数据：等待负责人确认")
            db.add(run); db.flush()
            for sequence, (node, summary) in enumerate([("load_context", "读取会议资料和最新纪要版本"), ("audit", "检查证据覆盖、负责人和截止时间"), ("revise", "生成可供人工确认的修订建议")], 1):
                db.add(AgentStep(run_id=run.id, sequence=sequence, node=node, status="succeeded", summary=summary, detail_json=json_dumps({"source": "demo-seed", "evidence_count": len(segments)}), duration_ms=120 + sequence * 80))
            if not db.scalar(select(Job).where(Job.idempotency_key == f"seed:review:{item['key']}")):
                db.add(Job(kind="agent_review", status="succeeded", progress=100, meeting_id=meeting.id, run_id=run.id, idempotency_key=f"seed:review:{item['key']}", result_json=json_dumps({"run_id": run.id, "score": score, "source": "demo-seed"})))
        if not db.scalar(select(Job).where(Job.idempotency_key == f"seed:minutes:{item['key']}")):
            db.add(Job(kind="minutes_generation", status="succeeded", progress=100, meeting_id=meeting.id, idempotency_key=f"seed:minutes:{item['key']}", result_json=json_dumps({"source": "demo-seed"})))
        call_defaults = {"transcription": ("paraformer-v2", 900, 0, 1340), "minutes_generation": (settings.llm_model, 1450, 680, 2140), "minutes_review": (settings.llm_model, 980, 420, 1760)}
        for purpose, (model, prompt_tokens, completion_tokens, duration_ms) in call_defaults.items():
            if not db.scalar(select(AiCallLog).where(AiCallLog.meeting_id == meeting.id, AiCallLog.purpose == purpose)):
                db.add(AiCallLog(meeting_id=meeting.id, purpose=purpose, model=model, success=True, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, duration_ms=duration_ms))
    return meeting


def seed(db: Session) -> None:
    settings = get_settings(); production = settings.environment.lower() in {"production", "prod"}
    demo = admin = None
    demo_enabled = (not production) or settings.public_demo
    if demo_enabled:
        demo = _get_or_create_user(db, "demo", "演示成员", "employee", settings.demo_password)
        admin = _get_or_create_user(db, "admin", "系统管理员", "admin", settings.demo_password)
    department = db.scalar(select(Department).where(Department.code == "product"))
    if not department:
        department = Department(name="产品与工程", code="product"); db.add(department); db.flush()
    for user, title in ((demo, "项目成员"), (admin, "系统管理员")):
        if user and not db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)):
            db.add(EmployeeProfile(user_id=user.id, department_id=department.id, title=title))
    model_defaults = {"transcription": ("paraformer-v2", settings.asr_base_url), "minutes_generation": (settings.llm_model, settings.llm_base_url), "minutes_review": (settings.llm_model, settings.llm_base_url), "speaker_matching": (settings.llm_model, settings.llm_base_url)}
    for purpose, (model, base_url) in model_defaults.items():
        if not db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == purpose)):
            db.add(AiModelConfig(purpose=purpose, model=model, base_url=base_url))
    prompt_defaults = {"minutes_generation": ("纪要生成", "你是会议纪要提取器。只记录转写中出现的事实。负责人或日期不明确时写待确认。每一项必须引用真实 segment id。只输出 JSON。"), "minutes_review": ("纪要审查", "对照转写审查纪要。分别检查完整性、可落实性和无来源事实。只输出 {issues:[{field,index,severity,message}]} JSON。"), "minutes_revision": ("纪要修订", "按问题清单修订纪要。不得新增转写中没有的事实，必须保留 evidence_segment_ids；缺失负责人或日期写待确认。输出完整纪要 JSON。"), "speaker_matching": ("说话人匹配", "根据参会人名单和转写片段，建议 speaker_label 对应的人。只能从参会人名单中选择，无法判断时使用待确认。只输出 JSON。")}
    for purpose, (name, template) in prompt_defaults.items():
        if not db.scalar(select(PromptTemplate).where(PromptTemplate.purpose == purpose, PromptTemplate.version == 1)):
            db.add(PromptTemplate(purpose=purpose, version=1, name=name, template=template, created_by=admin.id if admin else None))
    db.commit()
    if not demo_enabled or not demo: return
    for item in DEMO_MEETINGS: _seed_meeting(db, settings, demo, item)
    db.commit()
