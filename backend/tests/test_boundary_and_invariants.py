from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from sqlalchemy import select
from fastapi.testclient import TestClient

from app.agent_graph import rule_issues, safe_revision
from app.config import get_settings
from app.database import SessionLocal
from app.models import Job, User
from app.worker import process, sign_asset


def create_meeting(client: TestClient, auth: dict[str, str], *, title: str = "测试会议") -> int:
    response = client.post(
        "/meetings",
        headers=auth,
        json={
            "title": title,
            "starts_at": datetime.now(timezone.utc).isoformat(),
            "participants": ["林澄", "周岚"],
            "agenda": "验证会议链路",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_text(client: TestClient, auth: dict[str, str], meeting_id: int, content: str = "[00:01] 林澄：确认上线。") -> int:
    response = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("meeting.txt", content, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def prepare_review(client: TestClient, auth: dict[str, str], *, process_review: bool = True) -> tuple[int, int]:
    meeting_id = create_meeting(client, auth, title="审校状态机测试")
    upload_text(client, auth, meeting_id, "[00:01] 林澄：确认发布范围。\n[00:20] 周岚：我负责周五前完成检查。")
    transcription = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    assert transcription.status_code == 202
    process(transcription.json()["id"])
    minutes = client.post(f"/meetings/{meeting_id}/minutes/generate", headers=auth)
    assert minutes.status_code == 202
    process(minutes.json()["id"])
    review = client.post(f"/meetings/{meeting_id}/review-runs", headers=auth)
    assert review.status_code == 202
    run_id = review.json()["id"]
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.run_id == run_id))
        assert job is not None
        job_id = job.id
    if process_review:
        process(job_id)
    return meeting_id, run_id


def test_pytest_entrypoint_and_health_are_runnable(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_validation_rejects_empty_and_extreme_meeting_fields(client: TestClient, auth: dict[str, str]):
    too_long_title = "会" * 121
    too_long_agenda = "议" * 4001
    assert client.post(
        "/meetings",
        headers=auth,
        json={"title": "", "starts_at": datetime.now(timezone.utc).isoformat()},
    ).status_code == 422
    assert client.post(
        "/meetings",
        headers=auth,
        json={"title": too_long_title, "starts_at": datetime.now(timezone.utc).isoformat()},
    ).status_code == 422
    assert client.post(
        "/meetings",
        headers=auth,
        json={"title": "边界会议", "agenda": too_long_agenda, "starts_at": datetime.now(timezone.utc).isoformat()},
    ).status_code == 422


def test_upload_type_path_and_duplicate_boundaries(client: TestClient, auth: dict[str, str]):
    meeting_id = create_meeting(client, auth, title="资料边界测试")
    unsupported = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("payload.exe", b"not allowed", "application/octet-stream")},
    )
    assert unsupported.status_code == 415
    mismatch = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("meeting.txt", b"text", "application/pdf")},
    )
    assert mismatch.status_code == 415

    first = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("../../unsafe.txt", "[00:01] 林澄：同一资料。".encode("utf-8"), "text/plain")},
    )
    second = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("renamed.txt", "[00:01] 林澄：同一资料。".encode("utf-8"), "text/plain")},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["file_name"] == "unsafe.txt"
    detail = client.get(f"/meetings/{meeting_id}", headers=auth).json()
    assert len(detail["assets"]) == 1


def test_transcription_requires_asset_and_is_idempotent(client: TestClient, auth: dict[str, str]):
    meeting_id = create_meeting(client, auth, title="任务幂等测试")
    missing = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    assert missing.status_code == 422
    upload_text(client, auth, meeting_id)
    first = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    second = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]

    with SessionLocal() as db:
        job = db.get(Job, first.json()["id"])
        assert job is not None
        job.status = "failed"
        job.attempt = 3
        db.commit()
    exhausted = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    assert exhausted.status_code == 409


def test_signed_asset_is_expiring_and_signature_bound(client: TestClient, auth: dict[str, str]):
    meeting_id = create_meeting(client, auth, title="资源签名测试")
    asset_id = upload_text(client, auth, meeting_id)
    expires = int(__import__("time").time()) + 60
    valid = sign_asset(asset_id, expires)
    assert client.get(f"/assets/public/{asset_id}?expires={expires}&sig={valid}").status_code == 200
    assert client.get(f"/assets/public/{asset_id}?expires={expires}&sig=bad").status_code == 403
    expired = int(__import__("time").time()) - 1
    assert client.get(f"/assets/public/{asset_id}?expires={expired}&sig={sign_asset(asset_id, expired)}").status_code == 403
    assert client.get(f"/assets/public/999999?expires={expires}&sig={sign_asset(999999, expires)}").status_code == 404


