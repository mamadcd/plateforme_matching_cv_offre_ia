from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm import get_llm
from app.schemas.models import CandidateCV, JobPosting, MatchAnalysis


logger = logging.getLogger(__name__)


def generate_match_analysis(cv: CandidateCV, job: JobPosting) -> MatchAnalysis:
    cv_skills = {skill.lower() for skill in cv.skills}
    required_skills = {skill.lower() for skill in job.required_skills}
    matched = sorted(cv_skills & required_skills)
    missing = sorted(required_skills - cv_skills)

    base_score = (len(matched) / max(1, len(required_skills))) * 70
    bonus = 20 if any(skill in cv_skills for skill in ["python", "sql", "machine learning", "nlp"]) else 0
    experience_bonus = 10 if cv.experience else 0
    score = max(0, min(100, int(round(base_score + bonus + experience_bonus))))

    summary = (
        f"{cv.full_name} matches {job.title} at {job.company} with {len(matched)} overlapping skills "
        f"out of {len(required_skills)} required skills."
    )

    strengths = [
        f"Strong overlap on: {', '.join(matched) if matched else 'no direct skill match'}",
    ]
    if cv.experience:
        strengths.append("Relevant work experience is present in the profile.")

    gaps = [] if not missing else [f"Missing or weakly covered: {', '.join(missing)}"]

    return MatchAnalysis(
        score=score,
        summary=summary,
        strengths=strengths,
        gaps=gaps,
        matched_skills=matched,
    )


def generate_llm_match_analyses(cv: CandidateCV, jobs: list[JobPosting]) -> list[MatchAnalysis]:
    """Use the configured LLM to analyze retrieved jobs, with a local fallback."""
    if not jobs:
        return []

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Tu es un expert en recrutement. Analyse le CV par rapport aux offres.
Réponds uniquement avec un JSON valide sous cette forme :
{{"matches": [{{"job_id": "...", "score": 85, "explanation": "...",
"strengths": ["..."], "gaps": ["..."], "matched_skills": ["..."]}}]}}
Le score doit être entre 0 et 100. Base-toi sur les compétences explicites et implicites,
l'expérience, la séniorité et la cohérence entre le parcours et l'offre."""),
        ("human", "CV :\n{cv_text}\n\nOffres :\n{jobs_text}"),
    ])
    jobs_text = "\n\n".join(
        json.dumps(job.model_dump(), ensure_ascii=False) for job in jobs
    )

    try:
        response = (prompt | llm).invoke({"cv_text": cv.raw_text, "jobs_text": jobs_text})
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        payload = json.loads(content)
        analyses_by_id = {
            item["job_id"]: MatchAnalysis(
                score=max(0, min(100, int(item["score"]))),
                summary=item["explanation"],
                strengths=item.get("strengths", []),
                gaps=item.get("gaps", []),
                matched_skills=item.get("matched_skills", []),
            )
            for item in payload["matches"]
        }
        return [
            analyses_by_id.get(job.id, generate_match_analysis(cv, job))
            for job in jobs
        ]
    except Exception as error:
        logger.warning("OpenAI match analysis failed; using local fallback: %s", error)
        return [generate_match_analysis(cv, job) for job in jobs]


def generate_llm_cv_match_analyses(job: JobPosting, cvs: list[CandidateCV]) -> list[MatchAnalysis]:
    """Analyze the same match from the job's perspective for reverse search."""
    if not cvs:
        return []

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Tu es un recruteur expert. Analyse plusieurs CV pour une offre d'emploi.
Réponds uniquement avec un JSON valide sous cette forme :
{{"matches": [{{"cv_id": "...", "score": 85, "explanation": "...",
"strengths": ["..."], "gaps": ["..."], "matched_skills": ["..."]}}]}}
Le score doit être entre 0 et 100. Évalue les compétences, l'expérience, la séniorité,
la localisation et la mobilité par rapport aux contraintes de l'offre."""),
        ("human", "Offre :\n{job_text}\n\nCV :\n{cvs_text}"),
    ])
    cvs_text = "\n\n".join(
        json.dumps(cv.model_dump(), ensure_ascii=False) for cv in cvs
    )

    try:
        response = (prompt | llm).invoke({
            "job_text": json.dumps(job.model_dump(), ensure_ascii=False),
            "cvs_text": cvs_text,
        })
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        payload = json.loads(content)
        analyses_by_id = {
            item["cv_id"]: MatchAnalysis(
                score=max(0, min(100, int(item["score"]))),
                summary=item["explanation"],
                strengths=item.get("strengths", []),
                gaps=item.get("gaps", []),
                matched_skills=item.get("matched_skills", []),
            )
            for item in payload["matches"]
        }
        return [
            analyses_by_id.get(cv.id, generate_match_analysis(cv, job))
            for cv in cvs
        ]
    except Exception as error:
        logger.warning("Reverse match analysis failed; using local analysis: %s", error)
        return [generate_match_analysis(cv, job) for cv in cvs]


llm = get_llm()


@tool
def generate_match_analysis_tool(cv_text: str, jobs_text: str) -> str:
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
