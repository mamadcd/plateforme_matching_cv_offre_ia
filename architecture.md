# Flux complet du matching

```mermaid
flowchart TD
    UI[Frontend React / Nginx] --> AUTH[Authentification JWT<br/>candidat, recruteur, administrateur]
    AUTH --> DB[(SQLite)]

    subgraph INGESTION[Ingestion des documents]
        DOC[CV ou offre PDF, image, DOCX, texte] --> EXTRACT[Extraction du texte<br/>pypdf, OCR, DOCX]
        EXTRACT --> STRUCT[Structuration Pydantic<br/>CandidateCV ou JobPosting]
        STRUCT --> SKILLS[Référentiel des compétences<br/>normalisation et extraction]
    end

    UI --> INGESTION

    subgraph CANDIDAT[Flux candidat]
        PROFILE[Profil candidat] --> CV[CandidateCV]
        CONSENT{Recherche activée ?}
        PROFILE --> CONSENT
        CONSENT -->|Oui| CV_INDEX[(Chroma collection cvs)]
        CONSENT -->|Non| REMOVE[Retrait de l'index Chroma]
        CV --> HYBRID_CV
    end

    subgraph RECRUTEUR[Flux recruteur]
        JOB_CREATE[Création ou publication d'une offre] --> JOB[JobPosting]
        JOB --> HYBRID_JOB
    end

    subgraph RETRIEVAL[Recherche hybride]
        JOBS[Offres exemples + offres publiées] --> JOB_INDEX[(Chroma collection jobs)]
        CV --> HYBRID_CV[Construction des textes CV / offres]
        JOB_INDEX --> SEM_J[Similarité sémantique<br/>BAAI/bge-m3]
        HYBRID_CV --> SEM_J
        HYBRID_CV --> LEX_J[Similarité lexicale]
        HYBRID_CV --> SKILL_J[Recouvrement des compétences]
        SEM_J --> RRF_J[Fusion hybride par rangs]
        LEX_J --> RRF_J
        SKILL_J --> RRF_J
        RRF_J --> TOP_J[Top offres pour le candidat]

        JOB --> HYBRID_JOB[Construction des textes offre / CV]
        CV_INDEX --> SEM_C[Similarité sémantique<br/>BAAI/bge-m3]
        HYBRID_JOB --> SEM_C
        HYBRID_JOB --> LEX_C[Similarité lexicale]
        HYBRID_JOB --> SKILL_C[Recouvrement des compétences]
        SEM_C --> RRF_C[Fusion hybride par rangs]
        LEX_C --> RRF_C
        SKILL_C --> RRF_C
        RRF_C --> TOP_C[Top CV visibles pour le recruteur]
    end

    subgraph ANALYSE[Analyse explicable]
        TOP_J --> SCORE_J[Calcul hybride-v1]
        TOP_C --> SCORE_C[Calcul hybride-v1]
        SCORE_J --> WEIGHTS_J[60 % compétences + 25 % sémantique + 15 % texte]
        SCORE_C --> WEIGHTS_C[60 % compétences + 25 % sémantique + 15 % texte]
        WEIGHTS_J --> RESULT_J[Score, forces, lacunes, compétences]
        WEIGHTS_C --> RESULT_C[Score, forces, lacunes, compétences]
    end

    CV --> TOP_J
    JOB --> TOP_C
    RESULT_J --> API_J[API candidat / recommandations]
    RESULT_C --> API_C[API recruteur / candidats]

    API_J --> POSTULE[Postuler à une offre]
    POSTULE --> DB
    API_C --> SHORTLIST[Shortlist]
    SHORTLIST --> DB

    LEGACY_ACTIVE[/match /match/parsed-cv /match/anonymous] -. compatibilité active .-> RETRIEVAL
    LEGACY_OFF[/match/job /match/parsed-job] -. réponses HTTP 410 .-> LEGACY404[Utilisez une offre publiée<br/>dont vous êtes propriétaire]

    AGENT[LangGraph optionnel] -. orchestre les outils .-> RETRIEVAL
    AGENT -. peut appeler l'analyse LLM .-> RESULT_J

    OBS[Prometheus /metrics] -. métriques HTTP .-> UI
    OBS -. collecte .-> AUTH
```

## Légende

- `BAAI/bge-m3` produit les embeddings utilisés par les collections Chroma `jobs` et `cvs`.
- La récupération combine trois signaux : similarité sémantique, similarité lexicale et recouvrement des compétences.
- Le score exposé est déterministe (`hybrid-v1`) : 60 % couverture des compétences, 25 % similarité sémantique et 15 % recouvrement textuel.
- Les outils LLM restent disponibles pour des analyses de texte, mais le score principal n'est pas une prédiction générée par le LLM.
- Les profils recruteurs peuvent seulement être visibles si le candidat active explicitement `searchable`.
- Les routes `/match/job` et `/match/parsed-job` sont désactivées : le recruteur utilise une offre publiée détenue par son compte.
