# RelayDesk

RelayDesk is a voice-AI operations platform: a **LiveKit voice agent** handles phone calls, a **RAG REST API** stores and searches knowledge bases, and a **Next.js console** lets operators manage consumers, documents, and outbound campaigns.

> **Shell:** Command examples use **bash** (macOS, Linux, or **Git Bash** on Windows).

## Components at a glance

| Component | Path | One-line summary |
|-----------|------|------------------|
| **API** | [`api/`](api/) | FastAPI service — RAG (Qdrant), PostgreSQL consumers/call jobs, Cognito JWT auth |
| **UI** | [`ui/`](ui/) | Next.js operations console — SSO login, knowledge upload, search, call jobs |
| **Voice agent** | [`voice-agent/`](voice-agent/) | LiveKit agent — STT/LLM/TTS, Cal.com scheduling, RAG search on every turn |
| **Infrastructure** | [`infra/`](infra/) | Terraform — VPC, ECS on EC2, ALB, Cognito, RDS, ECR, SSM secrets |

## How it fits together

```
Browser ──► UI (Next.js :3000) ──► API (:8090) ──► Qdrant Cloud + AWS RDS
                                         ▲
Voice agent (LiveKit) ──M2M OAuth────────┘
     │
     └──► LiveKit Cloud, Deepgram, Cartesia, xAI, Cal.com
```

- **UI users** sign in with Cognito SSO and access data scoped by `client_email_id`.
- **Voice agent** uses Cognito **machine-to-machine** tokens to call RAG APIs without email scoping.
- **Admins** (`relaydesk-admins`) see all tenants; **guests** and **approved clients** are scoped to their email.

## Documentation map

| Topic | Read |
|-------|------|
| API — local run, env vars, RAG/consumer APIs, scripts | [`api/README.md`](api/README.md) |
| UI — Cognito/NextAuth, local dev, Docker/ECR deploy | [`ui/README.md`](ui/README.md) |
| Voice agent — LiveKit, phone configs, RAG client | [`voice-agent/README.md`](voice-agent/README.md) |
| AWS — Terraform bootstrap, SSM, ECS, Cognito roles, ops scripts | [`infra/README.md`](infra/README.md) |
| **New AWS account — full setup from scratch** | [`infra/NEW_INFRA_SETUP.md`](infra/NEW_INFRA_SETUP.md) |
| LiveKit agent development | [`AGENTS.md`](AGENTS.md) |

## Quick start (local UI + API)

Local development uses **Docker Postgres** and **Qdrant Cloud**. Production still uses AWS RDS.

### 1. Local Postgres

```powershell
cd api
docker compose -f docker-compose.postgres.yml up -d
```

### 2. API

```powershell
cd api
cp .env.example .env   # set OPENAI_API_KEY, QDRANT_CLUSTER_ENDPOINT, QDRANT_API_KEY, OAUTH_DISABLED=true
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Swagger: http://127.0.0.1:8090/docs

### 3. UI

```powershell
cd ui
cp .env.example .env   # set AUTH_DISABLE_SSO=true, AUTH_SECRET, AUTH_URL=http://localhost:3000
npm install
npm run dev
```

Open http://localhost:3000 → **Continue in local mode**.

### 4. Voice agent (optional)

```bash
cd voice-agent
cp .env.example .env
uv sync
uv run python src/agent.py download-files
uv run python src/agent.py console
```

Set `RAG_API_BASE_URL=http://127.0.0.1:8090` in `voice-agent/.env`.

## Repository layout

```
telephone-agent/
├── api/              # FastAPI RAG + consumer + call-job API
├── ui/               # Next.js operations console
├── voice-agent/      # LiveKit voice agent
├── infra/            # Terraform + operational scripts
├── README.md         # This file
└── AGENTS.md         # LiveKit agent dev guide
```

## AWS deployment (summary)

Production runs on **ECS on EC2** in `ap-south-1` (configurable):

| ECS service | Image | Port |
|-------------|-------|------|
| `relaydesk-prod-api` | `api/Dockerfile` | 8090 |
| `relaydesk-prod-ui` | `ui/Dockerfile` | 3000 |
| `relaydesk-prod-voice-agent` | `voice-agent/Dockerfile` | — |

**Full bootstrap, secrets, domain, and troubleshooting:** [`infra/README.md`](infra/README.md)

**Setting up in a new AWS account:** [`infra/NEW_INFRA_SETUP.md`](infra/NEW_INFRA_SETUP.md)

**Typical manual image push** (from repo root):

```bash
export PROFILE_NAME="relaydesk-admin"
export AWS_REGION="ap-south-1"
export IMAGE_TAG="latest"

cd infra/terraform
export ACCOUNT_ID="$(terraform output -raw aws_account_id)"
export ECR_API="$(terraform output -raw ecr_api_repository_url)"
export ECR_UI="$(terraform output -raw ecr_ui_repository_url)"
export ECR_VOICE="$(terraform output -raw ecr_voice_agent_repository_url)"
cd ../..

aws ecr get-login-password --profile "$PROFILE_NAME" --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build must succeed before push (verify npm run build / docker build output)
docker build -t "${ECR_API}:${IMAGE_TAG}" ./api && docker push "${ECR_API}:${IMAGE_TAG}"
docker build -t "${ECR_UI}:${IMAGE_TAG}" ./ui   && docker push "${ECR_UI}:${IMAGE_TAG}"
docker build -t "${ECR_VOICE}:${IMAGE_TAG}" ./voice-agent && docker push "${ECR_VOICE}:${IMAGE_TAG}"
```

Force ECS to pull new images:

```bash
for SVC in relaydesk-prod-api relaydesk-prod-ui relaydesk-prod-voice-agent; do
  aws ecs update-service --cluster relaydesk-prod --service "$SVC" \
    --force-new-deployment --profile "$PROFILE_NAME" --region "$AWS_REGION"
done
```

Or push to `main` and let **GitHub Actions** deploy (see [`infra/README.md`](infra/README.md)).

## Tests

```bash
cd api && uv run pytest
cd voice-agent && uv run pytest
```

## User roles (Cognito)

| Group | Access |
|-------|--------|
| `guest-clients` | Auto-assigned on SSO sign-up — read-only |
| `approved-clients` | Upload/delete knowledge-base documents |
| `relaydesk-admins` | Full console and API access |

Promote users: `python infra/scripts/approve_cognito_user.py --email user@example.com --role relaydesk-admins`
