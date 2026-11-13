from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentRun, Job, MinutesVersion, User
from app.worker import process


def test_health_and_auth_boundary(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/dashboard").status_code == 401
    assert client.post("/auth/login", json={"username": "demo", "password": "wrong-password"}).status_code == 401


def test_end_to_end_text_meeting(client: TestClient, auth: dict[str, str]):
    created = client.post(
        "/meetings",
        headers=auth,
        json={
            "title": "API 全链路评审",
            "starts_at": datetime.now(timezone.utc).isoformat(),
            "participants": ["林澄", "周岚"],
            "agenda": "确认发布范围",
        },
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    upload = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("meeting.txt", "[00:01] 林澄：确认首发支持证据跳转。\n[00:20] 周岚：我负责周五前完成移动端检查。", "text/plain")},
    )
    assert upload.status_code == 201

    queued = client.post(f"/meetings/{meeting_id}/transcription", headers=auth)
    assert queued.status_code == 202
    process(queued.json()["id"])
    transcript = client.get(f"/meetings/{meeting_id}/transcript", headers=auth).json()
    assert transcript["total"] == 2
    assert transcript["items"][0]["speaker_name"] == "林澄"
    suggestions = client.post(f"/meetings/{meeting_id}/speaker-suggestions", headers=auth).json()
    assert suggestions["items"][0]["source"] == "fallback"
    assert suggestions["items"][0]["suggested_name"] in {"林澄", "周岚"}

    queued = client.post(f"/meetings/{meeting_id}/minutes/generate", headers=auth)
    assert queued.status_code == 202
    process(queued.json()["id"])
    minutes = client.get(f"/meetings/{meeting_id}/minutes", headers=auth).json()["current"]
    assert minutes["version"] == 1
    assert minutes["content"]["decisions"][0]["evidence_segment_ids"]

    review = client.post(f"/meetings/{meeting_id}/review-runs", headers=auth)
    assert review.status_code == 202
    run_id = review.json()["id"]
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.run_id == run_id))
        job_id = job.id
    process(job_id)
    completed = client.get(f"/review-runs/{run_id}", headers=auth).json()
    assert completed["status"] == "waiting_human"
    assert completed["steps"]

    approved = client.post(f"/review-runs/{run_id}/approve", headers=auth, json={"reason": "测试批准"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    versions = client.get(f"/meetings/{meeting_id}/minutes", headers=auth).json()["versions"]
    assert versions[0]["version"] == 2
    assert versions[0]["status"] == "approved"

    docx = client.get(f"/meetings/{meeting_id}/export?format=docx", headers=auth)
    pdf = client.get(f"/meetings/{meeting_id}/export?format=pdf", headers=auth)
    assert docx.status_code == 200 and docx.content.startswith(b"PK")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_review_can_resume_before_worker_runs(client: TestClient, auth: dict[str, str]):
    created = client.post(
        "/meetings",
        headers=auth,
        json={"title": "恢复测试", "starts_at": datetime.now(timezone.utc).isoformat(), "participants": []},
    )
    meeting_id = created.json()["id"]
    upload = client.post(
        f"/meetings/{meeting_id}/assets",
        headers=auth,
        files={"file": ("meeting.txt", "[00:01] 林澄：确认恢复流程。", "text/plain")},
    )
    process(client.post(f"/meetings/{meeting_id}/transcription", headers=auth).json()["id"])
    process(client.post(f"/meetings/{meeting_id}/minutes/generate", headers=auth).json()["id"])
    run = client.post(f"/meetings/{meeting_id}/review-runs", headers=auth).json()
    cancelled = client.post(f"/review-runs/{run['id']}/cancel", headers=auth, json={"reason": "测试取消"})
    assert cancelled.status_code == 200
    resumed = client.post(f"/review-runs/{run['id']}/resume", headers=auth, json={"reason": "测试恢复"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"


def test_admin_boundary(client: TestClient, auth: dict[str, str]):
    assert client.get("/admin/observability", headers=auth).status_code == 403
    admin = client.post("/auth/login", json={"username": "admin", "password": "demo123456"}).json()
    response = client.get("/admin/observability", headers={"Authorization": f"Bearer {admin['token']}"})
    assert response.status_code == 200
    assert "jobs" in response.json()

    models = client.get("/admin/models", headers={"Authorization": f"Bearer {admin['token']}"})
    assert models.status_code == 200
    assert {item["purpose"] for item in models.json()["items"]} >= {"transcription", "minutes_generation", "speaker_matching"}

    prompt = client.post(
        "/admin/prompts",
        headers={"Authorization": f"Bearer {admin['token']}"},
        json={"purpose": "minutes_generation", "name": "测试版本", "template": "只输出 {{transcript}}", "variables": ["transcript"]},
    )
    assert prompt.status_code == 201
    assert prompt.json()["version"] == 2

    department = client.post(
        "/admin/departments",
        headers={"Authorization": f"Bearer {admin['token']}"},
        json={"name": "测试部门", "code": "qa"},
    )
    assert department.status_code == 201
    employee = client.post(
        "/admin/employees",
        headers={"Authorization": f"Bearer {admin['token']}"},
        json={"username": "qa-user", "display_name": "测试员工", "password": "qa-password-123", "department_id": department.json()["id"]},
    )
    assert employee.status_code == 201


def test_dashboard_stats_do_not_include_other_owners(client: TestClient, auth: dict[str, str]):
    baseline = client.get("/dashboard", headers=auth)
    assert baseline.status_code == 200
    baseline_count = baseline.json()["stats"]["meetings"]
    admin = client.post("/auth/login", json={"username": "admin", "password": "demo123456"}).json()
    admin_auth = {"Authorization": f"Bearer {admin['token']}"}
    created = client.post(
        "/meetings",
        headers=admin_auth,
        json={"title": "管理员隔离统计", "starts_at": datetime.now(timezone.utc).isoformat(), "participants": []},
    )
    assert created.status_code == 201
    dashboard = client.get("/dashboard", headers=auth)
    assert dashboard.status_code == 200
    # Demo data can grow over time; the admin-created meeting must not change the
    # employee's counts or become visible in analytics.
    assert dashboard.json()["stats"]["meetings"] == baseline_count
    assert all(item["id"] != created.json()["id"] for item in dashboard.json()["meetings"])


def test_meeting_object_access_isolation(client: TestClient, auth: dict[str, str]):
    admin = client.post("/auth/login", json={"username": "admin", "password": "demo123456"}).json()
    admin_auth = {"Authorization": f"Bearer {admin['token']}"}
    created = client.post(
        "/meetings",
        headers=admin_auth,
        json={"title": "管理员私有会议", "starts_at": datetime.now(timezone.utc).isoformat(), "participants": []},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    assert client.get(f"/meetings/{meeting_id}", headers=auth).status_code == 404
    assert client.patch(f"/meetings/{meeting_id}", headers=auth, json={"title": "越权修改"}).status_code == 404
    visible_ids = {item["id"] for item in client.get("/meetings", headers=auth).json()["items"]}
    assert meeting_id not in visible_ids
    assert client.get(f"/meetings/{meeting_id}", headers=admin_auth).status_code == 200


def test_review_stream_ticket_is_bound_to_run_and_user(client: TestClient, auth: dict[str, str]):
    created = client.post(
        "/meetings",
        headers=auth,
        json={"title": "SSE ticket 测试", "starts_at": datetime.now(timezone.utc).isoformat(), "participants": []},
    )
    meeting_id = created.json()["id"]
    with SessionLocal() as db:
        owner_id = db.scalar(select(User.id).where(User.username == "demo"))
        version = MinutesVersion(meeting_id=meeting_id, version=1, status="draft", source_digest="test", content_json="{}", created_by=owner_id)
        db.add(version)
        db.flush()
        run = AgentRun(meeting_id=meeting_id, minutes_version_id=version.id, status="waiting_human")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    ticket_response = client.post(f"/review-runs/{run_id}/events-ticket", headers=auth)
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]
    stream = client.get(f"/review-runs/{run_id}/events?ticket={ticket}")
    assert stream.status_code == 200
    assert "waiting_human" in stream.text
    assert client.get(f"/review-runs/{run_id}/events?ticket={ticket}").status_code == 401
