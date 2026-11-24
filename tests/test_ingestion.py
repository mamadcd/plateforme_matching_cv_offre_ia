import json as json_lib
import re
from io import BytesIO

import httpx
import pymupdf
import pytest
from docx import Document

from app.ingestion import parser
from app.ingestion.parser import parse_document
from app.ingestion.vision import OllamaIngestionError, StructuredCV, original_page_images


def _mock_structure_cv(text, document_id, images):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    experience = parser._section(text, ("expérience", "experience", "parcours", "work history"))
    return StructuredCV(
        id=document_id,
        full_name=lines[0] if lines else "",
        summary=next((line for line in lines if len(line) > 35), ""),
        skills=parser.extract_skills(text),
        experience=experience,
        raw_text=text,
    )


def test_parse_text_cv_matches_domain_shape(monkeypatch):
    monkeypatch.setattr(parser, "structure_cv", _mock_structure_cv)
    cv = parse_document(
        b"Alice Martin\nData scientist avec Python et SQL\nCompetences: Python, SQL, Machine Learning\nExperience\nDeveloppement de modeles",
        "alice.txt",
        "cv",
    )

    assert re.fullmatch(r"cv-[a-f0-9]{6}", cv.id)
    assert cv.full_name == "Alice Martin"
    assert "Python" in cv.skills
    assert cv.experience == ["Developpement de modeles"]
    assert cv.extraction_quality.completeness == 100


def test_cv_keeps_full_extracted_text_separate_from_llm_text(monkeypatch):
    source_text = "CV original avec tous les détails.\n" * 400

    def structure_with_condensed_text(text, document_id, images):
        return StructuredCV(
            id=document_id,
            full_name="Alice Martin",
            summary="Profil développeuse",
            skills=["Python"],
            experience=["Développement logiciel"],
            raw_text="Texte condensé pour le matching.",
        )

    monkeypatch.setattr(parser, "structure_cv", structure_with_condensed_text)
    cv = parse_document(source_text.encode("utf-8"), "alice.txt", "cv")

    assert cv.extracted_text == source_text
    assert cv.raw_text == "Texte condensé pour le matching."


def test_pdf_uses_ocr_for_pages_with_only_a_small_text_fragment(monkeypatch):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Titre")
    content = pdf.tobytes()
    pdf.close()
    monkeypatch.setattr(
        "pytesseract.image_to_string",
        lambda image, lang: "Titre\nTexte OCR complet de la page",
    )

    text = parser._extract_text(content, ".pdf")

    assert "Texte OCR complet de la page" in text


def test_docx_extraction_includes_table_content():
    document = Document()
    document.add_paragraph("Alice Martin")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Python"
    table.cell(0, 1).text = "Expérience backend"
    buffer = BytesIO()
    document.save(buffer)

    text = parser._extract_text(buffer.getvalue(), ".docx")

    assert "Alice Martin" in text
    assert "Python | Expérience backend" in text


def test_skill_catalog_does_not_match_java_inside_javascript(monkeypatch):
    monkeypatch.setattr(parser, "structure_cv", _mock_structure_cv)
    cv = parse_document(
        b"Taylor Candidate\nFrontend engineer JavaScript, React and TypeScript",
        "frontend.txt",
        "cv",
    )

    assert "JavaScript" in cv.skills
    assert "Java" not in cv.skills
    assert cv.extraction_quality.completeness < 100


def test_pdf_cv_sends_original_pages_to_ollama_vision(monkeypatch):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Alice Martin\nData Scientist")
    content = pdf.tobytes()
    pdf.close()
    requests = []
    monkeypatch.setattr("pytesseract.image_to_string", lambda image, lang: "")

    def fake_post(url, *, json, timeout):
        requests.append((url, json, timeout))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json_lib.dumps({
                        "id": "ignored",
                        "full_name": "Alice Martin",
                        "summary": "Data scientist",
                        "skills": ["Python", "Python"],
                        "experience": ["Développement de modèles"],
                        "raw_text": "Data scientist Python modèles",
                    })
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.ingestion.vision.httpx.post", fake_post)
    cv = parse_document(content, "alice.pdf", "cv")

    assert len(requests) == 1
    url, payload, timeout = requests[0]
    assert url.endswith("/api/chat")
    assert payload["model"] == "granite3.2-vision:2b"
    assert payload["format"] == StructuredCV.model_json_schema()
    assert payload["options"]["num_predict"] == 768
    assert len(payload["messages"][1]["images"]) == 1
    assert "Data Scientist" in payload["messages"][1]["content"]
    assert payload["options"]["num_ctx"] == 3072
    assert payload["options"]["num_thread"] == 8
    assert payload["keep_alive"] == 0
    assert timeout == 300.0
    assert cv.full_name == "Alice Martin"
    assert cv.skills == ["Python"]
    assert re.fullmatch(r"cv-[a-f0-9]{6}", cv.id)


def test_pdf_vision_uses_only_the_first_page_for_cpu_ingestion():
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()

    assert len(original_page_images(content, ".pdf")) == 1


def test_cv_can_be_structured_from_original_image_when_text_extraction_is_empty(monkeypatch):
    def structure_from_image(text, document_id, images):
        assert text == ""
        assert images == ["original-page"]
        return StructuredCV(
            id=document_id,
            full_name="Alex Martin",
            summary="Profil développeur",
            skills=["Python"],
            experience=["Développement logiciel"],
            raw_text="Python développement logiciel",
        )

    monkeypatch.setattr(parser, "_extract_text", lambda content, suffix: "")
    monkeypatch.setattr(parser, "original_page_images", lambda content, suffix: ["original-page"])
    monkeypatch.setattr(parser, "structure_cv", structure_from_image)

    cv = parse_document(b"image bytes", "scan.png", "cv")

    assert cv.full_name == "Alex Martin"
    assert cv.extraction_quality.completeness == 90


def test_ollama_partial_json_uses_local_parser_fallbacks(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json_lib.dumps({
                        "full_name": "Alice Martin",
                        "unexpected_field": "ignored",
                    })
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.ingestion.vision.httpx.post", fake_post)
    cv = parse_document(
        b"Alice Martin\nData scientist avec Python et SQL\nExperience\nDeveloppement de modeles",
        "alice.txt",
        "cv",
    )

    assert cv.full_name == "Alice Martin"
    assert "Python" in cv.skills
    assert cv.experience == ["Developpement de modeles"]
    assert cv.raw_text.startswith("Alice Martin")


def test_ollama_invalid_json_reports_safe_diagnostic(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"message": {"content": '{"id":'}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.ingestion.vision.httpx.post", fake_post)

    with pytest.raises(OllamaIngestionError, match="json_invalid"):
        parser.structure_cv("private extracted text", "cv-upload-123", [])


def test_ollama_server_error_is_reported_to_the_caller(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            500,
            json={"error": "out of memory"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.ingestion.vision.httpx.post", fake_post)

    with pytest.raises(OllamaIngestionError, match="out of memory"):
        parser.structure_cv("extracted text", "cv-upload-123", [])


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