from __future__ import annotations

import base64
import io

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings


SYSTEM_PROMPT = """Tu es un expert en extraction et validation de CV.

Tu reçois le texte extrait automatiquement du CV et, si disponible, les images des pages originales.
Compare le texte avec les images, corrige les erreurs d’OCR et les blocs mal extraits.
N’invente aucune information qui n’est pas visible ou présente dans le texte fourni.
Produis uniquement un objet JSON valide contenant exactement les champs suivants :
{
  "id": "string",
  "full_name": "string",
  "summary": "string",
  "skills": ["string"],
  "experience": ["string"],
  "raw_text": "string"
}
Règles :
- full_name : nom complet uniquement.
- summary : 1 à 3 phrases, fidèle au profil.
- skills : compétences nettoyées, sans doublons, maximum 25.
- experience : 3 à 8 puces synthétiques et impactantes, sans entreprise ni dates; n’invente rien si le CV en contient moins.
- raw_text : texte dense et concis optimisé pour le matching, avec les mots-clés et termes techniques visibles.
- id : utilise exactement l’identifiant fourni par l’application.
- Réponds uniquement avec le JSON, sans texte avant ou après.
Le CV peut être de n’importe quel domaine et de n’importe quelle mise en page."""


class StructuredCV(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str = ""
    full_name: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    raw_text: str = ""


class OllamaIngestionError(RuntimeError):
    """Raised when Ollama cannot produce a valid structured CV."""


def original_page_images(content: bytes, suffix: str) -> list[str]:
    if suffix == ".pdf":
        import pymupdf
        from PIL import Image

        images: list[str] = []
        with pymupdf.open(stream=content, filetype="pdf") as document:
            for page in document[:1]:
                pixmap = page.get_pixmap(dpi=100, alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                image.thumbnail((384, 384))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                images.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        return images

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            buffer = io.BytesIO()
            converted = image.convert("RGB")
            converted.thumbnail((384, 384))
            converted.save(buffer, format="PNG")
        return [base64.b64encode(buffer.getvalue()).decode("ascii")]

    return []


def structure_cv(
    extracted_text: str,
    document_id: str,
    images: list[str],
) -> StructuredCV:
    model = settings.OLLAMA_VISION_MODEL if images else settings.OLLAMA_TEXT_MODEL
    user_message: dict[str, object] = {
        "role": "user",
        "content": (
            f"Identifiant à utiliser : {document_id}\n\n"
            "Texte extrait automatiquement du CV :\n"
            "---\n"
            f"{extracted_text[:10_000]}\n"
            "---\n\n"
            "Compare le texte avec les images originales lorsqu’elles sont fournies, "
            "puis renvoie le JSON structuré."
        ),
    }
    if images:
        user_message["images"] = images

    try:
        response = httpx.post(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    user_message,
                ],
                "format": StructuredCV.model_json_schema(),
                "stream": False,
                "keep_alive": 0,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 768,
                    "num_ctx": settings.OLLAMA_NUM_CTX,
                    "num_thread": settings.OLLAMA_NUM_THREAD,
                },
            },
            timeout=300.0,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        structured = StructuredCV.model_validate_json(content)
    except httpx.HTTPStatusError as error:
        detail = error.response.text.strip()[:1_000]
        raise OllamaIngestionError(
            f"Ollama a refusé la requête (HTTP {error.response.status_code}): "
            f"{detail or error}"
        ) from error
    except httpx.RequestError as error:
        raise OllamaIngestionError(
            f"Le service Ollama est injoignable: {error}"
        ) from error
    except ValidationError as error:
        issues = [
            ".".join(str(part) for part in issue["loc"]) or str(issue["type"])
            for issue in error.errors(include_input=False)[:5]
        ]
        detail = ", ".join(issues) or "schéma non respecté"
        raise OllamaIngestionError(
            f"Réponse Ollama invalide ({detail})."
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        raise OllamaIngestionError(
            "La réponse d’Ollama n’est pas un JSON exploitable."
        ) from error

    if structured.id != document_id:
        structured = structured.model_copy(update={"id": document_id})

    normalized_skills = []
    seen_skills = set()
    for skill in structured.skills:
        normalized = skill.strip()
        if normalized and normalized.casefold() not in seen_skills:
            normalized_skills.append(normalized)
            seen_skills.add(normalized.casefold())
            if len(normalized_skills) == 25:
                break
    normalized_experience = [
        item.strip() for item in structured.experience if item.strip()
    ][:8]
    return structured.model_copy(
        update={
            "full_name": structured.full_name.strip(),
            "summary": structured.summary.strip(),
            "skills": normalized_skills,
            "experience": normalized_experience,
            "raw_text": structured.raw_text.strip(),
        }
    )
