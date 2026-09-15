from typing import List, Optional

from pydantic import BaseModel, Field


class CandidateCV(BaseModel):
    id: str
    full_name: str
    summary: str = ""
    skills: List[str] = Field(default_factory=list)
    experience: List[str] = Field(default_factory=list)
    raw_text: str = ""


class JobPosting(BaseModel):
    id: str
    title: str
    company: str
    location: str = ""
    description: str = ""
    required_skills: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class MatchAnalysis(BaseModel):
    score: int
    summary: str
    strengths: List[str]
    gaps: List[str]
    matched_skills: List[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    job: JobPosting
    score: float
    matched_skills: List[str] = Field(default_factory=list)


class Job(BaseModel):
    id: str
    title: str
    description: str
    location: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)


class MatchResultLegacy(BaseModel):
    job_id: str
    job_title: str
    score: float = Field(..., ge=0, le=100, description="Score de matching entre 0 et 100")
    explanation: str
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)


class MatchingResponse(BaseModel):
    cv_summary: str
    matches: List[MatchResultLegacy]
    message: str = "Matching terminé"


class ReverseMatchResult(BaseModel):
    cv_id: str
    cv_name: str
    score: float = Field(..., ge=0, le=100)
    explanation: str
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)


class JobMatchingResponse(BaseModel):
    job_summary: str
    matches: List[ReverseMatchResult]
    message: str = "Matching inverse terminé"