def test_review_state_machine_fails_closed_and_is_single_decision(client: TestClient, auth: dict[str, str]):
    meeting_id, run_id = prepare_review(client, auth, process_review=False)
    before_worker = client.post(f"/review-runs/{run_id}/approve", headers=auth, json={"reason": "过早批准"})
    assert before_worker.status_code == 409
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.run_id == run_id))
        assert job is not None
        job_id = job.id
    process(job_id)
    waiting = client.get(f"/review-runs/{run_id}", headers=auth)
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting_human"
    approved = client.post(f"/review-runs/{run_id}/approve", headers=auth, json={"reason": "已核对证据"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    repeated = client.post(f"/review-runs/{run_id}/approve", headers=auth, json={"reason": "重复批准"})
    assert repeated.status_code == 409
    versions = client.get(f"/meetings/{meeting_id}/minutes", headers=auth).json()["versions"]
    assert any(item["status"] == "approved" for item in versions)


def test_invalid_and_disabled_tokens_are_rejected(client: TestClient, auth: dict[str, str]):
    assert client.get("/auth/me", headers={"Authorization": "Bearer malformed"}).status_code == 401
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "demo"))
        assert user is not None
        user.enabled = False
        db.commit()
    assert client.get("/auth/me", headers=auth).status_code == 401


def test_admin_mutations_validate_contract_and_duplicates(client: TestClient, auth: dict[str, str]):
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "demo123456"})
    assert admin_login.status_code == 200
    admin = {"Authorization": f"Bearer {admin_login.json()['token']}"}
    missing_variable = client.post(
        "/admin/prompts",
        headers=admin,
        json={"purpose": "minutes_generation", "name": "不完整模板", "template": "只输出会议", "variables": ["transcript"]},
    )
    assert missing_variable.status_code == 422
    valid_prompt = client.post(
        "/admin/prompts",
        headers=admin,
        json={"purpose": "minutes_generation", "name": "完整模板", "template": "只输出 {{transcript}}", "variables": ["transcript"]},
    )
    assert valid_prompt.status_code == 201

    department = client.post("/admin/departments", headers=admin, json={"name": "边界部门", "code": "boundary"})
    assert department.status_code == 201
    duplicate = client.post("/admin/departments", headers=admin, json={"name": "边界部门", "code": "boundary-2"})
    assert duplicate.status_code == 409
    employee = client.post(
        "/admin/employees",
        headers=admin,
        json={"username": "boundary-user", "display_name": "边界员工", "password": "boundary-pass-123"},
    )
    assert employee.status_code == 201
    duplicate_employee = client.post(
        "/admin/employees",
        headers=admin,
        json={"username": "boundary-user", "display_name": "重复员工", "password": "boundary-pass-123"},
    )
    assert duplicate_employee.status_code == 409
    assert client.get("/admin/observability", headers=auth).status_code == 403


def test_agent_evidence_rules_clear_untrusted_references():
    minutes = {
        "summary": "有摘要",
        "topics": [{"title": "议题", "evidence_segment_ids": [7]}],
        "decisions": [{"text": "结论", "evidence_segment_ids": [999]}],
        "action_items": [{"text": "跟进", "owner": "", "due": "", "evidence_segment_ids": [999]}],
        "open_questions": [],
        "risks": [],
    }
    issues = rule_issues(minutes, {7})
    assert any(issue["field"] == "decisions" and issue["severity"] == "high" for issue in issues)
    revised = safe_revision(minutes, {7})
    assert revised["decisions"][0]["evidence_segment_ids"] == []
    assert revised["action_items"][0]["owner"] == "待确认"
    assert revised["action_items"][0]["due"] == "待确认"


def test_worker_parser_handles_chinese_colons_and_ignores_unparseable_lines(tmp_path: Path):
    from app.worker import parse_text_transcript

    path = tmp_path / "transcript.txt"
    path.write_text("标题行\n[01:02] 林澄：确认发布\n[00:03:04] 周岚: 完成检查\n没有标记的页眉\n", encoding="utf-8")
    segments = parse_text_transcript(path)
    assert len(segments) == 2
    assert segments[0]["start_ms"] == 62_000
    assert segments[1]["start_ms"] == 3 * 60_000 + 4_000
    assert [segment["text"] for segment in segments] == ["确认发布", "完成检查"]
