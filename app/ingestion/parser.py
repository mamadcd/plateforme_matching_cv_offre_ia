from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Literal

from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.skills import extract_skills
from app.ingestion.vision import original_page_images, structure_cv
from app.schemas.models import CandidateCV, ExtractionQuality, JobPosting


DocumentKind = Literal["cv", "job"]
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".docx", ".txt", ".md", ".csv"}

def _extract_text(content: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=False)
        pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
        if any(len(page.strip()) < 80 for page in pages):
            import pymupdf
            import pytesseract
            from PIL import Image

            with pymupdf.open(stream=content, filetype="pdf") as document:
                for index, page_text in enumerate(pages):
                    if len(page_text.strip()) >= 80:
                        continue
                    pixmap = document[index].get_pixmap(dpi=200, alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    ocr_text = pytesseract.image_to_string(image, lang="fra+eng")
                    if len(ocr_text.strip()) > len(page_text.strip()):
                        pages[index] = ocr_text
        return "\n\n".join(pages)

    if suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(content))
        blocks = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    blocks.append(block.text)
            elif isinstance(block, Table):
                for row in block.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        blocks.append(" | ".join(cells))
        for section in document.sections:
            blocks.extend(
                paragraph.text
                for paragraph in [*section.header.paragraphs, *section.footer.paragraphs]
                if paragraph.text.strip()
            )
        return "\n".join(blocks)

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}:
        from PIL import Image
        import pytesseract

        image = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(image, lang="fra+eng")

    return content.decode("utf-8-sig", errors="replace")


def _document_id(kind: DocumentKind, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()[:16]
    if kind == "cv":
        return f"cv-{digest[:6]}"
    return f"{kind}-upload-{digest}"


def _lines(text: str) -> list[str]:
    return [line.strip(" -*\t") for line in text.splitlines() if line.strip()]


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


def _parse_cv(text: str, content: bytes, images: list[str]) -> CandidateCV:
    lines = _lines(text)
    document_id = _document_id("cv", content)
    structured = structure_cv(text, document_id, images)
    name = structured.full_name or next(
        (line for line in lines[:5] if len(line.split()) in {2, 3} and not any(char.isdigit() for char in line)),
        "",
    )
    skills = []
    seen_skills: set[str] = set()
    for skill in [*structured.skills, *extract_skills(text)]:
        normalized = skill.strip()
        if normalized and normalized.casefold() not in seen_skills:
            skills.append(normalized)
            seen_skills.add(normalized.casefold())
        if len(skills) == 25:
            break
    experience = (
        structured.experience
        or _section(text, ("expérience", "experience", "parcours", "work history"))
    )[:8]
    summary = structured.summary or next((line for line in lines if len(line) > 35), text[:240])
    completeness = round(
        15 * bool(name)
        + 25 * bool(summary)
        + 25 * bool(skills)
        + 25 * bool(experience)
        + 10 * bool(text)
    )
    warnings = []
    if not name:
        warnings.append("Nom non détecté; vérification conseillée.")
    if not skills:
        warnings.append("Aucune compétence du référentiel n’a été détectée.")
    if not experience:
        warnings.append("Aucune section expérience n’a été détectée.")
    return CandidateCV(
        id=document_id,
        full_name=name[:120],
        summary=summary[:500],
        skills=skills,
        experience=experience,
        raw_text=(structured.raw_text or text)[:50_000],
        extracted_text=text,
        extraction_quality=ExtractionQuality(completeness=completeness, warnings=warnings),
    )


def _parse_job(text: str, content: bytes, filename: str) -> JobPosting:
    lines = _lines(text)
    title = lines[0][:160] if lines else Path(filename).stem.replace("_", " ").title()
    company_match = re.search(r"(?:entreprise|company)\s*:\s*(.+)", text, re.I)
    location_match = re.search(r"(?:lieu|localisation|location)\s*:\s*(.+)", text, re.I)
    skills = extract_skills(text)
    completeness = round(
        20 * bool(lines)
        + 15 * bool(company_match)
        + 10 * bool(location_match)
        + 30 * bool(text)
        + 25 * bool(skills)
    )
    warnings = []
    if not company_match:
        warnings.append("Entreprise non détectée.")
    if not location_match:
        warnings.append("Localisation non détectée.")
    if not skills:
        warnings.append("Aucune compétence du référentiel n’a été détectée.")
    return JobPosting(
        id=_document_id("job", content),
        title=title,
        company=company_match.group(1).strip()[:160] if company_match else "Entreprise à préciser",
        location=location_match.group(1).strip()[:160] if location_match else "",
        description=text[:2_000],
        required_skills=skills,
        keywords=[skill.casefold() for skill in skills],
        extraction_quality=ExtractionQuality(completeness=completeness, warnings=warnings),
    )


def parse_document(content: bytes, filename: str, kind: DocumentKind) -> CandidateCV | JobPosting:
    """Extract and normalize an uploaded document without persisting its bytes."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Type de fichier non supporté: {suffix or 'inconnu'}")
    text = _extract_text(content, suffix)
    if kind == "cv":
        images = original_page_images(content, suffix)
        if not text.strip() and not images:
            raise ValueError("Aucun texte ni image exploitable n'a été détecté dans le CV")
        return _parse_cv(text, content, images)
    if not text.strip():
        raise ValueError("Aucun texte exploitable n'a été détecté dans le document")
    return _parse_job(text, content, filename)