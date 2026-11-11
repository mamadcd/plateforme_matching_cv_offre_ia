from __future__ import annotations

from typing import Iterable, List

from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma

from app.core.config import settings
from app.core.embeddings import get_embeddings
from app.schemas.models import CandidateCV, JobPosting


def _skill_overlap(cv: CandidateCV, job: JobPosting) -> List[str]:
    cv_skills = {s.lower() for s in cv.skills}
    job_skills = {s.lower() for s in job.required_skills}
    return sorted(cv_skills & job_skills)


def _cv_text(cv: CandidateCV) -> str:
    return "\n".join([
        f"Résumé : {cv.summary}",
        f"Compétences : {', '.join(cv.skills)}",
        f"Expérience : {'; '.join(cv.experience)}",
        f"Texte original : {cv.raw_text}",
    ])


def _job_text(job: JobPosting) -> str:
    return "\n".join([
        f"Titre : {job.title}",
        f"Entreprise : {job.company}",
        f"Localisation : {job.location}",
        f"Description : {job.description}",
        f"Compétences requises : {', '.join(job.required_skills)}",
        f"Mots-clés : {', '.join(job.keywords)}",
    ])


embeddings = get_embeddings()
vectorstore = Chroma(
    persist_directory=settings.CHROMA_PERSIST_DIR,
    embedding_function=embeddings,
    collection_name="jobs",
)
cvs_vectorstore = Chroma(
    persist_directory=settings.CHROMA_PERSIST_DIR,
    embedding_function=embeddings,
    collection_name="cvs",
)


def index_jobs(jobs: Iterable[JobPosting]) -> None:
    """Create or refresh the Chroma documents representing the job postings."""
    job_list = list(jobs)
    if not job_list:
        return

    ids = [job.id for job in job_list]
    vectorstore.delete(ids=ids)
    vectorstore.add_texts(
        texts=[_job_text(job) for job in job_list],
        metadatas=[
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
            }
            for job in job_list
        ],
        ids=ids,
    )


def retrieve_jobs_for_cv(cv: CandidateCV, jobs: Iterable[JobPosting], k: int = 3) -> List[dict]:
    """Return the jobs closest to the CV in the BGE-M3 embedding space."""
    job_list = list(jobs)
    if not job_list:
        return []

    index_jobs(job_list)
    jobs_by_id = {job.id: job for job in job_list}
    matches = vectorstore.similarity_search_with_score(_cv_text(cv), k=min(k, len(job_list)))

    results = []
    for document, distance in matches:
        job = jobs_by_id.get(document.metadata.get("id"))
        if job is None:
            continue
        results.append({
            "job": job,
            "score": round(max(0.0, 1.0 - float(distance)), 4),
            "matched_skills": _skill_overlap(cv, job),
        })
    return results


def index_cvs(cvs: Iterable[CandidateCV]) -> None:
    """Create or refresh the Chroma documents representing candidate CVs."""
    cv_list = list(cvs)
    if not cv_list:
        return

    ids = [cv.id for cv in cv_list]
    cvs_vectorstore.delete(ids=ids)
    cvs_vectorstore.add_texts(
        texts=[_cv_text(cv) for cv in cv_list],
        metadatas=[{"id": cv.id, "full_name": cv.full_name} for cv in cv_list],
        ids=ids,
    )


def retrieve_cvs_for_job(job: JobPosting, cvs: Iterable[CandidateCV], k: int = 3) -> List[dict]:
    """Return the candidates closest to a job in the BGE-M3 embedding space."""
    cv_list = list(cvs)
    if not cv_list:
        return []

    index_cvs(cv_list)
    cvs_by_id = {cv.id: cv for cv in cv_list}
    matches = cvs_vectorstore.similarity_search_with_score(_job_text(job), k=min(k, len(cv_list)))

    results = []
    for document, distance in matches:
        cv = cvs_by_id.get(document.metadata.get("id"))
        if cv is None:
            continue
        matched_skills = sorted({skill.lower() for skill in cv.skills} & {
            skill.lower() for skill in job.required_skills
        })
        results.append({
            "cv": cv,
            "score": round(max(0.0, 1.0 - float(distance)), 4),
            "matched_skills": matched_skills,
        })
    return results


@tool
def retrieve_jobs_for_cv_tool(cv_text: str, k: int = 5) -> str:
    """Récupère les offres d'emploi les plus pertinentes par rapport à un CV."""
    docs = vectorstore.similarity_search(cv_text, k=k)
    if not docs:
        return "Aucune offre trouvée."

    results = []
    for i, doc in enumerate(docs, 1):
        results.append(
            f"=== Offre {i} ===\n"
            f"ID: {doc.metadata.get('id', 'N/A')}\n"
            f"Titre: {doc.metadata.get('title', 'N/A')}\n"
            f"Contenu: {doc.page_content}\n"
        )
    return "\n\n".join(results)
