from __future__ import annotations

import re
import unicodedata


SKILL_ALIASES = {
    "A/B Testing": ("a/b testing", "ab testing", "tests a/b"),
    "Agile": ("agile",),
    "Analytics": ("analytics",),
    "AWS": ("aws", "amazon web services"),
    "B2B": ("b2b",),
    "Business Intelligence": ("business intelligence", "bi"),
    "CSS": ("css",),
    "Data Analysis": ("data analysis", "analyse de données", "analyse des données"),
    "Deep Learning": ("deep learning", "apprentissage profond"),
    "Docker": ("docker",),
    "Figma": ("figma",),
    "Git": ("git",),
    "HTML": ("html",),
    "Java": ("java",),
    "JavaScript": ("javascript", "js"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Machine Learning": ("machine learning", "apprentissage automatique", "ml"),
    "MongoDB": ("mongodb",),
    "NLP": (
        "nlp",
        "natural language processing",
        "traitement automatique du langage naturel",
        "taln",
    ),
    "Node.js": ("node.js", "nodejs"),
    "NumPy": ("numpy",),
    "Pandas": ("pandas",),
    "PostgreSQL": ("postgresql", "postgres"),
    "Product Analytics": ("product analytics", "analytics produit"),
    "Product Discovery": ("product discovery", "discovery produit"),
    "Product Management": ("product management", "gestion de produit", "gestion produit"),
    "Product Strategy": ("product strategy", "stratégie produit"),
    "Python": ("python",),
    "React": ("react",),
    "Roadmapping": ("roadmapping", "roadmap", "feuille de route produit"),
    "Scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "Scrum": ("scrum",),
    "SaaS": ("saas",),
    "SQL": ("sql",),
    "Spring Boot": ("spring boot", "spring"),
    "Tableau": ("tableau",),
    "TensorFlow": ("tensorflow",),
    "TypeScript": ("typescript", "ts"),
    "UX Design": ("ux design", "expérience utilisateur"),
    "UX Research": ("ux research", "recherche utilisateur"),
    "Vue": ("vue", "vue.js", "vuejs"),
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def canonicalize_skill(skill: str) -> str:
    normalized = _normalize(skill).strip()
    for canonical, aliases in SKILL_ALIASES.items():
        if normalized == _normalize(canonical) or any(
            normalized == _normalize(alias) for alias in aliases
        ):
            return canonical
    return " ".join(skill.split())


def extract_skills(text: str) -> list[str]:
    found: list[str] = []
    normalized_text = _normalize(text)
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            normalized_alias = _normalize(alias)
            pattern = rf"(?<!\w){re.escape(normalized_alias)}(?!\w)"
            if re.search(pattern, normalized_text):
                found.append(canonical)
                break
    return found


def normalized_tokens(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        token
        for token in re.findall(r"[a-z0-9+#.]+", normalized)
        if len(token) > 1
    }


def token_overlap(left: str, right: str) -> float:
    left_tokens = normalized_tokens(left)
    right_tokens = normalized_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
