import pytest

from app.evaluation import ranking_metrics, run_evaluation
from app.core.skills import canonicalize_skill, extract_skills
from app.schemas.models import CandidateCV, JobPosting
from app.tools.analyze import SCORING_VERSION, analyze_cv_job_match
from app.tools.retrieve import remove_cv_from_index


def test_skill_extraction_normalizes_aliases_without_substring_false_positives():
    assert extract_skills("JavaScript, NLP et traitement automatique du langage naturel") == [
        "JavaScript",
        "NLP",
    ]
    assert canonicalize_skill("apprentissage automatique") == "Machine Learning"


def test_parser_and_ranker_score_explicit_evidence_deterministically():
    cv = CandidateCV(
        id="cv",
        full_name="Candidate",
        summary="Data scientist Python et SQL",
        skills=["Python", "SQL"],
        experience=["Développement de modèles de données en Python"],
    )
    job = JobPosting(
        id="job",
        title="Data Scientist",
        company="Example",
        required_skills=["Python", "SQL", "Machine Learning"],
        description="Construire des modèles de machine learning et des analyses.",
    )

    analysis = analyze_cv_job_match(cv, job, semantic_similarity=0.8)

    assert analysis.score_version == SCORING_VERSION
    assert analysis.score == 67
    assert analysis.matched_skills == ["Python", "SQL"]
    assert analysis.signals.required_skills_coverage == pytest.approx(2 / 3)
    assert analysis.signals.semantic_similarity == 0.8
    assert any("Machine Learning" in gap for gap in analysis.gaps)


def test_ranking_metrics_match_perfect_and_missed_rankings():
    relevance = {
        "cv-good": {"job-a": 1, "job-b": 1},
        "cv-miss": {"job-c": 1},
    }

    perfect = ranking_metrics(
        {"cv-good": ["job-a", "job-b"], "cv-miss": ["job-c"]},
        relevance,
        k=2,
    )
    imperfect = ranking_metrics(
        {"cv-good": ["job-x", "job-a"], "cv-miss": ["job-x"]},
        relevance,
        k=2,
    )

    assert perfect == {"recall_at_2": 1.0, "mrr": 1.0, "ndcg_at_2": 1.0}
    assert imperfect["recall_at_2"] == 0.25
    assert imperfect["mrr"] == 0.25
    assert imperfect["ndcg_at_2"] < perfect["ndcg_at_2"]


def test_ranking_metrics_reject_empty_or_unlabeled_cases():
    with pytest.raises(ValueError, match="aucun cas"):
        ranking_metrics({}, {}, k=3)
    with pytest.raises(ValueError, match="[Aa]ucun résultat pertinent"):
        ranking_metrics({"cv": []}, {"cv": {"job": 0}}, k=3)


def test_custom_evaluation_dataset_runs_without_persisting_source_text(tmp_path, monkeypatch):
    import json
    import app.evaluation as evaluation

    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(
        json.dumps(
            {
                "name": "mini-test",
                "cvs": [
                    {
                        "id": "cv-test",
                        "full_name": "Test Candidate",
                        "summary": "Python data analysis",
                        "skills": ["Python"],
                        "experience": ["Python data analysis"],
                    }
                ],
                "jobs": [
                    {
                        "id": "job-test",
                        "title": "Data Analyst",
                        "company": "Example",
                        "required_skills": ["Python"],
                        "description": "Python data analysis",
                    }
                ],
                "cases": [{"cv_id": "cv-test", "relevant_job_ids": ["job-test"]}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        evaluation,
        "retrieve_jobs_for_cv",
        lambda cv, jobs, k: [{"job": jobs[0], "semantic_similarity": 0.9}],
    )

    report = run_evaluation(dataset_path)

    assert report["case_count"] == 1
    assert report["metrics"]["recall_at_1"] == 1
    assert "Test Candidate" not in json.dumps(report)


def test_revoking_search_consent_removes_the_persisted_vector(tmp_path, monkeypatch):
    from langchain_community.vectorstores import Chroma
    import app.tools.retrieve as retrieve

    monkeypatch.setattr(retrieve.settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(retrieve, "_cvs_vectorstore", None)
    collection = Chroma(persist_directory=str(tmp_path), collection_name="cvs")
    collection._collection.add(
        ids=["private-cv"],
        embeddings=[[0.1, 0.2]],
        documents=["candidate profile text"],
        metadatas=[{"id": "private-cv", "full_name": "Private Candidate"}],
    )

    remove_cv_from_index("private-cv")

    assert collection._collection.get(include=[])["ids"] == []
