# RelayDesk Voice Agent

LiveKit voice agent for inbound/outbound phone calls. Runs an STT → LLM → TTS pipeline, books meetings via Cal.com, and searches the RAG API on every user turn for document-grounded answers.

[← Back to monorepo](../README.md) · **API:** [`../api/README.md`](../api/README.md) · **Infrastructure:** [`../infra/README.md`](../infra/README.md)

---

## 1. Description

### What it does

- Connects to **LiveKit Cloud** for real-time audio rooms and SIP telephony.
- Uses **Sarvam Saaras v3** + **Google Gemini 3.6 Flash** + **Sarvam Bulbul v3** by default (`VOICE_PROVIDER=sarvam`) for Hindi, English, and other supported Indian languages.
- Loads per-client config from the **RelayDesk API** (`GET /v1/voice-agent-config/resolve-by-phone`) at call start.
- Calls the **RAG API** (`POST /v1/search`) with Cognito M2M OAuth in production.
- Optional **Cal.com** tools for meeting scheduling.

### Project structure

```
voice-agent/
├── src/
│   ├── agent.py              # Entry point
│   ├── agent_instructions.py
│   ├── client_config.py      # Runtime API config loader
│   ├── voice_agent_config_client.py
│   ├── scheduling_tools.py   # Cal.com integration
│   └── rag_client/           # HTTP client for RAG API
├── scripts/                  # Cal.com debug utilities
├── tests/
├── Dockerfile
└── livekit.toml              # LiveKit Cloud agent config
```

---

## 2. Run locally

### Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- RelayDesk API running (see [`../api/README.md`](../api/README.md))
- LiveKit Cloud project credentials

### Configure environment

```bash
cd voice-agent
uv sync
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `LIVEKIT_URL` | Yes | `wss://<project>.livekit.cloud` |
| `LIVEKIT_API_KEY` | Yes | LiveKit API key |
| `LIVEKIT_API_SECRET` | Yes | LiveKit API secret |
| `VOICE_PROVIDER` | No | `sarvam` (default) or `legacy` |
| `SARVAM_API_KEY` | Sarvam | Required when `VOICE_PROVIDER=sarvam` |
| `GOOGLE_API_KEY` | Gemini | Required for direct Gemini billing when `VOICE_PROVIDER=sarvam` |
| `SARVAM_STT_MODEL` | No | Default `saaras:v3` |
| `SARVAM_STT_LANGUAGE` | No | Fallback default `hi-IN`; per-client config can override this |
| `GEMINI_LLM_MODEL` | No | Default `gemini-3.6-flash` via the LiveKit Google plugin |
| `SARVAM_TTS_MODEL` | No | Default `bulbul:v3` |
| `SARVAM_TTS_LANGUAGE` | No | Fallback default `hi-IN`; per-client config can override this |
| `SARVAM_TTS_SPEAKER` | No | Default `shubh` |
| `ASSEMBLYAI_API_KEY` | Legacy | Required when `VOICE_PROVIDER=legacy` (default) |
| `STT_MODEL` | No | Default `universal-3-5-pro` (Universal-3.5-Pro Realtime) |
| `DEEPSEEK_API_KEY` | Legacy | Required when `VOICE_PROVIDER=legacy` (default) |
| `LLM_MODEL` | No | Default `deepseek-v4-flash` (off-peak pricing is automatic) |
| `DEEPGRAM_API_KEY` | Legacy | Required when `VOICE_PROVIDER=legacy` (default) |
| `DEEPGRAM_TTS_MODEL` | No | Default `aura-asteria-en` (Aura-1) |
| `CALCOM_API_KEY` | Scheduling | Cal.com API key |
| `AGENT_NAME` | Yes | Must match LiveKit agent registration |
| `CLIENT_PHONE_OVERRIDE` | Local | e.g. `+911171366880` — simulates caller phone |
| `RAG_BACKEND` | RAG | Must be `qdrant` (RelayDesk RAG API) |
| `RAG_API_BASE_URL` | Yes | `http://127.0.0.1:8090` locally |
| `COGNITO_TOKEN_URL` | Production | Cognito OAuth token endpoint |
| `COGNITO_CLIENT_ID` | Production | M2M client ID |
| `COGNITO_CLIENT_SECRET` | Production | M2M client secret |
| `COGNITO_SCOPE` | Production | `relaydesk-api/access` |

**Local dev auth:** When calling the API at `http://127.0.0.1:8090`, either:

1. **Production-like OAuth (default):** Set `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`, and `COGNITO_TOKEN_URL` in `.env`. If Cognito returns `invalid_client`, refresh the M2M secret:
   ```bash
   python infra/scripts/patch_voice_cognito_secret.py --from-cognito-api --profile relaydesk-admin
   ```
2. **Skip OAuth:** Set `OAUTH_DISABLED=true` in `api/.env` and remove or comment out `COGNITO_*` in `voice-agent/.env`.

