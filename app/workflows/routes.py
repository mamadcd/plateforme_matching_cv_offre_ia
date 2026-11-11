from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.database import get_db_session, get_optional_db_session
from app.auth.models import User
from app.auth.routes import require_roles
from app.data.load_samples import load_sample_jobs
from app.schemas.models import (
    CVForJobMatchResult,
    CVToJobsMatchResponse,
    CandidateCV,
    JobPosting,
    JobToCVsMatchResponse,
)
from app.tools.analyze import analyze_cvs_for_job, analyze_jobs_for_cv
from app.tools.retrieve import retrieve_cvs_for_job, retrieve_jobs_for_cv
from app.workflows.models import (
    Application,
    CandidateProfile,
    Notification,
    RecruiterJob,
    ShortlistEntry,
)


router = APIRouter(tags=["workflows"])


class CandidateProfileInput(CandidateCV):
    searchable: bool = False


class RecruiterJobInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    company: str = Field(min_length=2, max_length=160)
    location: str = Field(default="", max_length=160)
    description: str = Field(min_length=20, max_length=20_000)
    required_skills: list[str] = Field(default_factory=list, max_length=50)


class JobPublishInput(BaseModel):
    is_published: bool


class ApplicationStatusInput(BaseModel):
    status: Literal["review", "interview", "rejected", "accepted"]


class ApplicationInput(BaseModel):
    job_id: str


def _job_from_row(row: RecruiterJob) -> JobPosting:
    return JobPosting(
        id=row.id,
        title=row.title,
        company=row.company,
        location=row.location,
        description=row.description,
        required_skills=row.required_skills,
        keywords=row.keywords,
    )


def _profile_as_cv(profile: CandidateProfile) -> CandidateCV:
    return CandidateCV(
        id=profile.user_id,
        full_name=profile.full_name,
        summary=profile.summary,
        skills=profile.skills,
        experience=profile.experience,
        raw_text=profile.raw_text,
    )


