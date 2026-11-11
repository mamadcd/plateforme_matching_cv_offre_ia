# Matching RAG

## Démarrage avec Docker Compose

Prérequis : Docker Desktop avec le plugin Docker Compose.

```powershell
docker compose up --build
```

Ouvrir ensuite `http://localhost:5173` (interface), `http://localhost:8000/docs` (API) ou `http://localhost:8000/health`. PostgreSQL, les données Chroma et le cache du modèle d'embeddings sont conservés dans des volumes Docker. Le premier démarrage peut prendre plusieurs minutes : l'API télécharge le modèle d'embeddings.

Sans clé OpenAI, l'application démarre avec son fallback local. Pour activer OpenAI, définir `OPENAI_API_KEY` dans `.env` avant de lancer Compose. Créer le premier compte administrateur avec :

```powershell
docker compose exec api python -m app.auth.bootstrap_admin
```

La clé secrète et les identifiants PostgreSQL par défaut sont réservés au développement local. Les remplacer avant tout déploiement; ne pas exposer directement les ports de développement en production.

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

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_ingestion.py -q
npm --prefix frontend run build
npm --prefix frontend audit
```
