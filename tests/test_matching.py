from app.schemas.models import CandidateCV, JobPosting
from app.tools.analyze import analyze_cv_job_match
from app.tools.retrieve import retrieve_jobs_for_cv


def build_cv():
    return CandidateCV(
        id="cv-001",
        full_name="Alice Martin",
        summary="Data scientist with 5 years of experience in Python, ML, and analytics.",
        skills=["Python", "Machine Learning", "SQL", "NLP", "Pandas", "Scikit-learn"],
        experience=["Built recommendation systems", "Led ML product analytics"],
        raw_text="Python, Machine Learning, SQL, NLP, Pandas, Scikit-learn, analytics, recommendation systems",
    )


def build_jobs():
    return [
        JobPosting(
            id="job-001",
            title="Data Scientist",
            company="Acme",
            location="Paris",
            description="We need a data scientist with Python, ML, NLP, and analytics expertise.",
            required_skills=["Python", "Machine Learning", "SQL", "NLP"],
            keywords=["python", "ml", "sql", "nlp"],
        ),
        JobPosting(
            id="job-002",
            title="Frontend Engineer",
            company="Beta",
            location="Lyon",
            description="Build user interfaces with JavaScript and React.",
            required_skills=["JavaScript", "React", "CSS"],
            keywords=["javascript", "react", "css"],
        ),
    ]


def test_retrieve_jobs_for_cv_returns_best_match():
    cv = build_cv()
    jobs = build_jobs()

    results = retrieve_jobs_for_cv(cv, jobs, k=1)

    assert len(results) == 1
    assert results[0]["job"].id == "job-001"
    assert results[0]["score"] > 0.2


def test_analyze_cv_job_match_produces_reasonable_score():
    cv = build_cv()
    job = build_jobs()[0]

    analysis = analyze_cv_job_match(cv, job)

    assert 0 <= analysis.score <= 100
    assert analysis.summary
    assert analysis.strengths
    assert analysis.gaps or analysis.gaps == []
