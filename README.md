# Matching RAG

## Démarrage avec Docker Compose

Prérequis : Docker Desktop avec le plugin Docker Compose.

```powershell
docker compose up --build
```

Ouvrir ensuite `http://localhost:5173` (interface), `http://localhost:8000/docs` (API) ou `http://localhost:8000/health`. PostgreSQL n'est plus publié sur l'hôte; les données Chroma, le cache du modèle d'embeddings et l'historique Prometheus sont conservés dans des volumes Docker. Le premier démarrage peut prendre plusieurs minutes : l'API télécharge le modèle d'embeddings.

La route `/metrics` est exposée uniquement sur le réseau Docker Compose et Prometheus la collecte toutes les 15 secondes à partir de `prometheus.yml`. Depuis l’espace administrateur, les liens « Audit Prometheus » ouvrent l’état de la cible API et le graphe des métriques via `/prometheus/`; le reverse-proxy vérifie la session et le rôle administrateur. Les ports PostgreSQL et Prometheus ne sont pas publiés sur l'hôte.

Le matching principal utilise BGE-M3 local et un score déterministe; aucune clé OpenAI n’est nécessaire pour ce parcours. Pour les outils auxiliaires qui utilisent un LLM, définir `OPENAI_API_KEY` dans `.env` avant de lancer Compose. Créer le premier compte administrateur avec :

```powershell
docker compose exec api python -m app.auth.bootstrap_admin
```

Avant le démarrage Compose, renseigner `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` et une longue `AUTH_SECRET_KEY` dans `.env`. Compose exige ces valeurs et ne fournit plus de mot de passe PostgreSQL ni de secret JWT par défaut. Ne pas exposer directement les ports de développement en production.

Arrêter les services avec `docker compose down`. Pour supprimer également les données persistées, utiliser `docker compose down --volumes`.

## Démarrage local

Prérequis : Python 3.13, Node.js 20.19+ et PostgreSQL disponible sur le port 5432.

1. Copier `.env.example` vers `.env`, puis renseigner `DATABASE_URL` avec une URL SQLAlchemy au format `postgresql+psycopg://...`. Encoder les caractères spéciaux du mot de passe dans l’URL. Générer `AUTH_SECRET_KEY` avec la commande indiquée dans le fichier d’exemple.
2. Installer les dépendances Python et lancer l’API :

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

   Au démarrage, l’application crée les tables manquantes avec SQLAlchemy. Pour un déploiement durable, remplacer cette initialisation automatique par des migrations versionnées.

3. Créer le premier compte administrateur dans un terminal configuré avec le même `.env` :

   ```powershell
   .\.venv\Scripts\python.exe -m app.auth.bootstrap_admin
   ```

   Le mot de passe est demandé de façon interactive et n’est pas écrit dans la commande.

4. Copier `frontend/.env.example` vers `frontend/.env.local`, installer et lancer le frontend :

   ```powershell
   npm --prefix frontend install
   npm --prefix frontend run dev
   ```

   Ouvrir l’URL Vite affichée dans le terminal, normalement `http://localhost:5173`.

## Rôles disponibles

- Visiteur : offres publiques et jusqu’à trois analyses anonymes par jour.
- Candidat : CV, consentement de visibilité, recommandations, candidatures et notifications.
- Recruteur : offres, publication, candidatures, recommandations de profils visibles et shortlist.
- Administrateur : comptes et métriques disponibles. Le suivi des biais, la configuration IA interactive et le réentraînement ne sont pas encore implémentés.

Les contrôles d’accès sont appliqués par l’API; le frontend ne constitue pas une frontière de sécurité. Les offres JSON fournies dans le dépôt restent des exemples, alors que les offres créées par les recruteurs et les candidatures sont persistées dans PostgreSQL.

## Pipeline de matching mesurable

1. Le parseur extrait les champs et compétences d’un CV; l’interface montre les données détectées et les avertissements avant enregistrement ou analyse. L’indicateur de complétude décrit les champs trouvés, pas leur exactitude.
2. Les recherches CV→offres et offre→CV combinent classement sémantique BGE-M3, recouvrement lexical et compétences normalisées.
3. Le score final est déterministe et versionné (`hybrid-v1`): couverture des compétences requises (60 %), similarité sémantique (25 %) et recouvrement lexical du texte de profil avec l’offre (15 %). Les composantes indisponibles sont exclues puis les poids restants sont renormalisés. Ce score n’est pas une probabilité d’embauche; les compétences non détectées sont à vérifier, et non réputées absentes.
4. Les recommandations affichent les signaux, les compétences reconnues et les écarts. Le LLM ne calcule pas le score.
5. Le jeu annoté `app/data/evaluation/matching_cases.json` permet de calculer Recall@k, MRR et nDCG@k. Le benchmark synthétique reste séparé de l’évaluation réelle disponible dans l’espace administrateur.

