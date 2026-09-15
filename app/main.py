from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.load_samples import load_sample_cvs, load_sample_jobs
from app.schemas.models import CandidateCV, JobMatchingResponse, MatchingResponse
from app.schemas.models import ReverseMatchResult
from app.tools.analyze import generate_llm_cv_match_analyses, generate_llm_match_analyses
from app.tools.retrieve import retrieve_relevant_cvs, retrieve_relevant_jobs


app = FastAPI(title="Matching RAG Prototype - Phase 1")


class MatchRequest(BaseModel):
    cv_text: str


class JobMatchRequest(BaseModel):
    job_id: str | None = None
    job_text: str | None = None


@app.post("/match", response_model=MatchingResponse)
async def match_cv(request: MatchRequest):
    try:
        cv = CandidateCV(
            id="cv-from-request",
            full_name="Candidat",
            summary=request.cv_text,
            raw_text=request.cv_text,
            skills=[token for token in request.cv_text.lower().replace(",", " ").split() if len(token) > 3][:20],
            experience=["Expérience professionnelle signalée dans le profil"],
        )

        jobs = load_sample_jobs()
        retrieved = retrieve_relevant_jobs(cv, jobs, k=3)
        retrieved_jobs = [item["job"] for item in retrieved]
        analyses = generate_llm_match_analyses(cv, retrieved_jobs)

        matches = []
        for item, analysis in zip(retrieved, analyses):
            matches.append({
                "job_id": item["job"].id,
                "job_title": item["job"].title,
                "score": float(analysis.score),
                "explanation": analysis.summary,
                "strengths": analysis.strengths,
                "gaps": analysis.gaps,
            })

        return MatchingResponse(
            cv_summary=request.cv_text,
            matches=matches,
            message="Matching effectué avec succès (Phase 1 Prototype)",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/match/job", response_model=JobMatchingResponse)
async def match_job(request: JobMatchRequest):
    try:
        jobs = load_sample_jobs()
        if request.job_id:
            job = next((item for item in jobs if item.id == request.job_id), None)
            if job is None:
                raise HTTPException(status_code=404, detail="Offre inconnue")
        elif request.job_text:
            job = next(
                (
                    item for item in jobs
                    if item.title.lower() in request.job_text.lower()
                ),
                None,
            )
            if job is None:
                from app.schemas.models import JobPosting
                job = JobPosting(
                    id="job-from-request",
                    title="Offre soumise",
                    company="Entreprise non précisée",
                    description=request.job_text,
                    keywords=request.job_text.split(),
                )
        else:
            raise HTTPException(status_code=400, detail="job_id ou job_text est requis")

        cvs = load_sample_cvs()
        retrieved = retrieve_relevant_cvs(job, cvs, k=3)
        retrieved_cvs = [item["cv"] for item in retrieved]
        analyses = generate_llm_cv_match_analyses(job, retrieved_cvs)

        matches = []
        for item, analysis in zip(retrieved, analyses):
            matches.append(ReverseMatchResult(
                cv_id=item["cv"].id,
                cv_name=item["cv"].full_name,
                score=float(analysis.score),
                explanation=analysis.summary,
                strengths=analysis.strengths,
                gaps=analysis.gaps,
                matched_skills=analysis.matched_skills or item["matched_skills"],
            ))

        return JobMatchingResponse(
            job_summary=f"{job.title} chez {job.company} ({job.location})",
            matches=matches,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "phase": "1 - Prototype"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
