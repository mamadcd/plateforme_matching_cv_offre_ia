from __future__ import annotations

from threading import RLock
from typing import Iterable, List, Literal

from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma

from app.core.config import settings
from app.core.embeddings import get_embeddings
from app.core.skills import canonicalize_skill, token_overlap
from app.schemas.models import CandidateCV, JobPosting


def _skill_overlap(cv: CandidateCV, job: JobPosting) -> List[str]:
    cv_skills = {canonicalize_skill(skill).casefold() for skill in cv.skills}
    job_skills = {
        canonicalize_skill(skill).casefold(): canonicalize_skill(skill)
        for skill in job.required_skills
    }
    return sorted(
        (job_skills[key] for key in cv_skills & job_skills.keys()),
        key=str.casefold,
    )


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


def _cv_rank_text(cv: CandidateCV) -> str:
    return "\n".join([cv.summary, *cv.skills, *cv.experience])


def _job_rank_text(job: JobPosting) -> str:
    return "\n".join([job.title, job.description, *job.required_skills, *job.keywords])


def _normalized_l2_similarity(distance: float) -> float:
    return round(max(0.0, min(1.0, 1.0 - float(distance) / 2.0)), 4)


def _hybrid_rank(
    semantic_scores: dict[str, float],
    lexical_scores: dict[str, float],
    skill_scores: dict[str, float],
) -> dict[str, float]:
    def ranks(scores: dict[str, float]) -> dict[str, int]:
        ordered = sorted(scores, key=lambda item: (-scores[item], item))
        return {item: rank for rank, item in enumerate(ordered, 1)}

    semantic_ranks = ranks(semantic_scores)
    lexical_ranks = ranks(lexical_scores)
    skill_ranks = ranks(skill_scores)
    return {
        item: round(
            (
                0.55 / (60 + semantic_ranks[item])
                + 0.30 / (60 + lexical_ranks[item])
                + 0.15 / (60 + skill_ranks[item])
            )
            / (1 / 61),
            4,
        )
        for item in semantic_scores
    }


_jobs_vectorstore: Chroma | None = None
_cvs_vectorstore: Chroma | None = None
_cv_index_lock = RLock()


def _get_vectorstore(collection_name: Literal["jobs", "cvs"]) -> Chroma:
    global _jobs_vectorstore, _cvs_vectorstore
    if collection_name == "jobs":
        if _jobs_vectorstore is None:
            _jobs_vectorstore = Chroma(
                persist_directory=settings.CHROMA_PERSIST_DIR,
                embedding_function=get_embeddings(),
                collection_name=collection_name,
            )
        return _jobs_vectorstore
    if _cvs_vectorstore is None:
        _cvs_vectorstore = Chroma(
            persist_directory=settings.CHROMA_PERSIST_DIR,
            embedding_function=get_embeddings(),
            collection_name=collection_name,
        )
    return _cvs_vectorstore


def index_jobs(jobs: Iterable[JobPosting]) -> None:
    """Create or refresh the Chroma documents representing the job postings."""
    job_list = list(jobs)
    if not job_list:
        return

    ids = [job.id for job in job_list]
    vectorstore = _get_vectorstore("jobs")
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


def retrieve_jobs_for_cv(
    cv: CandidateCV,
    jobs: Iterable[JobPosting],
    k: int = 3,
    *,
    index: bool = True,
) -> List[dict]:
    """Rank jobs with reciprocal-rank fusion of semantic, lexical and skill retrieval."""
    job_list = list(jobs)
    if not job_list:
        return []

    if index:
        index_jobs(job_list)
    jobs_by_id = {job.id: job for job in job_list}
    vectorstore = _get_vectorstore("jobs")
    semantic_matches = vectorstore.similarity_search_with_score(
        _cv_text(cv), k=max(len(job_list), vectorstore._collection.count())
    )
    semantic_scores = {
        document.metadata["id"]: _normalized_l2_similarity(distance)
        for document, distance in semantic_matches
        if document.metadata.get("id") in jobs_by_id
    }
    lexical_scores = {
        job.id: token_overlap(_cv_rank_text(cv), _job_rank_text(job))
        for job in job_list
    }
    skill_scores = {
        job.id: len(_skill_overlap(cv, job)) / max(1, len(job.required_skills))
        for job in job_list
    }
    fused_scores = _hybrid_rank(semantic_scores, lexical_scores, skill_scores)

    results = []
    for job_id in sorted(fused_scores, key=lambda item: (-fused_scores[item], item))[:k]:
        results.append({
            "job": jobs_by_id[job_id],
            "score": round(fused_scores[job_id], 6),
            "semantic_similarity": semantic_scores[job_id],
            "lexical_similarity": round(lexical_scores[job_id], 4),
            "matched_skills": _skill_overlap(cv, jobs_by_id[job_id]),
        })
    return results


def index_cvs(cvs: Iterable[CandidateCV]) -> None:
    """Index visible CVs and remove records whose visibility has been revoked."""
    cv_list = list(cvs)
    ids = [cv.id for cv in cv_list]
    with _cv_index_lock:
        retained_ids = set(ids)
        vectorstore = _cvs_vectorstore or Chroma(
            persist_directory=settings.CHROMA_PERSIST_DIR,
            collection_name="cvs",
        )
        existing_ids = vectorstore._collection.get(include=[])["ids"]
        stale_ids = [cv_id for cv_id in existing_ids if cv_id not in retained_ids]
        if stale_ids:
            vectorstore.delete(ids=stale_ids)
        if not cv_list:
            return

        vectorstore = _get_vectorstore("cvs")
        vectorstore.delete(ids=ids)
        vectorstore.add_texts(
            texts=[_cv_text(cv) for cv in cv_list],
            metadatas=[{"id": cv.id, "full_name": cv.full_name} for cv in cv_list],
            ids=ids,
        )


def remove_cv_from_index(cv_id: str) -> None:
    """Remove a candidate record immediately after their search consent is revoked."""
    with _cv_index_lock:
        vectorstore = _cvs_vectorstore or Chroma(
            persist_directory=settings.CHROMA_PERSIST_DIR,
            collection_name="cvs",
        )
        vectorstore.delete(ids=[cv_id])


def retrieve_cvs_for_job(job: JobPosting, cvs: Iterable[CandidateCV], k: int = 3) -> List[dict]:
    """Rank visible candidate CVs with hybrid semantic, lexical and skill retrieval."""
    cv_list = list(cvs)
    index_cvs(cv_list)
    if not cv_list:
        return []

    cvs_by_id = {cv.id: cv for cv in cv_list}
    semantic_matches = _get_vectorstore("cvs").similarity_search_with_score(
        _job_text(job), k=len(cv_list)
    )
    semantic_scores = {
        document.metadata["id"]: _normalized_l2_similarity(distance)
        for document, distance in semantic_matches
        if document.metadata.get("id") in cvs_by_id
    }
    lexical_scores = {
        cv.id: token_overlap(_job_rank_text(job), _cv_rank_text(cv))
        for cv in cv_list
    }
    skill_scores = {
        cv.id: len(_skill_overlap(cv, job)) / max(1, len(job.required_skills))
        for cv in cv_list
    }
    fused_scores = _hybrid_rank(semantic_scores, lexical_scores, skill_scores)

    results = []
    for cv_id in sorted(fused_scores, key=lambda item: (-fused_scores[item], item))[:k]:
        cv = cvs_by_id[cv_id]
        results.append({
            "cv": cv,
            "score": round(fused_scores[cv_id], 6),
            "semantic_similarity": semantic_scores[cv_id],
            "lexical_similarity": round(lexical_scores[cv_id], 4),
            "matched_skills": _skill_overlap(cv, job),
        })
    return results


@tool
def retrieve_jobs_for_cv_tool(cv_text: str, k: int = 5) -> str:
    """Récupère les offres d'emploi les plus pertinentes par rapport à un CV."""
    docs = _get_vectorstore("jobs").similarity_search(cv_text, k=k)
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
