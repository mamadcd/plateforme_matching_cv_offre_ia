from __future__ import annotations

import json
from pathlib import Path

from app.schemas.models import CandidateCV, JobPosting


ROOT = Path(__file__).resolve().parent
CV_DIR = ROOT / "sample_cvs"
JOB_DIR = ROOT / "sample_jobs"


def load_sample_cvs() -> list[CandidateCV]:
    cvs: list[CandidateCV] = []
    for path in sorted(CV_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cvs.append(CandidateCV(**payload))
    return cvs


def load_sample_jobs() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for path in sorted(JOB_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        jobs.append(JobPosting(**payload))
    return jobs
