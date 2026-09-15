# Flux complet du matching

```mermaid
flowchart TD
	A[CV texte reçu par POST /match] --> B[Création du CandidateCV]
	B --> B1[Extraction rudimentaire des compétences<br/>tokens de plus de 3 caractères]
	B1 --> C[Chargement des offres JSON]

	C --> D[Construction du texte des offres]
	D --> E[Embedding des offres avec BAAI/bge-m3]
	E --> F[Indexation persistante dans Chroma]

	B1 --> G[Construction du texte du CV]
	G --> H[Embedding du CV avec BAAI/bge-m3]
	H --> I[Recherche vectorielle dans Chroma]
	I --> J[Classement par proximité sémantique]
	J --> K[Offres les plus proches]

	K --> L[Offres récupérées]
	L --> M{LLM disponible}

	M -->|Oui| N[Prompt CV + offres vers le LLM<br/>Gemma/Ollama ou OpenAI selon configuration]
	N --> O[Parsing du JSON d'analyse]
	M -->|Non ou erreur| P[Fallback local]
	P --> P1[Intersection compétences<br/>score, forces et lacunes]

	O --> Q[MatchAnalysis par offre]
	P1 --> Q
	Q --> R[Assemblage des résultats]
	R --> S[Réponse JSON /match<br/>score, explication, strengths, gaps]

	V[Offre reçue par POST /match/job] --> W[Chargement ou construction du JobPosting]
	W --> X[Embedding de l'offre avec BAAI/bge-m3]
	Y[CV disponibles] --> Z[Embedding des CV avec BAAI/bge-m3]
	Z --> AA[Indexation dans la collection Chroma cvs]
	X --> AB[Recherche vectorielle des CV similaires]
	AA --> AB
	AB --> AC[Top CV candidats]
	AC --> AD[Analyse Offre vers CV<br/>compétences, expérience, mobilité]
	AD --> AE[Réponse JSON /match/job<br/>score, explication, strengths, gaps]

	S -. peut être comparé à .-> AE

	T[LangGraph agent] -. orchestre .-> U[AgentState messages]
	U -. appels d'outils .-> D
	U -. appelle éventuellement .-> N
```

## Légende

    - Le chemin principal de `/match` utilise BAAI/bge-m3 pour encoder le CV et les offres.
    - Les offres sont indexées dans Chroma avant chaque recherche et persistées dans `chroma_db`.
    - La récupération ne possède plus de fallback lexical : elle dépend de la recherche vectorielle Chroma.
    - Le chemin inverse `/match/job` indexe les CV dans une collection Chroma distincte et récupère les profils les plus proches.
    - Les deux directions utilisent le même modèle BAAI/bge-m3, puis une analyse explique les forces et les écarts.

- L'analyse finale utilise le LLM configuré, avec un fallback local basé sur les compétences explicites.
