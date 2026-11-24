from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.database import Base, get_db_session, get_optional_db_session
from app.core.config import settings
from app.main import app
from app.schemas.models import CandidateCV, JobPosting, MatchAnalysis, MatchSignals


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
    settings.AUTH_SECRET_KEY = "integration-secret-key-with-at-least-32-characters"
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


def register(client: TestClient, role: str, email: str) -> TestClient:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "Integration Person",
            "password": "Long-test-password-2026",
            "role": role,
        },
    )
    assert response.status_code == 201
    return client


def test_health_public_jobs_and_metrics(client: TestClient):
    assert client.get("/health").json() == {"status": "ok", "phase": "1 - Prototype"}

    jobs = client.get("/jobs")
    assert jobs.status_code == 200
    assert jobs.json()

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


def test_ingestion_endpoints_validate_files_and_return_parsed_contract(client: TestClient, monkeypatch):
    cv = CandidateCV(
        id="cv-integration",
        full_name="Alice Integration",
        summary="Python and SQL engineer",
        skills=["Python", "SQL"],
        experience=["Built APIs"],
        extracted_text="Full extracted CV text",
    )
    monkeypatch.setattr("app.main.parse_document", lambda content, filename, kind: cv)

    response = client.post(
        "/ingest/cv",
        files={"file": ("alice.txt", b"Alice Integration\nPython SQL", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "cv-integration"
    assert response.json()["skills"] == ["Python", "SQL"]
    assert response.json()["extracted_text"] == "Full extracted CV text"

    oversized = b"x" * (settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1)
    assert client.post(
        "/ingest/cv",
        files={"file": ("large.txt", oversized, "text/plain")},
    ).status_code == 413


def test_candidate_profile_recommendations_application_and_notification(client: TestClient, monkeypatch):
    register(client, "recruiter", "recruiter.integration@example.com")
    created = client.post(
        "/recruiter/jobs",
        json={
            "title": "Python Engineer",
            "company": "Integration Co",
            "location": "Paris",
            "description": "Build APIs and maintain Python data services.",
            "required_skills": ["Python", "SQL"],
        },
    )
    job_id = created.json()["id"]
    assert client.patch(
        f"/recruiter/jobs/{job_id}/publication",
        json={"is_published": True},
    ).status_code == 200
    assert client.post("/auth/logout").status_code == 204

    register(client, "candidate", "candidate.integration@example.com")
    profile = client.put(
        "/candidate/profile",
        json={
            "id": "ignored",
            "full_name": "Candidate Integration",
            "summary": "Python SQL engineer",
            "skills": ["Python", "SQL"],
            "experience": ["API development"],
            "raw_text": "Python SQL API development",
            "searchable": True,
        },
    )
    assert profile.status_code == 200
    candidate_id = profile.json()["id"]

    published_job = client.get("/jobs").json()
    target = next(job for job in published_job if job["id"] == job_id)
    target_job = JobPosting.model_validate(target)
    cv = CandidateCV.model_validate(profile.json())
    monkeypatch.setattr(
        "app.workflows.routes.retrieve_jobs_for_cv",
        lambda cv, jobs, k: [{"job": target_job, "semantic_similarity": 0.9}],
    )
    monkeypatch.setattr(
        "app.workflows.routes.analyze_jobs_for_cv",
        lambda cv, jobs, similarities: [
            MatchAnalysis(
                score=88,
                summary="Strong Python and SQL match",
                strengths=["Python", "SQL"],
                gaps=[],
                matched_skills=["Python", "SQL"],
                signals=MatchSignals(required_skills_coverage=1.0, semantic_similarity=0.9),
            )
        ],
    )

    recommendations = client.post("/candidate/recommendations")
    assert recommendations.status_code == 200
    assert recommendations.json()["matches"][0]["job_id"] == job_id
    assert recommendations.json()["matches"][0]["score"] == 88

    application = client.post("/candidate/applications", json={"job_id": job_id})
    assert application.status_code == 201
    assert client.post("/candidate/applications", json={"job_id": job_id}).status_code == 409

    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/login",
        json={
            "email": "recruiter.integration@example.com",
            "password": "Long-test-password-2026",
        },
    ).status_code == 200
    applications = client.get(f"/recruiter/jobs/{job_id}/applications")
    assert applications.status_code == 200
    assert applications.json()[0]["candidate_id"] == candidate_id
    assert client.patch(
        f"/recruiter/applications/{application.json()['id']}",
        json={"status": "interview"},
    ).status_code == 200


def test_anonymous_matching_endpoint_enforces_quota(client: TestClient, monkeypatch):
    cv = CandidateCV(
        id="anonymous-cv",
        full_name="Visitor",
        summary="Python developer",
        skills=["Python"],
        experience=["Built services"],
    )
    job = JobPosting(
        id="anonymous-job",
        title="Python Developer",
        company="Example",
        required_skills=["Python"],
        description="Build Python services",
    )
    monkeypatch.setattr("app.main.load_sample_jobs", lambda: [job])
    monkeypatch.setattr(
        "app.main.retrieve_jobs_for_cv",
        lambda cv, jobs, k: [{"job": job, "semantic_similarity": 0.8}],
    )
    monkeypatch.setattr(
        "app.main.analyze_jobs_for_cv",
        lambda cv, jobs, similarities: [
            MatchAnalysis(
                score=80,
                summary="Good match",
                strengths=["Python"],
                gaps=[],
                matched_skills=["Python"],
                signals=MatchSignals(required_skills_coverage=1.0, semantic_similarity=0.8),
            )
        ],
    )

    payload = cv.model_dump()
    for _ in range(3):
        response = client.post("/match/anonymous", json=payload)
        assert response.status_code == 200
    assert client.post("/match/anonymous", json=payload).status_code == 429