def _find_owned_job(session: Session, job_id: str, user: User) -> RecruiterJob:
    job = session.get(RecruiterJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    if user.role != "admin" and job.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Cette offre ne vous appartient pas")
    return job


@router.get("/jobs", response_model=list[JobPosting])
def public_jobs(session: Session | None = Depends(get_optional_db_session)) -> list[JobPosting]:
    jobs = load_sample_jobs()
    if session is None:
        return jobs
    published = session.scalars(
        select(RecruiterJob).where(RecruiterJob.is_published.is_(True)).order_by(RecruiterJob.created_at.desc())
    ).all()
    return jobs + [_job_from_row(job) for job in published]


@router.get("/candidate/profile")
def get_candidate_profile(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    profile = session.get(CandidateProfile, user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Aucun CV enregistré")
    return {**_profile_as_cv(profile).model_dump(), "searchable": profile.searchable}


@router.put("/candidate/profile")
def save_candidate_profile(
    payload: CandidateProfileInput,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    profile = session.get(CandidateProfile, user.id)
    if profile is None:
        profile = CandidateProfile(user_id=user.id)
        session.add(profile)
    profile.full_name = payload.full_name
    profile.summary = payload.summary
    profile.skills = payload.skills
    profile.experience = payload.experience
    profile.raw_text = payload.raw_text
    profile.searchable = payload.searchable
    profile.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {**payload.model_dump(), "id": user.id}


@router.post("/candidate/recommendations", response_model=CVToJobsMatchResponse)
def candidate_recommendations(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
) -> CVToJobsMatchResponse:
    profile = session.get(CandidateProfile, user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Enregistrez d'abord votre CV")
    jobs = load_sample_jobs()
    recruiter_jobs = session.scalars(
        select(RecruiterJob).where(RecruiterJob.is_published.is_(True))
    ).all()
    jobs.extend(_job_from_row(job) for job in recruiter_jobs)
    cv = _profile_as_cv(profile)
    matches = retrieve_jobs_for_cv(cv, jobs, k=min(10, len(jobs)))
    analyses = analyze_jobs_for_cv(cv, [match["job"] for match in matches])
    return CVToJobsMatchResponse(
        cv_summary=cv.summary,
        matches=[
            {
                "job_id": match["job"].id,
                "job_title": match["job"].title,
                "score": float(analysis.score),
                "explanation": analysis.summary,
                "strengths": analysis.strengths,
                "gaps": analysis.gaps,
            }
            for match, analysis in zip(matches, analyses)
        ],
    )


@router.post("/candidate/applications", status_code=status.HTTP_201_CREATED)
def apply_to_job(
    payload: ApplicationInput,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    if session.get(CandidateProfile, user.id) is None:
        raise HTTPException(status_code=409, detail="Enregistrez votre CV avant de postuler")
    sample_job = next((job for job in load_sample_jobs() if job.id == payload.job_id), None)
    recruiter_job = session.get(RecruiterJob, payload.job_id)
    if sample_job is None and (recruiter_job is None or not recruiter_job.is_published):
        raise HTTPException(status_code=404, detail="Offre publique introuvable")
    title = sample_job.title if sample_job else recruiter_job.title
    recruiter_id = recruiter_job.owner_id if recruiter_job else None
    application = Application(
        candidate_id=user.id,
        job_id=payload.job_id,
        job_title=title,
        recruiter_id=recruiter_id,
    )
    session.add(application)
    if recruiter_id:
        session.add(Notification(user_id=recruiter_id, message=f"Nouvelle candidature pour {title}"))
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Vous avez déjà postulé à cette offre") from error
    return {"id": application.id, "job_id": application.job_id, "job_title": application.job_title, "status": application.status}


@router.get("/candidate/applications")
def candidate_applications(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    applications = session.scalars(
        select(Application).where(Application.candidate_id == user.id).order_by(Application.created_at.desc())
    ).all()
    return [
        {"id": item.id, "job_id": item.job_id, "job_title": item.job_title, "status": item.status, "created_at": item.created_at}
        for item in applications
    ]


@router.get("/candidate/notifications")
def candidate_notifications(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    notifications = session.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())
    ).all()
    return [
        {"id": item.id, "message": item.message, "is_read": item.is_read, "created_at": item.created_at}
        for item in notifications
    ]


@router.patch("/candidate/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("candidate")),
):
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    notification.is_read = True
    session.commit()


@router.post("/recruiter/jobs", status_code=status.HTTP_201_CREATED)
def create_recruiter_job(
    payload: RecruiterJobInput,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter")),
):
    job = RecruiterJob(
        owner_id=user.id,
        title=payload.title.strip(),
        company=payload.company.strip(),
        location=payload.location.strip(),
        description=payload.description.strip(),
        required_skills=list(dict.fromkeys(skill.strip() for skill in payload.required_skills if skill.strip())),
        keywords=[skill.casefold() for skill in payload.required_skills if skill.strip()],
    )
    session.add(job)
    session.commit()
    return {**_job_from_row(job).model_dump(), "is_published": job.is_published}


@router.get("/recruiter/jobs")
def recruiter_jobs(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    query = select(RecruiterJob).order_by(RecruiterJob.created_at.desc())
    if user.role != "admin":
        query = query.where(RecruiterJob.owner_id == user.id)
    jobs = session.scalars(query).all()
    return [{**_job_from_row(job).model_dump(), "is_published": job.is_published} for job in jobs]


@router.patch("/recruiter/jobs/{job_id}/publication")
def update_job_publication(
    job_id: str,
    payload: JobPublishInput,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    job = _find_owned_job(session, job_id, user)
    job.is_published = payload.is_published
    session.commit()
    return {"id": job.id, "is_published": job.is_published}


@router.get("/recruiter/jobs/{job_id}/candidates")
def recommended_candidates(
    job_id: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    job = _find_owned_job(session, job_id, user)
    profiles = session.scalars(
        select(CandidateProfile).where(CandidateProfile.searchable.is_(True))
    ).all()
    cvs = [_profile_as_cv(profile) for profile in profiles]
    if not cvs:
        return []
    matches = retrieve_cvs_for_job(_job_from_row(job), cvs, k=min(20, len(cvs)))
    analyses = analyze_cvs_for_job(_job_from_row(job), [match["cv"] for match in matches])
    return [
        CVForJobMatchResult(
            cv_id=match["cv"].id,
            cv_name=match["cv"].full_name,
            score=float(analysis.score),
            explanation=analysis.summary,
            strengths=analysis.strengths,
            gaps=analysis.gaps,
            matched_skills=analysis.matched_skills or match["matched_skills"],
        ).model_dump()
        for match, analysis in zip(matches, analyses)
    ]


@router.post("/recruiter/jobs/{job_id}/shortlist/{candidate_id}", status_code=status.HTTP_201_CREATED)
def add_to_shortlist(
    job_id: str,
    candidate_id: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    _find_owned_job(session, job_id, user)
    profile = session.get(CandidateProfile, candidate_id)
    if profile is None or not profile.searchable:
        raise HTTPException(status_code=404, detail="Profil candidat introuvable ou non visible")
    entry = ShortlistEntry(job_id=job_id, recruiter_id=user.id, candidate_id=candidate_id)
    session.add(entry)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Ce profil est déjà dans la shortlist") from error
    return {"id": entry.id, "job_id": job_id, "candidate_id": candidate_id}


@router.get("/recruiter/jobs/{job_id}/shortlist")
def recruiter_shortlist(
    job_id: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    _find_owned_job(session, job_id, user)
    entries = session.scalars(select(ShortlistEntry).where(ShortlistEntry.job_id == job_id)).all()
    result = []
    for entry in entries:
        profile = session.get(CandidateProfile, entry.candidate_id)
        if profile and profile.searchable:
            result.append({"candidate_id": profile.user_id, "full_name": profile.full_name, "summary": profile.summary})
    return result


@router.get("/recruiter/jobs/{job_id}/applications")
def recruiter_applications(
    job_id: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    _find_owned_job(session, job_id, user)
    applications = session.execute(
        select(Application, CandidateProfile.full_name, User.email)
        .join(User, User.id == Application.candidate_id)
        .join(CandidateProfile, CandidateProfile.user_id == Application.candidate_id)
        .where(Application.job_id == job_id)
        .order_by(Application.created_at.desc())
    ).all()
    return [
        {
            "id": application.id,
            "candidate_id": application.candidate_id,
            "candidate_name": full_name,
            "candidate_email": email,
            "job_title": application.job_title,
            "status": application.status,
            "created_at": application.created_at,
        }
        for application, full_name, email in applications
    ]


@router.patch("/recruiter/applications/{application_id}")
def update_application_status(
    application_id: str,
    payload: ApplicationStatusInput,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_roles("recruiter", "admin")),
):
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Candidature introuvable")
    job = session.get(RecruiterJob, application.job_id)
    if job is None or (user.role != "admin" and job.owner_id != user.id):
        raise HTTPException(status_code=403, detail="Cette candidature ne concerne pas vos offres")
    application.status = payload.status
    application.updated_at = datetime.now(timezone.utc)
    session.add(Notification(
        user_id=application.candidate_id,
        message=f"Le statut de votre candidature pour {application.job_title} a changé : {payload.status}",
    ))
    session.commit()
    return {"id": application.id, "status": application.status}