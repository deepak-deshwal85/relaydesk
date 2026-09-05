# RelayDesk API

FastAPI service providing **RAG** (Qdrant vector search, document ingest), **consumer management** (PostgreSQL), **outbound call jobs** (LiveKit SIP), and **client profiles**. All routes except `/health` require a Cognito JWT unless `OAUTH_DISABLED=true`.

[← Back to monorepo](../README.md) · **Infrastructure:** [`../infra/README.md`](../infra/README.md)

---

## 1. Description

### What it does

- **RAG:** Upload PDF/text/markdown per phone collection (`phone_<digits>`), embed with OpenAI, search via Qdrant Cloud.
- **Consumers:** CRUD for client/consumer records scoped by `client_email_id`.
- **Call jobs:** Async outbound dialing of all consumers for a client phone number.
- **Clients:** Profile setup (name, phone, email) after SSO; links Cognito `sub` to tenant.
- **Auth:** Validates Cognito access tokens; UI users are email-scoped; M2M voice-agent tokens bypass tenant checks.

### Architecture

```
src/app/
  routers/     HTTP routes (Swagger at /docs)
  services/    Business logic
  db/          PostgreSQL (RDS), Qdrant Cloud, embedding providers
  schemas/     Pydantic request/response models
  domain/      Internal dataclasses
  core/        Settings, OAuth, RBAC, tenant scoping
```

### Key API groups

| Prefix | Purpose |
|--------|---------|
| `/health` | Liveness (no auth) |
| `/v1/collections`, `/v1/search` | RAG — collections, documents, semantic search |
| `/v1/consumers` | Consumer CRUD + approve |
| `/v1/call-jobs` | Trigger and poll outbound campaigns |
| `/v1/clients` | Client profile (`/me`, `/profile`) |
| `/v1/embeddings` | Embedding cache (admin) |

---

## 2. Run locally

Local development uses **Docker PostgreSQL** and **Qdrant Cloud**. Production continues to use AWS RDS.

### Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Qdrant Cloud cluster + API key
- OpenAI API key (embeddings)

### Configure environment

```bash
cd api
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (RAG) | OpenAI embeddings |
| `DATABASE_URL` | Yes | Local Postgres: `postgresql+asyncpg://relaydesk:relaydesk@127.0.0.1:5434/relaydesk` |
| `QDRANT_CLUSTER_ENDPOINT` | Yes | Qdrant Cloud HTTPS endpoint |
| `QDRANT_API_KEY` | Yes | Qdrant Cloud API key |
| `QDRANT_CLUSTER_NAME` | Optional | Cluster label (error messages) |
| `OAUTH_DISABLED` | Local dev | `true` — skip JWT validation |
| `COGNITO_*` | Production / SSO | User pool and client IDs |
| `LIVEKIT_*` | Call jobs | Real outbound SIP calls |
| `CORS_ORIGINS` | Optional | e.g. `http://localhost:3000` |

### Start (Windows)

**Terminal 1 — Postgres**:

```powershell
cd api
docker compose -f docker-compose.postgres.yml up -d
```

**Terminal 2 — API**:

```powershell
cd api
cp .env.example .env
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
```

### Initialize database (first time / fresh local Postgres)

The API **does not** create tables on startup. After the Docker Postgres container is healthy and `DATABASE_URL` is configured, bootstrap once (destructive — drops all tables, recreates schema, loads Deepak seed data):

```powershell
cd api
uv run python ../infra/scripts/bootstrap_db.py --yes
```

Seed includes two Deepak clients (`deepakdeshwal85@gmail.com`, `deepakdeshwal85@yahoo.com`), voice agent configs, consumers, call jobs, and call summaries.

### Start (Git Bash / macOS / Linux)

```bash
# Terminal 1
cd api
docker compose -f docker-compose.postgres.yml up -d

# Terminal 2
cd api && cp .env.example .env
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
```

- Swagger: http://127.0.0.1:8090/docs
- Health: http://127.0.0.1:8090/health

### Upload a test document

Use the **Knowledge** page in the UI, or Swagger `POST /v1/collections/{collection}/documents/upload`.

---

## 3. Deploy to ECS

From repo root:

```bash
python infra/scripts/deploy_api.py
python infra/scripts/deploy_api.py --dry-run
python infra/scripts/deploy_api.py --safe
```

Manual Docker/ECR steps (if you prefer):

```bash
export PROFILE_NAME="relaydesk-admin"
export AWS_REGION="ap-south-1"
export IMAGE_TAG="latest"    # match api_ecr_image_tag in terraform.tfvars

cd infra/terraform
export ACCOUNT_ID="$(terraform output -raw aws_account_id)"
export ECR_API="$(terraform output -raw ecr_api_repository_url)"
export CLUSTER="$(terraform output -raw ecs_cluster_name)"
export SERVICE="$(terraform output -raw ecs_service_api_name)"
cd ../..

aws ecr get-login-password --profile "$PROFILE_NAME" --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build -t relaydesk-api:latest ./api
docker tag relaydesk-api:latest "${ECR_API}:${IMAGE_TAG}"
docker tag relaydesk-api:latest "${ECR_API}:latest"
docker push "${ECR_API}:${IMAGE_TAG}"
docker push "${ECR_API}:latest"

aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE" \
  --force-new-deployment \
  --profile "$PROFILE_NAME" \
  --region "$AWS_REGION"
```

After deploy, tail logs:

```bash
aws logs tail /ecs/relaydesk-prod/api --since 10m --follow \
  --region "$AWS_REGION" --profile "$PROFILE_NAME"
```

**Secrets:** API reads from SSM Parameter Store (`/relaydesk/prod/api/*`). Sync with [`../infra/scripts/sync_ssm_parameters.py`](../infra/scripts/sync_ssm_parameters.py). See [`../infra/README.md`](../infra/README.md).

---

## 4. Infra scripts

Database bootstrap and deployment scripts live under [`../infra/scripts/`](../infra/scripts/).

| Script | Purpose |
|--------|---------|
| [`../infra/scripts/bootstrap_db.py`](../infra/scripts/bootstrap_db.py) | Drop, recreate, and seed PostgreSQL |
| [`docker-compose.postgres.yml`](docker-compose.postgres.yml) | Local PostgreSQL container for development |
| [`../infra/scripts/deploy_api.py`](../infra/scripts/deploy_api.py) | Build, push, and deploy API to ECS |
| [`../infra/scripts/sync_ssm_parameters.py`](../infra/scripts/sync_ssm_parameters.py) | Sync secrets to SSM |

Document upload, search, and collection management are available via the UI and Swagger (`/docs`).

---

## Tests

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```
