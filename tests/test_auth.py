from collections.abc import Generator
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.database import Base, get_db_session, get_optional_db_session
from app.auth.quota import consume_anonymous_match
from app.auth.models import User
from app.core.config import settings
from app.main import app
from app.schemas.models import JobPosting
from app.workflows.models import RecruiterJob


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    original_secret = settings.AUTH_SECRET_KEY
    original_cookie_secure = settings.AUTH_COOKIE_SECURE
    settings.AUTH_SECRET_KEY = "test-secret-key-with-at-least-32-characters"
    settings.AUTH_COOKIE_SECURE = False
    monkeypatch.setattr("app.main.initialize_database", lambda: None)
    monkeypatch.setattr("app.workflows.routes.remove_cv_from_index", lambda _: None)

    def override_session() -> Generator:
        with test_sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_optional_db_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        settings.AUTH_SECRET_KEY = original_secret
        settings.AUTH_COOKIE_SECURE = original_cookie_secure
        engine.dispose()


def register(client: TestClient, role: str = "candidate", email: str = "person@example.com"):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "Test Person",
            "password": "Long-test-password-2026",
            "role": role,
        },
    )


def test_prometheus_metrics_endpoint(client: TestClient):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "http_requests_total" in response.text


def test_prometheus_ui_access_requires_admin(client: TestClient):
    assert client.get("/admin/prometheus-access").status_code == 401

    assert register(client).status_code == 201
    assert client.get("/admin/prometheus-access").status_code == 403
    assert client.post("/auth/logout").status_code == 204

    create_admin_session(client)
    assert client.get("/admin/prometheus-access").status_code == 204


def test_registration_creates_http_only_session_and_logout_revokes_it(client: TestClient):
    response = register(client)

    assert response.status_code == 201
    assert response.json()["role"] == "candidate"
    assert response.headers["set-cookie"].lower().find("httponly") >= 0
    assert client.get("/auth/me").json()["email"] == "person@example.com"

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_login_is_limited_after_repeated_failed_attempts(client: TestClient):
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": "unknown@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    response = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 429


def test_registration_cannot_grant_admin_and_duplicate_email_is_rejected(client: TestClient):
    admin_attempt = client.post(
        "/auth/register",
        json={
            "email": "admin@example.com",
            "full_name": "Test Admin",
            "password": "Long-test-password-2026",
            "role": "admin",
        },
    )
    assert admin_attempt.status_code == 422

    assert register(client).status_code == 201
    assert register(client).status_code == 409


def test_candidate_cannot_access_recruiter_matching(client: TestClient):
    assert register(client).status_code == 201

    response = client.post(
        "/match/parsed-job",
        json={
            "id": "job-1",
            "title": "Engineer",
            "company": "Example",
            "description": "A role",
        },
    )

    assert response.status_code == 403


def test_anonymous_quota_is_limited_to_three_per_day(client: TestClient):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        for _ in range(3):
            consume_anonymous_match(session, "203.0.113.12")
        with pytest.raises(HTTPException) as error:
            consume_anonymous_match(session, "203.0.113.12")
        assert error.value.status_code == 429
    finally:
        session.close()
        session_generator.close()


def create_admin_session(client: TestClient) -> None:
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    session.add(
        User(
            email="admin@example.com",
            full_name="Test Admin",
            password_hash=PasswordHash.recommended().hash("Long-test-password-2026"),
            role="admin",
        )
    )
    session.commit()
    session_generator.close()
    assert client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Long-test-password-2026"},
    ).status_code == 200


def test_admin_can_list_users_but_cannot_remove_last_admin(client: TestClient):
    create_admin_session(client)

    users_response = client.get("/admin/users")
    assert users_response.status_code == 200
    admin = users_response.json()[0]
    assert admin["role"] == "admin"

    update_response = client.patch(f"/admin/users/{admin['id']}", json={"is_active": False})
    assert update_response.status_code == 409