### Ingestion et vérification visuelle des CV

L’ingestion conserve séparément la transcription extraite du CV et le texte synthétisé par Ollama pour le matching. La transcription complète est affichée dans l’écran de vérification; elle n’est ni remplacée par la sortie du LLM ni envoyée avec le profil enregistré. Le parseur extrait le texte et la mise en page (PyMuPDF/pypdf, OCR Tesseract pour les pages PDF avec peu ou pas de texte), en incluant les tableaux DOCX. La sortie structurée d’Ollama sert aux champs du profil, pas à la transcription. Pour les PDF et images, seule la première page originale est envoyée au modèle Vision afin de limiter le temps et la mémoire. Les autres formats pris en charge utilisent le modèle textuel. Les offres d’emploi gardent leur extraction locale actuelle. Pour l’OCR local des documents scannés, installer Tesseract avec les langues française et anglaise; Docker les installe déjà.

Ollama doit être lancé sur la machine hôte avant d’ingérer un CV. Par défaut, Compose le contacte via `http://host.docker.internal:11434`. Pour une machine avec 8 Go de RAM, les valeurs par défaut séparent le modèle Vision `granite3.2-vision:2b` (2,4 Go) du modèle texte `qwen2.5:1.5b` (986 Mo); le contexte est limité à 3 072 tokens, le calcul utilise 8 threads et les modèles sont déchargés après chaque requête pour limiter la mémoire résidente. Seule la première page originale est envoyée au modèle Vision, réduite à 384 pixels; le texte extrait reste complet et visible. Ollama reçoit le schéma JSON de validation et peut générer jusqu’à 768 tokens; les champs absents sont complétés par l’extraction locale du document. Télécharger les deux modèles s’ils ne sont pas déjà installés :

```powershell
ollama pull granite3.2-vision:2b
ollama pull qwen2.5:1.5b
```

Configuration conseillée dans `.env` :

```dotenv
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_VISION_MODEL=granite3.2-vision:2b
OLLAMA_TEXT_MODEL=qwen2.5:1.5b
OLLAMA_NUM_CTX=3072
OLLAMA_NUM_THREAD=8
```

`OLLAMA_VISION_MODEL` est bien le réglage distinct utilisé pour les CV PDF et images; `OLLAMA_TEXT_MODEL` sert aux CV sans image et `OLLAMA_MODEL` aux autres fonctions LLM. Ces réglages, ainsi que `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX` et `OLLAMA_NUM_THREAD`, sont modifiables dans `.env`. Granite Vision 2B est optimisé pour la compréhension de documents et reste plus petit que Gemma 3 4B; sur CPU, il sera néanmoins plus lent qu’une inférence avec GPU. Si Ollama est injoignable, manque de mémoire ou renvoie un JSON non conforme, l’ingestion échoue explicitement; elle ne retourne pas de CV partiellement structuré.

### Évaluation réelle dans l’espace administrateur

Les candidats peuvent donner ou retirer un consentement distinct à l’utilisation de leur profil pour évaluer la pertinence du matching; la visibilité recruteur n’implique pas ce consentement. Les administrateurs voient les profils participants sous pseudonyme et annotent chaque paire avec une échelle de pertinence (« non pertinent », « pertinent », « très pertinent »). Les mesures sont calculées uniquement pour les CV dont toutes les offres publiées ont des annotations à jour. Tout changement du CV ou d’une offre rend les annotations correspondantes obsolètes; un retrait de consentement supprime ses annotations et les rapports agrégés enregistrés.

Le rapport historisé contient uniquement des métriques agrégées et les volumes, jamais le texte source du CV, son nom ou des identifiants de candidat. Les CV sans aucune annotation positive sont signalés et exclus des métriques de classement. Un échantillon de moins de 30 profils porte un avertissement de faible volume; ce seuil est un repère de prudence, pas une garantie statistique. Les annotations historiques sont des jugements de pertinence, pas des décisions d’embauche. Les tables nécessaires sont créées au démarrage via `create_all`; déployez les changements de schéma selon le processus de migration de votre environnement de production.

Lancer ou relancer le benchmark depuis la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe -m app.evaluation
```

Le benchmark inclus est constitué d’exemples synthétiques : il valide le fonctionnement du pipeline, mais ne mesure pas sa qualité sur une population de recrutement réelle. Pour une évaluation métier, fournissez dans le JSON des listes `cvs` et `jobs` (objets conformes aux modèles de l’API) et des cas `cv_id` / `relevant_job_ids` avec des jugements pertinents annotés et représentatifs. Gardez ce fichier local et protégé s’il contient des données personnelles, et gardez un jeu de test indépendant des données servant à régler les poids.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_ingestion.py tests/test_integration.py tests/test_matching_pipeline.py tests/test_matching.py -q
npm --prefix frontend run build
npm --prefix frontend audit
```