Also ensure the local API is running before `uv run python src/agent.py console`.

### Voice agent configuration

Per-client settings (conversation language, greeting with service offerings, Cal.com) live in Postgres and are edited in the RelayDesk UI under **Voice agent**, or via the API. When callers ask questions, the agent searches uploaded documents automatically.

- `GET /v1/voice-agent-config?client_email_id=...` — read settings (UI)
- `PUT /v1/voice-agent-config?client_email_id=...` — update settings (UI)
- `GET /v1/voice-agent-config/resolve-by-phone?phone_number=...` — M2M, used by the voice agent at runtime

Ensure each approved client has a business phone number in Postgres so inbound calls resolve correctly.

### Run

Start the API first, then:

```bash
# Download plugin models (first time)
uv run python src/agent.py download-files

# Local microphone/speaker test
uv run python src/agent.py console
```

**Console mic not working?** On some Windows laptops the default PortAudio path captures silence even when the mic works in the browser (LiveKit Playground). Console mode now opens the **WASAPI** device in exclusive mode at native rate, resamples to 24 kHz mono, and disables console echo cancellation. If the level meter stays flat:

1. **Close LiveKit Playground** while using console — exclusive mode cannot share the mic.
2. **Windows mic:** Settings → Privacy → Microphone → allow desktop apps; set the correct **default input device** in Sound settings.
3. **Watch the level meter** in the console UI — bars should move when you speak.
4. Pick a device explicitly: `uv run python src/agent.py console --input-device "Microphone Array"`.
5. Disable the WASAPI fix to use the old path: `DISABLE_CONSOLE_WASAPI=true` in `.env`.

**Voice breaking / choppy audio?** Console logs showed the mic picking up the agent's own speech (echo), which triggered overlapping replies and TTS buffer flushes. The agent now filters echo transcripts (`AGENT_ECHO_FILTER_ENABLED=true` by default), requires 3+ words to interrupt the agent, and no longer blocks the LLM while a RAG filler phrase finishes playing.

```bash
# Connect to LiveKit Cloud (dev)
uv run python src/agent.py dev
```

### Deploy to LiveKit Cloud

```bash
lk agent create    # first time
lk agent deploy    # updates
```

---

## 3. Docker build, push to ECR, update ECS

Run from **repo root**.

```bash
export PROFILE_NAME="relaydesk-admin"
export AWS_REGION="ap-south-1"
export IMAGE_TAG="latest"    # match voice_ecr_image_tag in terraform.tfvars

cd infra/terraform
export ACCOUNT_ID="$(terraform output -raw aws_account_id)"
export ECR_VOICE="$(terraform output -raw ecr_voice_agent_repository_url)"
export CLUSTER="$(terraform output -raw ecs_cluster_name)"
export SERVICE="$(terraform output -raw ecs_service_voice_agent_name)"
cd ../..

aws ecr get-login-password --profile "$PROFILE_NAME" --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build -t relaydesk-voice:latest ./voice-agent
docker tag relaydesk-voice:latest "${ECR_VOICE}:${IMAGE_TAG}"
docker tag relaydesk-voice:latest "${ECR_VOICE}:latest"
docker push "${ECR_VOICE}:${IMAGE_TAG}"
docker push "${ECR_VOICE}:latest"

aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE" \
  --force-new-deployment \
  --profile "$PROFILE_NAME" \
  --region "$AWS_REGION"
```

In ECS, `RAG_API_BASE_URL` is set to `http://api.relaydesk.local:8090` (Cloud Map). Secrets come from SSM `/relaydesk/prod/voice-agent/*`.

---

## 4. Scripts

Run from `voice-agent/` unless noted.

| Script | Purpose | Usage |
|--------|---------|--------|
| `src/agent.py download-files` | Pre-download LiveKit plugin models | `uv run python src/agent.py download-files` |
| `src/agent.py console` | Local audio test (no telephony) | `uv run python src/agent.py console` |
| `src/agent.py dev` | Dev mode against LiveKit Cloud | `uv run python src/agent.py dev` |
| `src/agent.py start` | Production worker (used in Docker/ECS) | `uv run python src/agent.py start` |

### Infra scripts (voice-agent secrets)

| Script | Purpose |
|--------|---------|
| [`../infra/scripts/sync_ssm_parameters.py`](../infra/scripts/sync_ssm_parameters.py) | Sync `voice-agent/.env` → SSM (`--only KEY` for one parameter) |
| [`../infra/scripts/patch_voice_cognito_secret.py`](../infra/scripts/patch_voice_cognito_secret.py) | Fix local `COGNITO_CLIENT_SECRET` from Cognito API |

---

## Tests

```bash
uv run pytest
uv run ruff check src tests
```

See [`../AGENTS.md`](../AGENTS.md) for LiveKit agent development guidelines.
