import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.database import get_db_session
from app.auth.models import User
from app.auth.routes import require_roles
from app.auth.schemas import AdminUserResponse, AdminUserUpdate
from app.core.config import settings
from app.evaluation import ranking_metrics
from app.schemas.models import CandidateCV, JobPosting
from app.tools.analyze import SCORING_VERSION, SCORING_WEIGHTS, analyze_jobs_for_cv
from app.tools.retrieve import index_jobs, retrieve_jobs_for_cv
from app.workflows.models import (
    Application,
    CandidateEvaluationConsent,
    CandidateProfile,
    MatchEvaluationAnnotation,
    MatchingEvaluationRun,
    RecruiterJob,
)
from app.auth.models import AnonymousMatchUse


router = APIRouter(prefix="/admin", tags=["admin"])


class MatchEvaluationAnnotationInput(BaseModel):
    candidate_ref: str = Field(min_length=64, max_length=64)
    job_id: str = Field(min_length=1, max_length=36)
    relevance_grade: int = Field(ge=0, le=2)


def _candidate_ref(candidate_id: str) -> str:
    return hmac.new(
        settings.AUTH_SECRET_KEY.encode("utf-8"),
        candidate_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _profile_fingerprint(profile: CandidateProfile) -> str:
    return _fingerprint({
        "summary": profile.summary,
        "skills": profile.skills,
        "experience": profile.experience,
        "raw_text": profile.raw_text,
    })


def _evaluation_job(row: RecruiterJob) -> JobPosting:
    return JobPosting(
        id=row.id,
        title=row.title,
        company=row.company,
        location=row.location,
        description=row.description,
        required_skills=row.required_skills,
        keywords=row.keywords,
    )


def _job_fingerprint(job: JobPosting) -> str:
    return _fingerprint(job.model_dump())


def _eligible_profile(
    session: Session,
    candidate_ref: str,
) -> CandidateProfile:
    profiles = session.scalars(
        select(CandidateProfile)
        .join(
            CandidateEvaluationConsent,
            CandidateEvaluationConsent.candidate_id == CandidateProfile.user_id,
        )
    ).all()
    profile = next(
        (item for item in profiles if hmac.compare_digest(_candidate_ref(item.user_id), candidate_ref)),
        None,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profil autorisé introuvable")
    return profile


def _current_annotations(
    session: Session,
    profile: CandidateProfile,
    jobs: list[JobPosting],
) -> dict[str, int | None]:
    rows = session.scalars(
        select(MatchEvaluationAnnotation).where(
            MatchEvaluationAnnotation.candidate_id == profile.user_id
        )
    ).all()
    by_job_id = {row.id: row for row in jobs}
    annotations = {row.job_id: row for row in rows}
    profile_fingerprint = _profile_fingerprint(profile)
    return {
        job.id: (
            annotations[job.id].relevance_grade
            if job.id in annotations
            and annotations[job.id].cv_fingerprint == profile_fingerprint
            and annotations[job.id].job_fingerprint == _job_fingerprint(job)
            else None
        )
        for job in by_job_id.values()
    }


def _matching_run_reports(session: Session) -> list[dict]:
    runs = session.scalars(
        select(MatchingEvaluationRun).order_by(MatchingEvaluationRun.created_at.desc()).limit(10)
    ).all()
    return [run.report for run in runs]


@router.get("/matching-quality")
def matching_quality(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    dataset_path = Path(settings.MATCH_EVALUATION_DATASET)
    report_path = Path(settings.MATCH_EVALUATION_REPORT)
    report = None
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(
                status_code=500,
                detail="Le rapport d’évaluation configuré est illisible",
            ) from error
    return {
        "pipeline_version": SCORING_VERSION,
        "score_weights": SCORING_WEIGHTS,
        "llm_used_for_score": False,
        "evaluation_dataset_configured": dataset_path.is_file(),
        "latest_evaluation": report,
        "real_evaluation_history": _matching_run_reports(session),
    }


@router.get("/matching-evaluation")
def matching_evaluation_overview(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    profiles = session.scalars(
        select(CandidateProfile)
        .join(
            CandidateEvaluationConsent,
            CandidateEvaluationConsent.candidate_id == CandidateProfile.user_id,
        )
        .order_by(CandidateProfile.updated_at.desc())
    ).all()
    jobs = session.scalars(
        select(RecruiterJob)
        .where(RecruiterJob.is_published.is_(True))
        .order_by(RecruiterJob.created_at.desc())
    ).all()
    evaluation_jobs = [_evaluation_job(job) for job in jobs]
    profile_rows = []
    for profile in profiles:
        annotations = _current_annotations(session, profile, evaluation_jobs)
        completed_count = sum(grade is not None for grade in annotations.values())
        profile_rows.append({
            "candidate_ref": _candidate_ref(profile.user_id),
            "skills_count": len(profile.skills),
            "annotated_job_count": completed_count,
            "published_job_count": len(evaluation_jobs),
            "complete": bool(evaluation_jobs) and completed_count == len(evaluation_jobs),
        })
    return {
        "consented_candidate_count": len(profiles),
        "published_job_count": len(evaluation_jobs),
        "annotation_scale": [
            {"value": 0, "label": "Non pertinent"},
            {"value": 1, "label": "Pertinent"},
            {"value": 2, "label": "Très pertinent"},
        ],
        "candidates": profile_rows,
        "history": _matching_run_reports(session),
        "notice": (
            "Seuls les profils avec consentement dédié sont inclus. Les CV sont présentés sans nom "
            "ni texte source. Les annotations sont associées en base à un identifiant interne "
            "pseudonymisé; les rapports enregistrés ne contiennent que des résultats agrégés. "
            "Les jugements portent sur toutes les offres publiées afin de ne pas traiter les paires "
            "non annotées comme des résultats négatifs."
        ),
    }


@router.get("/matching-evaluation/{candidate_ref}")
def matching_evaluation_candidate(
    candidate_ref: str,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    profile = _eligible_profile(session, candidate_ref)
    jobs = session.scalars(
        select(RecruiterJob)
        .where(RecruiterJob.is_published.is_(True))
        .order_by(RecruiterJob.created_at.desc())
    ).all()
    evaluation_jobs = [_evaluation_job(job) for job in jobs]
    annotations = _current_annotations(session, profile, evaluation_jobs)
    return {
        "candidate_ref": candidate_ref,
        "profile": {
            "summary": profile.summary,
            "skills": profile.skills,
            "experience": profile.experience,
        },
        "jobs": [
            {
                **job.model_dump(),
                "relevance_grade": annotations[job.id],
            }
            for job in evaluation_jobs
        ],
    }


@router.put("/matching-evaluation/annotations")
def save_matching_evaluation_annotation(
    payload: MatchEvaluationAnnotationInput,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    profile = _eligible_profile(session, payload.candidate_ref)
    job_row = session.get(RecruiterJob, payload.job_id)
    if job_row is None or not job_row.is_published:
        raise HTTPException(status_code=404, detail="Offre publiée introuvable")
    job = _evaluation_job(job_row)
    annotation = session.scalar(
        select(MatchEvaluationAnnotation).where(
            MatchEvaluationAnnotation.candidate_id == profile.user_id,
            MatchEvaluationAnnotation.job_id == job.id,
        )
    )
    if annotation is None:
        annotation = MatchEvaluationAnnotation(
            id=str(uuid4()),
            candidate_id=profile.user_id,
            job_id=job.id,
        )
        session.add(annotation)
    annotation.relevance_grade = payload.relevance_grade
    annotation.cv_fingerprint = _profile_fingerprint(profile)
    annotation.job_fingerprint = _job_fingerprint(job)
    annotation.labeler_id = admin.id
    annotation.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"saved": True, "relevance_grade": annotation.relevance_grade}


@router.post("/matching-evaluation/run", status_code=201)
def run_real_matching_evaluation(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    profiles = session.scalars(
        select(CandidateProfile)
        .join(
            CandidateEvaluationConsent,
            CandidateEvaluationConsent.candidate_id == CandidateProfile.user_id,
        )
    ).all()
    job_rows = session.scalars(
        select(RecruiterJob)
        .where(RecruiterJob.is_published.is_(True))
        .order_by(RecruiterJob.id)
    ).all()
    jobs = [_evaluation_job(row) for row in job_rows]
    if not jobs:
        raise HTTPException(
            status_code=409,
            detail="Publiez au moins une offre recruteur avant de lancer l’évaluation",
        )

    profile_ids = [profile.user_id for profile in profiles]
    annotations = session.scalars(
        select(MatchEvaluationAnnotation).where(
            MatchEvaluationAnnotation.candidate_id.in_(profile_ids)
        )
    ).all() if profile_ids else []
    annotations_by_profile: dict[str, dict[str, MatchEvaluationAnnotation]] = {}
    for annotation in annotations:
        annotations_by_profile.setdefault(annotation.candidate_id, {})[annotation.job_id] = annotation

    complete_profiles = []
    for profile in profiles:
        current = annotations_by_profile.get(profile.user_id, {})
        profile_fingerprint = _profile_fingerprint(profile)
        if all(
            job.id in current
            and current[job.id].cv_fingerprint == profile_fingerprint
            and current[job.id].job_fingerprint == _job_fingerprint(job)
            for job in jobs
        ):
            complete_profiles.append((profile, current))
    if not complete_profiles:
        raise HTTPException(
            status_code=409,
            detail="Aucun CV consentant n’a des annotations à jour pour toutes les offres publiées",
        )

    index_jobs(jobs)
    rankings: dict[str, list[str]] = {}
    relevance: dict[str, dict[str, int]] = {}
    no_positive_labels = 0
    for profile, current in complete_profiles:
        cv = CandidateCV(
            id=profile.user_id,
            full_name=profile.full_name,
            summary=profile.summary,
            skills=profile.skills,
            experience=profile.experience,
            raw_text=profile.raw_text,
        )
        retrieved = retrieve_jobs_for_cv(cv, jobs, k=len(jobs), index=False)
        analyses = analyze_jobs_for_cv(
            cv,
            [match["job"] for match in retrieved],
            {
                match["job"].id: {"semantic_similarity": match["semantic_similarity"]}
                for match in retrieved
            },
        )
        candidate_ranking = [
            match["job"].id
            for match, _ in sorted(
                zip(retrieved, analyses),
                key=lambda item: (-item[1].score, item[0]["job"].id),
            )
        ]
        grades = {job.id: current[job.id].relevance_grade for job in jobs}
        if not any(grade > 0 for grade in grades.values()):
            no_positive_labels += 1
            continue
        rankings[profile.user_id] = candidate_ranking
        relevance[profile.user_id] = grades

    if not relevance:
        raise HTTPException(
            status_code=409,
            detail="Les annotations complètes ne contiennent aucun match jugé pertinent",
        )

    metrics: dict[str, float] = {}
    for k in (1, 3, 5):
        metrics.update(ranking_metrics(rankings, relevance, k))
    report = {
        "pipeline_version": SCORING_VERSION,
        "dataset_type": "real_annotated",
        "label_source": "Jugements de pertinence saisis par un administrateur",
        "case_count": len(relevance),
        "fully_annotated_candidate_count": len(complete_profiles),
        "excluded_without_positive_labels": no_positive_labels,
        "job_count": len(jobs),
        "pair_count": len(relevance) * len(jobs),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "warning": (
            "Résultats agrégés sur des profils ayant consenti et des annotations complètes. "
            "Les métriques dépendent de la qualité des jugements et ne prédisent pas une embauche."
            + (
                " L’échantillon est trop petit pour tirer des conclusions fiables."
                if len(relevance) < 30
                else ""
            )
        ),
    }
    session.add(MatchingEvaluationRun(report=report))
    session.commit()
    return report


@router.get("/overview")
def admin_overview(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    return {
        "users_total": session.scalar(select(func.count()).select_from(User)) or 0,
        "published_jobs": session.scalar(
            select(func.count()).select_from(RecruiterJob).where(RecruiterJob.is_published.is_(True))
        ) or 0,
        "applications_total": session.scalar(select(func.count()).select_from(Application)) or 0,
        "anonymous_matches_today": session.scalar(
            select(func.coalesce(func.sum(AnonymousMatchUse.request_count), 0)).where(
                AnonymousMatchUse.usage_date == date.today()
            )
        ) or 0,
        "ai_provider": settings.LLM_PROVIDER,
        "ai_configuration_editable": False,
        "bias_monitoring_available": False,
        "retraining_available": False,
    }


@router.get("/prometheus-access", include_in_schema=False, status_code=204)
def authorize_prometheus_access(
    admin: User = Depends(require_roles("admin")),
) -> Response:
    return Response(status_code=204)


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
) -> list[AdminUserResponse]:
    users = session.scalars(select(User).order_by(User.created_at.desc())).all()
    return [
        AdminUserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )
        for user in users
    ]


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
) -> AdminUserResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    removes_admin_access = user.role == "admin" and (
        payload.role not in (None, "admin") or payload.is_active is False
    )
    if removes_admin_access:
        active_admins = session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
        )
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="Le dernier administrateur actif doit être conservé")
    if user.id == admin.id and (payload.role not in (None, "admin") or payload.is_active is False):
        raise HTTPException(status_code=409, detail="Vous ne pouvez pas retirer vos propres droits admin")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if not user.is_active or user.role != "admin":
        user.session_version += 1
    session.commit()
    session.refresh(user)
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )