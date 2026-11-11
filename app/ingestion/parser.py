from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Literal

from app.schemas.models import CandidateCV, JobPosting


DocumentKind = Literal["cv", "job"]
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".docx", ".txt", ".md", ".csv"}

SKILL_CATALOG = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Vue", "Angular", "HTML", "CSS",
    "SQL", "PostgreSQL", "MongoDB", "Docker", "Kubernetes", "AWS", "Azure", "Git",
    "Machine Learning", "Deep Learning", "NLP", "Data Analysis", "Pandas", "NumPy",
    "Scikit-learn", "TensorFlow", "PyTorch", "Spark", "Kafka", "FastAPI", "Django",
    "Spring", "Node.js", "Figma", "Product Management", "A/B Testing", "Analytics",
]


def _extract_text(content: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=False)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()

    if suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()).strip()

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}:
        from PIL import Image
        import pytesseract

        image = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(image, lang="fra+eng").strip()

    return content.decode("utf-8-sig", errors="replace").strip()


def _document_id(kind: DocumentKind, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()[:16]
    return f"{kind}-upload-{digest}"


def _lines(text: str) -> list[str]:
    return [line.strip(" -*\t") for line in text.splitlines() if line.strip()]


def _skills(text: str) -> list[str]:
    lowered = text.casefold()
    found = [skill for skill in SKILL_CATALOG if skill.casefold() in lowered]
    return list(dict.fromkeys(found))


def _section(text: str, names: tuple[str, ...]) -> list[str]:
    lines = _lines(text)
    start = next((index for index, line in enumerate(lines) if any(name in line.casefold() for name in names)), None)
    if start is None:
        return []
    values: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^(compétences?|skills?|expérience|experience|formation|education|description|missions?)\s*[:#]?", line, re.I):
            break
        values.append(line)
    return values[:12]


def _parse_cv(text: str, content: bytes, filename: str) -> CandidateCV:
    lines = _lines(text)
    name = next((line for line in lines[:5] if len(line.split()) in {2, 3} and not any(char.isdigit() for char in line)), Path(filename).stem.replace("_", " ").title())
    summary = next((line for line in lines if len(line) > 35), text[:240])
    experience = _section(text, ("expérience", "experience", "parcours", "work history"))
    return CandidateCV(
        id=_document_id("cv", content),
        full_name=name[:120],
        summary=summary[:500],
        skills=_skills(text),
        experience=experience,
        raw_text=text[:50_000],
    )


def _parse_job(text: str, content: bytes, filename: str) -> JobPosting:
    lines = _lines(text)
    title = lines[0][:160] if lines else Path(filename).stem.replace("_", " ").title()
    company_match = re.search(r"(?:entreprise|company)\s*:\s*(.+)", text, re.I)
    location_match = re.search(r"(?:lieu|localisation|location)\s*:\s*(.+)", text, re.I)
    skills = _skills(text)
    return JobPosting(
        id=_document_id("job", content),
        title=title,
        company=company_match.group(1).strip()[:160] if company_match else "Entreprise à préciser",
        location=location_match.group(1).strip()[:160] if location_match else "",
        description=text[:2_000],
        required_skills=skills,
        keywords=[skill.casefold() for skill in skills],
    )


def parse_document(content: bytes, filename: str, kind: DocumentKind) -> CandidateCV | JobPosting:
    """Extract and normalize an uploaded document without persisting its bytes."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Type de fichier non supporté: {suffix or 'inconnu'}")
    text = _extract_text(content, suffix)
    if not text:
        raise ValueError("Aucun texte exploitable n'a été détecté dans le document")
    return _parse_cv(text, content, filename) if kind == "cv" else _parse_job(text, content, filename)