def test_matching_quality_report_is_admin_only_and_describes_score_weights(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_path = tmp_path / "latest_report.json"
    report_path.write_text(
        json.dumps({"case_count": 5, "metrics": {"mrr": 0.8}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "MATCH_EVALUATION_REPORT", str(report_path))
    assert client.get("/admin/matching-quality").status_code == 401
    create_admin_session(client)

    response = client.get("/admin/matching-quality")

    assert response.status_code == 200
    assert response.json()["pipeline_version"] == "hybrid-v1"
    assert response.json()["llm_used_for_score"] is False
    assert response.json()["latest_evaluation"]["case_count"] == 5
    assert response.json()["score_weights"] == {
        "required_skills_coverage": 0.6,
        "semantic_similarity": 0.25,
        "profile_text_overlap": 0.15,
    }


def test_real_matching_evaluation_requires_consent_annotations_and_keeps_reports_aggregated(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    assert register(client).status_code == 201
    profile_response = client.put(
        "/candidate/profile",
        json={
            "id": "parsed-cv",
            "full_name": "Private Test Candidate",
            "summary": "Python data analysis",
            "skills": ["Python"],
            "experience": ["Confidential employment history"],
            "raw_text": "Private source CV text",
            "searchable": False,
        },
    )
    assert profile_response.status_code == 200
    assert client.get("/admin/matching-evaluation").status_code == 403
    assert client.put(
        "/candidate/evaluation-consent",
        json={"enabled": True},
    ).json()["enabled"] is True
    assert client.post("/auth/logout").status_code == 204
    create_admin_session(client)

    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    admin = session.scalar(select(User).where(User.role == "admin"))
    session.add(
        RecruiterJob(
            id="real-job",
            owner_id=admin.id,
            title="Python Analyst",
            company="Example Co",
            location="Paris",
            description="Analyse datasets and build Python reporting pipelines.",
            required_skills=["Python"],
            keywords=["data"],
            is_published=True,
        )
    )
    session.commit()
    session.close()
    session_generator.close()

    overview = client.get("/admin/matching-evaluation").json()
    assert overview["consented_candidate_count"] == 1
    candidate_ref = overview["candidates"][0]["candidate_ref"]
    profile_payload = client.get(f"/admin/matching-evaluation/{candidate_ref}").json()
    assert profile_payload["profile"]["skills"] == ["Python"]
    assert "Private Test Candidate" not in json.dumps(profile_payload)
    assert "Private source CV text" not in json.dumps(profile_payload)
    assert "Confidential employment history" in json.dumps(profile_payload)

    annotation = client.put(
        "/admin/matching-evaluation/annotations",
        json={
            "candidate_ref": candidate_ref,
            "job_id": "real-job",
            "relevance_grade": 2,
        },
    )
    assert annotation.status_code == 200
    monkeypatch.setattr("app.auth.admin_routes.index_jobs", lambda jobs: None)
    monkeypatch.setattr(
        "app.auth.admin_routes.retrieve_jobs_for_cv",
        lambda cv, jobs, k, *, index: [
            {"job": job, "semantic_similarity": 0.8} for job in jobs
        ],
    )

    evaluation = client.post("/admin/matching-evaluation/run")

    assert evaluation.status_code == 201
    report = evaluation.json()
    assert report["dataset_type"] == "real_annotated"
    assert report["case_count"] == 1
    assert report["pair_count"] == 1
    assert report["metrics"]["mrr"] == 1
    assert "Private Test Candidate" not in json.dumps(report)
    assert "Private source CV text" not in json.dumps(report)
    assert "trop petit" in report["warning"]

    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "Long-test-password-2026"},
    ).status_code == 200
    revoked = client.put(
        "/candidate/evaluation-consent",
        json={"enabled": False},
    )
    assert revoked.status_code == 200
    assert revoked.json()["enabled"] is False
    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Long-test-password-2026"},
    ).status_code == 200
    assert client.get(f"/admin/matching-evaluation/{candidate_ref}").status_code == 404
    assert client.get("/admin/matching-evaluation").json()["history"] == []


def test_candidate_profile_and_application_are_persisted(client: TestClient):
    assert register(client).status_code == 201
    profile = {
        "id": "temporary-cv-id",
        "full_name": "Test Person",
        "summary": "Experienced software developer",
        "skills": ["Python", "PostgreSQL"],
        "experience": ["Built APIs"],
        "raw_text": "CV source text",
        "searchable": True,
    }
    assert client.put("/candidate/profile", json=profile).status_code == 200
    assert client.get("/candidate/profile").json()["searchable"] is True

    job = client.get("/jobs").json()[0]
    application = client.post("/candidate/applications", json={"job_id": job["id"]})
    assert application.status_code == 201
    assert client.get("/candidate/applications").json()[0]["job_title"] == job["title"]
    assert client.post("/candidate/applications", json={"job_id": job["id"]}).status_code == 409


def test_candidate_recommendations_expose_versioned_score_components(client: TestClient, monkeypatch):
    assert register(client).status_code == 201
    assert client.put(
        "/candidate/profile",
        json={
            "id": "parsed-cv",
            "full_name": "Test Person",
            "summary": "Python data analysis",
            "skills": ["Python"],
            "experience": ["Python data analysis"],
            "raw_text": "Python data analysis",
            "searchable": False,
        },
    ).status_code == 200
    job = client.get("/jobs").json()[0]
    job["required_skills"] = ["Python"]
    monkeypatch.setattr(
        "app.workflows.routes.retrieve_jobs_for_cv",
        lambda cv, jobs, k: [{
            "job": JobPosting.model_validate(job),
            "semantic_similarity": 0.8,
            "matched_skills": ["Python"],
        }],
    )

    response = client.post("/candidate/recommendations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["score_version"] == "hybrid-v1"
    assert payload["score_weights"]["required_skills_coverage"] == 0.6
    assert payload["matches"][0]["signals"]["semantic_similarity"] == 0.8
    assert payload["matches"][0]["matched_skills"] == ["Python"]


def test_recruiter_publication_is_owner_scoped(client: TestClient):
    assert register(client, "recruiter", "second@example.com").status_code == 201
    created = client.post(
        "/recruiter/jobs",
        json={
            "title": "Backend Engineer",
            "company": "Example Co",
            "location": "Paris",
            "description": "Build and maintain reliable service APIs.",
            "required_skills": ["Python", "PostgreSQL"],
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert job_id not in {job["id"] for job in client.get("/jobs").json()}
    assert client.patch(f"/recruiter/jobs/{job_id}/publication", json={"is_published": True}).status_code == 200
    assert job_id in {job["id"] for job in client.get("/jobs").json()}

    assert register(client, "recruiter").status_code == 201
    assert client.patch(f"/recruiter/jobs/{job_id}/publication", json={"is_published": False}).status_code == 403


def test_application_status_notifies_candidate_and_is_visible_to_job_owner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    assert register(client, "recruiter", "team@example.com").status_code == 201
    created_job = client.post(
        "/recruiter/jobs",
        json={
            "title": "Product Designer",
            "company": "Studio",
            "location": "Lyon",
            "description": "Design accessible product experiences with a cross-functional team.",
            "required_skills": ["Figma", "Research"],
        },
    )
    job_id = created_job.json()["id"]
    assert client.patch(
        f"/recruiter/jobs/{job_id}/publication", json={"is_published": True}
    ).status_code == 200
    assert client.post("/auth/logout").status_code == 204

    assert register(client, "candidate", "applicant@example.com").status_code == 201
    removed_cv_ids = []
    monkeypatch.setattr(
        "app.workflows.routes.remove_cv_from_index",
        removed_cv_ids.append,
    )
    profile_response = client.put(
        "/candidate/profile",
        json={
            "id": "parsed-cv",
            "full_name": "Taylor Candidate",
            "summary": "Product designer",
            "skills": ["Figma", "Research"],
            "experience": ["Product design"],
            "raw_text": "Designer CV",
            "searchable": False,
        },
    )
    assert profile_response.status_code == 200
    assert removed_cv_ids == [profile_response.json()["id"]]
    application = client.post("/candidate/applications", json={"job_id": job_id})
    assert application.status_code == 201
    assert client.post("/auth/logout").status_code == 204

    assert client.post(
        "/auth/login",
        json={"email": "team@example.com", "password": "Long-test-password-2026"},
    ).status_code == 200
    received = client.get(f"/recruiter/jobs/{job_id}/applications").json()
    assert received[0]["candidate_name"] == "Taylor Candidate"
    assert received[0]["candidate_email"] == "applicant@example.com"
    assert client.patch(
        f"/recruiter/applications/{application.json()['id']}",
        json={"status": "interview"},
    ).json()["status"] == "interview"
    assert client.post("/auth/logout").status_code == 204

    assert client.post(
        "/auth/login",
        json={"email": "applicant@example.com", "password": "Long-test-password-2026"},
    ).status_code == 200
    assert client.get("/candidate/applications").json()[0]["status"] == "interview"
    assert "interview" in client.get("/candidate/notifications").json()[0]["message"]