from __future__ import annotations

import json

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm import get_llm
from app.core.skills import canonicalize_skill, token_overlap
from app.schemas.models import CandidateCV, JobPosting, MatchAnalysis, MatchSignals


SCORING_VERSION = "hybrid-v1"
SCORING_WEIGHTS = {
    "required_skills_coverage": 0.60,
    "semantic_similarity": 0.25,
    "profile_text_overlap": 0.15,
}


def analyze_cv_job_match(
    cv: CandidateCV,
    job: JobPosting,
    semantic_similarity: float | None = None,
) -> MatchAnalysis:
    """Score explicit, inspectable signals; this score is not a hiring probability."""
    cv_skills = {canonicalize_skill(skill).casefold() for skill in cv.skills}
    required_names = {
        canonicalize_skill(skill).casefold(): canonicalize_skill(skill)
        for skill in job.required_skills
    }
    matched_keys = cv_skills & required_names.keys()
    missing_keys = required_names.keys() - cv_skills
    matched = sorted((required_names[key] for key in matched_keys), key=str.casefold)
    missing = sorted((required_names[key] for key in missing_keys), key=str.casefold)
    skill_coverage = len(matched_keys) / len(required_names) if required_names else None
    experience_text = " ".join([cv.summary, *cv.experience])
    job_text = " ".join([job.title, job.description, *job.required_skills])
    profile_text_overlap = (
        token_overlap(experience_text, job_text) if experience_text.strip() else None
    )
    semantic = (
        max(0.0, min(1.0, semantic_similarity))
        if semantic_similarity is not None
        else None
    )
    signals = MatchSignals(
        required_skills_coverage=skill_coverage,
        semantic_similarity=semantic,
        profile_text_overlap=profile_text_overlap,
    )
    components = [
        (SCORING_WEIGHTS["required_skills_coverage"], skill_coverage),
        (SCORING_WEIGHTS["semantic_similarity"], semantic),
        (SCORING_WEIGHTS["profile_text_overlap"], profile_text_overlap),
    ]
    active_components = [
        (weight, value)
        for weight, value in components
        if value is not None
    ]
    denominator = sum(weight for weight, _ in active_components)
    score = round(
        100 * sum(weight * value for weight, value in active_components) / denominator
    ) if denominator else 0

    strengths = []
    if matched:
        strengths.append(f"Compétences requises détectées : {', '.join(matched)}.")
    if semantic is not None:
        strengths.append(f"Similarité sémantique : {semantic:.0%}.")
    if profile_text_overlap is not None and profile_text_overlap > 0:
        strengths.append(
            f"Recouvrement lexical du texte du profil avec l’offre : {profile_text_overlap:.0%}."
        )
    if not strengths:
        strengths.append("Aucun signal de correspondance exploitable n’a été détecté.")

    gaps = []
    if missing:
        gaps.append(
            "Compétences requises non détectées dans le profil (à vérifier) : "
            + ", ".join(missing)
            + "."
        )
    if not job.required_skills:
        gaps.append("L’offre ne définit pas de compétences requises explicites.")
    if not cv.experience:
        gaps.append("Aucune expérience structurée n’a été détectée dans le CV.")

    return MatchAnalysis(
        score=score,
        summary=(
            f"Score indicatif fondé sur la couverture des critères pour {job.title}; "
            "ce n’est pas une probabilité d’embauche."
        ),
        strengths=strengths,
        gaps=gaps,
        matched_skills=matched,
        signals=signals,
        score_version=SCORING_VERSION,
        score_weights=SCORING_WEIGHTS,
    )


def analyze_jobs_for_cv(
    cv: CandidateCV,
    jobs: list[JobPosting],
    retrieval_signals: dict[str, dict[str, float]] | None = None,
) -> list[MatchAnalysis]:
    """Compute deterministic scores using the semantic retrieval signals when available."""
    retrieval_signals = retrieval_signals or {}
    return [
        analyze_cv_job_match(
            cv,
            job,
            semantic_similarity=retrieval_signals.get(job.id, {}).get("semantic_similarity"),
        )
        for job in jobs
    ]


def analyze_cvs_for_job(
    job: JobPosting,
    cvs: list[CandidateCV],
    retrieval_signals: dict[str, dict[str, float]] | None = None,
) -> list[MatchAnalysis]:
    """Compute the same deterministic score in the recruiter-to-candidate direction."""
    retrieval_signals = retrieval_signals or {}
    return [
        analyze_cv_job_match(
            cv,
            job,
            semantic_similarity=retrieval_signals.get(cv.id, {}).get("semantic_similarity"),
        )
        for cv in cvs
    ]


llm = get_llm()


@tool
def analyze_jobs_for_cv_tool(cv_text: str, jobs_text: str) -> str:
    """Analyse un CV par rapport à une liste d'offres récupérées."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Tu es un expert en recrutement et en matching CV / offres d'emploi.
Tu dois analyser un CV par rapport à plusieurs offres et produire un JSON strict.

Réponds UNIQUEMENT avec un JSON valide de cette forme :
{{
  "matches": [
    {{
      "job_id": "...",
      "job_title": "...",
      "score": 85,
      "explanation": "...",
      "strengths": ["...", "..."],
      "gaps": ["...", "..."]
    }}
  ]
}}"""),
        ("human", """CV du candidat :
{cv_text}

Offres à analyser :
{jobs_text}

Produis le JSON d'analyse maintenant."""),
    ])
    chain = prompt | llm
    response = chain.invoke({
        "cv_text": cv_text,
        "jobs_text": jobs_text,
    })
    return response.content
