from app.ingestion.parser import parse_document


def test_parse_text_cv_matches_domain_shape():
    cv = parse_document(
        b"Alice Martin\nData scientist avec Python et SQL\nCompetences: Python, SQL, Machine Learning\nExperience\nDeveloppement de modeles",
        "alice.txt",
        "cv",
    )

    assert cv.id.startswith("cv-upload-")
    assert cv.full_name == "Alice Martin"
    assert "Python" in cv.skills
    assert cv.experience == ["Developpement de modeles"]


def test_parse_text_job_matches_sample_contract():
    job = parse_document(
        b"Data Scientist\nEntreprise: Acme\nLocalisation: Paris\nNous cherchons Python, SQL et NLP.",
        "job.txt",
        "job",
    )

    assert job.id.startswith("job-upload-")
    assert job.title == "Data Scientist"
    assert job.company == "Acme"
    assert job.location == "Paris"
    assert "Python" in job.required_skills