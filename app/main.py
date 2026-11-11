from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.load_samples import load_sample_cvs, load_sample_jobs
from app.schemas.models import CandidateCV, CVForJobMatchResult, CVToJobsMatchResponse, JobPosting, JobToCVsMatchResponse
from app.tools.analyze import analyze_cvs_for_job, analyze_jobs_for_cv
from app.tools.retrieve import retrieve_cvs_for_job, retrieve_jobs_for_cv
from app.core.config import settings
from app.ingestion.parser import parse_document
from app.auth.database import get_db_session, initialize_database
from app.auth.models import User
from app.auth.quota import consume_anonymous_match
from app.auth.routes import get_current_user, require_roles, router as auth_router
from app.auth.admin_routes import router as admin_router
from app.workflows.routes import router as workflow_router

from sqlalchemy.orm import Session


app = FastAPI(title="Matching RAG Prototype - Phase 1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.FRONTEND_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(workflow_router)


@app.on_event("startup")
def startup_database() -> None:
    initialize_database()


class CVToJobsMatchRequest(BaseModel):
    cv_id: str


class JobToCVsMatchRequest(BaseModel):
    job_id: str


async def _read_upload(upload: UploadFile) -> bytes:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant")
    content = await upload.read(settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1)
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux")
    return content


@app.post("/ingest/cv", response_model=CandidateCV)
async def ingest_cv(file: UploadFile = File(...)):
    content = await _read_upload(file)
    try:
        return parse_document(content, file.filename or "upload", "cv")
    except (ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/ingest/job", response_model=JobPosting)
async def ingest_job(file: UploadFile = File(...)):
    content = await _read_upload(file)
    try:
        return parse_document(content, file.filename or "upload", "job")
    except (ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/match/parsed-cv", response_model=CVToJobsMatchResponse)
async def match_parsed_cv(
    cv: CandidateCV,
    user: User = Depends(require_roles("candidate", "admin")),
):
    jobs = load_sample_jobs()
    job_matches = retrieve_jobs_for_cv(cv, jobs, k=3)
    analyses = analyze_jobs_for_cv(cv, [match["job"] for match in job_matches])
    return CVToJobsMatchResponse(
        cv_summary=cv.summary,
        matches=[{
            "job_id": match["job"].id,
            "job_title": match["job"].title,
            "score": float(analysis.score),
            "explanation": analysis.summary,
            "strengths": analysis.strengths,
            "gaps": analysis.gaps,
        } for match, analysis in zip(job_matches, analyses)],
        message="Matching du CV ingéré effectué avec succès",
    )


@app.post("/match/parsed-job", response_model=JobToCVsMatchResponse)
async def match_parsed_job(
    job: JobPosting,
    user: User = Depends(require_roles("recruiter", "admin")),
):
    raise HTTPException(
        status_code=410,
        detail="Ce flux de démonstration est désactivé; publiez l'offre pour rechercher les profils consentants.",
    )


@app.post("/match", response_model=CVToJobsMatchResponse)
async def match_cv_to_jobs(
    request: CVToJobsMatchRequest,
    user: User = Depends(require_roles("candidate", "admin")),
):
    try:
        cvs = load_sample_cvs()
        cv = next((item for item in cvs if item.id == request.cv_id), None)
        if cv is None:
            raise HTTPException(status_code=404, detail="CV inconnu")

        jobs = load_sample_jobs()
        job_matches = retrieve_jobs_for_cv(cv, jobs, k=3)
        retrieved_jobs = [match["job"] for match in job_matches]
        analyses = analyze_jobs_for_cv(cv, retrieved_jobs)

        matches = []
        for job_match, analysis in zip(job_matches, analyses):
            matches.append({
                "job_id": job_match["job"].id,
                "job_title": job_match["job"].title,
                "score": float(analysis.score),
                "explanation": analysis.summary,
                "strengths": analysis.strengths,
                "gaps": analysis.gaps,
            })

        return CVToJobsMatchResponse(
            cv_summary=cv.summary,
            matches=matches,
            message="Matching effectué avec succès (Phase 1 Prototype)",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/match/job", response_model=JobToCVsMatchResponse)
async def match_job_to_cvs(
    request: JobToCVsMatchRequest,
    user: User = Depends(require_roles("recruiter", "admin")),
):
    raise HTTPException(
        status_code=410,
        detail="Ce flux de démonstration est désactivé; utilisez une offre dont vous êtes propriétaire.",
    )


@app.post("/match/anonymous", response_model=CVToJobsMatchResponse, tags=["matching"])
async def match_anonymous_cv(
    cv: CandidateCV,
    request: Request,
    session: Session = Depends(get_db_session),
):
    client_ip = request.client.host if request.client else "unknown"
    consume_anonymous_match(session, client_ip)
    jobs = load_sample_jobs()
    job_matches = retrieve_jobs_for_cv(cv, jobs, k=3)
    analyses = analyze_jobs_for_cv(cv, [match["job"] for match in job_matches])
    return CVToJobsMatchResponse(
        cv_summary=cv.summary,
        matches=[{
            "job_id": match["job"].id,
            "job_title": match["job"].title,
            "score": float(analysis.score),
            "explanation": analysis.summary,
            "strengths": analysis.strengths,
            "gaps": analysis.gaps,
        } for match, analysis in zip(job_matches, analyses)],
        message="Matching visiteur effectué; quota journalier limité à 3 analyses",
    )


@app.get("/health")
def health():
    return {"status": "ok", "phase": "1 - Prototype"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
