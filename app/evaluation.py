from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.data.load_samples import load_sample_cvs, load_sample_jobs
from app.schemas.models import CandidateCV, JobPosting
from app.tools.analyze import SCORING_VERSION, analyze_jobs_for_cv
from app.tools.retrieve import retrieve_jobs_for_cv


def ranking_metrics(
    rankings: dict[str, list[str]],
    relevance: dict[str, dict[str, int]],
    k: int,
) -> dict[str, float]:
    if k < 1:
        raise ValueError("k doit être supérieur ou égal à 1")
    if not relevance:
        raise ValueError("Le jeu d’évaluation ne contient aucun cas annoté")

    recalls = []
    reciprocal_ranks = []
    ndcgs = []
    for query_id, grades in relevance.items():
        if not grades or any(grade < 0 for grade in grades.values()):
            raise ValueError(f"Annotations de pertinence invalides pour {query_id}")
        relevant = {item_id for item_id, grade in grades.items() if grade > 0}
        if not relevant:
            raise ValueError(f"Aucun résultat pertinent annoté pour {query_id}")
        full_ranking = rankings.get(query_id, [])
        ranked = full_ranking[:k]
        recalls.append(len(relevant.intersection(ranked)) / len(relevant))
        first_relevant_rank = next(
            (rank for rank, item_id in enumerate(full_ranking, 1) if item_id in relevant),
            None,
        )
        reciprocal_ranks.append(1 / first_relevant_rank if first_relevant_rank else 0.0)
        dcg = sum(
            (2 ** grades.get(item_id, 0) - 1) / math.log2(rank + 1)
            for rank, item_id in enumerate(ranked, 1)
        )
        ideal_grades = sorted(grades.values(), reverse=True)[:k]
        ideal_dcg = sum(
            (2**grade - 1) / math.log2(rank + 1)
            for rank, grade in enumerate(ideal_grades, 1)
        )
        ndcgs.append(dcg / ideal_dcg if ideal_dcg else 0.0)

    return {
        f"recall_at_{k}": round(sum(recalls) / len(recalls), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        f"ndcg_at_{k}": round(sum(ndcgs) / len(ndcgs), 4),
    }


def _read_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Le jeu d’évaluation doit contenir une liste « cases »")
    if not payload["cases"]:
        raise ValueError("Le jeu d’évaluation ne contient aucun cas")
    return payload


def run_evaluation(dataset_path: Path) -> dict[str, Any]:
    dataset = _read_dataset(dataset_path)
    if "cvs" in dataset and not isinstance(dataset["cvs"], list):
        raise ValueError("Le jeu d’évaluation « cvs » doit être une liste")
    if "jobs" in dataset and not isinstance(dataset["jobs"], list):
        raise ValueError("Le jeu d’évaluation « jobs » doit être une liste")
    cvs = {
        cv.id: cv
        for cv in (
            [CandidateCV.model_validate(item) for item in dataset["cvs"]]
            if "cvs" in dataset
            else load_sample_cvs()
        )
    }
    jobs = (
        [JobPosting.model_validate(item) for item in dataset["jobs"]]
        if "jobs" in dataset
        else load_sample_jobs()
    )
    if "cvs" in dataset and len(cvs) != len(dataset["cvs"]):
        raise ValueError("Le jeu d’évaluation contient des identifiants de CV dupliqués")
    if len({job.id for job in jobs}) != len(jobs):
        raise ValueError("Le jeu d’évaluation contient des identifiants d’offre dupliqués")
    job_ids = {job.id for job in jobs}
    relevance: dict[str, dict[str, int]] = {}
    rankings: dict[str, list[str]] = {}

    for case in dataset["cases"]:
        if not isinstance(case, dict):
            raise ValueError("Chaque cas d’évaluation doit être un objet")
        cv_id = case.get("cv_id")
        relevant_job_ids = case.get("relevant_job_ids")
        if not isinstance(cv_id, str) or cv_id not in cvs:
            raise ValueError(f"CV d’évaluation inconnu : {cv_id}")
        if (
            not isinstance(relevant_job_ids, list)
            or not relevant_job_ids
            or any(job_id not in job_ids for job_id in relevant_job_ids)
        ):
            raise ValueError(f"Offres pertinentes invalides pour {cv_id}")
        if cv_id in relevance:
            raise ValueError(f"CV dupliqué dans le jeu d’évaluation : {cv_id}")

        retrieved = retrieve_jobs_for_cv(cvs[cv_id], jobs, k=len(jobs))
        analyses = analyze_jobs_for_cv(
            cvs[cv_id],
            [match["job"] for match in retrieved],
            {
                match["job"].id: {"semantic_similarity": match["semantic_similarity"]}
                for match in retrieved
            },
        )
        rankings[cv_id] = [
            match["job"].id
            for match, _ in sorted(
                zip(retrieved, analyses),
                key=lambda item: (-item[1].score, item[0]["job"].id),
            )
        ]
        relevance[cv_id] = {job_id: 1 for job_id in relevant_job_ids}

    metrics = {}
    for k in (1, 3, 5):
        metrics.update(ranking_metrics(rankings, relevance, k))
    return {
        "pipeline_version": SCORING_VERSION,
        "dataset_name": dataset.get("name", dataset_path.stem),
        "dataset_type": dataset.get("type", "custom"),
        "label_source": dataset.get("label_source", "Non précisé"),
        "case_count": len(relevance),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "metric_definitions": {
            "recall_at_k": "Part des offres pertinentes annotées retrouvées dans le top-k.",
            "mrr": "Rang réciproque moyen de la première offre pertinente.",
            "ndcg_at_k": "Qualité du classement top-k par rapport aux annotations.",
        },
        "warning": (
            "Ce benchmark synthétique valide le fonctionnement du pipeline; il ne démontre "
            "pas sa qualité sur des données de recrutement réelles."
            if dataset.get("type") == "synthetic_demo"
            else "Les métriques dépendent de la qualité et de la représentativité des annotations."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Évalue le classement CV–offres annoté.")
    parser.add_argument("--dataset", type=Path, default=Path(settings.MATCH_EVALUATION_DATASET))
    parser.add_argument("--report", type=Path, default=Path(settings.MATCH_EVALUATION_REPORT))
    args = parser.parse_args()

    report = run_evaluation(args.dataset)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
