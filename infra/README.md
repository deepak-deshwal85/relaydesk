# RelayDesk Infrastructure

AWS infrastructure for RelayDesk: **VPC**, **ECS on EC2**, **ALB**, **Cognito**, **RDS PostgreSQL**, **ECR**, **SSM Parameter Store**, and operational scripts.

[← Back to monorepo](../README.md) · **New AWS account setup:** [`NEW_INFRA_SETUP.md`](NEW_INFRA_SETUP.md) · **API deploy:** [`../api/README.md`](../api/README.md) · **UI deploy:** [`../ui/README.md`](../ui/README.md) · **Voice agent deploy:** [`../voice-agent/README.md`](../voice-agent/README.md)

> **Shell:** All commands use **bash** (macOS, Linux, or **Git Bash** on Windows).

---

## Quick reference

| ECS service | Image | Port |
|-------------|-------|------|
| `relaydesk-prod-api` | [`api/Dockerfile`](../api/Dockerfile) | 8090 |
| `relaydesk-prod-ui` | [`ui/Dockerfile`](../ui/Dockerfile) | 3000 |
| `relaydesk-prod-voice-agent` | [`voice-agent/Dockerfile`](../voice-agent/Dockerfile) | — |

Terraform: [`terraform/`](terraform/) · CI/CD: [`.github/workflows/deploy-ecs.yml`](../.github/workflows/deploy-ecs.yml)

**Bootstrap:**

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform apply
python ../scripts/sync_ssm_parameters.py --profile relaydesk-admin --region ap-south-1
```

**Deploy one service (example — API):**

```bash
export PROFILE_NAME="relaydesk-admin" AWS_REGION="ap-south-1" IMAGE_TAG="latest"
cd infra/terraform
export ECR_API="$(terraform output -raw ecr_api_repository_url)"
cd ../..
docker build -t "${ECR_API}:latest" ./api && docker push "${ECR_API}:latest"
aws ecs update-service --cluster relaydesk-prod --service relaydesk-prod-api \
  --force-new-deployment --profile "$PROFILE_NAME" --region "$AWS_REGION"
```

Sections below cover architecture, secrets, Cloudflare DNS, Cognito roles, automation scripts (`rebuild_infra.py`, `cost_control.py`), and troubleshooting in full.

---

## 1. Overview

### What Terraform provisions

| Resource | Purpose |
|----------|---------|
| **VPC** | Private subnets + NAT gateway for outbound internet |
| **ECS cluster** | `relaydesk-prod` — API, UI, voice-agent services |
| **EC2 Auto Scaling** | Separate ASGs for API (`t3.small`) and voice (`t3.large`) |
| **ALB** | HTTPS termination, routes to UI (`:3000`) and API (`:8090`) |
| **ACM** | TLS certificate for custom domain |
| **Cognito** | User pool, UI client, M2M client, role groups, post-confirmation Lambda |
| **RDS** | PostgreSQL for consumers, clients, call jobs |
| **ECR** | Container registries for api, ui, voice-agent |
| **Cloud Map** | `api.relaydesk.local` — internal API DNS for voice agent |
| **SSM** | Secure parameters for all app secrets |
| **CloudWatch** | ECS logs, billing dashboard, monthly budget |
| **IAM** | Task roles, instance profiles, GitHub Actions OIDC role |

### Architecture

```
Internet ──► ALB (HTTPS) ──► UI task (:3000)
                    │
                    ├──► API task (:8090) ──► Qdrant Cloud + RDS
                    │
Voice agent task ───┘  RAG_API_BASE_URL=http://api.relaydesk.local:8090
     │
     └──► LiveKit Cloud, Deepgram, Cartesia, xAI (outbound via NAT)
```

### Why separate containers

| | Separate (deployed) | Single container |
|---|---------------------|------------------|
| Scaling | API and voice scale independently | Both scale together |
| Memory | API ~512 MiB; voice ~8 GiB | One task needs 10+ GiB |
| Deploys | Update API without killing calls | API change restarts agent |
| Security | API behind ALB; agent outbound-only | Larger blast radius |

### Terraform layout

```
infra/
├── README.md                 # This file
├── scripts/                  # Operational Python/shell scripts
└── terraform/
    ├── vpc.tf
    ├── ecs.tf
    ├── alb.tf
    ├── cognito.tf
    ├── cognito_lambda.tf
    ├── rds.tf
    ├── ecr.tf
    ├── ssm.tf
    ├── service_discovery.tf
    ├── iam.tf
    ├── cloudwatch.tf
    ├── variables.tf
    ├── outputs.tf
    └── terraform.tfvars.example
```

---

## 2. Prerequisites

1. **Do not use the AWS root user.** Create an IAM admin user or use IAM Identity Center.
2. AWS CLI configured: `aws configure --profile relaydesk-admin`
3. Terraform >= 1.5
4. Docker (for manual image builds)
5. GitHub repository with Actions enabled (optional CI/CD)

---

## 3. Bootstrap (one-time)

> **New AWS account?** Follow the full checklist in [`NEW_INFRA_SETUP.md`](NEW_INFRA_SETUP.md) (Phases 0–10). This section is a shorter reference for an account that is already configured.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit — no secrets in git

# Optional: remote state
# cp backend.tf.example backend.tf

terraform init
terraform plan
terraform apply
```

### Key `terraform.tfvars` properties

| Variable | Description |
|----------|-------------|
| `aws_region` | Default `ap-south-1` (Mumbai) |
| `project_name` / `environment` | Resource naming prefix |
| `ui_domain_name` | e.g. `relaydesk.uk` — enables ACM + HTTPS |
| `api_ecs_instance_type` | API host, default `t3.small` |
| `voice_ecs_instance_type` | Voice host, default `t3.large` |
| `voice_agent_desired_count` | Set `0` to save cost (Free Tier) |
| `enable_cognito` | Cognito user pool + clients |
| `enable_cognito_google` | Google SSO (requires SSM Google credentials first) |
| `enable_cost_monitoring` | Billing dashboard + budget alerts |
| `monthly_budget_usd` | Budget threshold |
| `api_ecr_image_tag` / `ui_ecr_image_tag` / `voice_ecr_image_tag` | ECS image tags, usually `latest` |

### Useful outputs

```bash
terraform output aws_account_id
terraform output ecs_cluster_name
terraform output ecr_api_repository_url
terraform output ecr_ui_repository_url
terraform output ecr_voice_agent_repository_url
terraform output cognito_user_pool_id
terraform output cognito_callback_urls
terraform output alb_dns_name
terraform output rds_endpoint
terraform output github_actions_role_arn
```

---

## 4. Secrets (SSM Parameter Store)

Terraform creates **placeholder** SSM parameters. Fill them after first apply.

### Sync from local `.env` files

```bash
# Dry run — shows what would be written
python infra/scripts/sync_ssm_parameters.py --dry-run

# Apply (reads api/.env, voice-agent/.env, ui/.env by default)
python infra/scripts/sync_ssm_parameters.py \
  --region ap-south-1 \
  --profile relaydesk-admin

# Upload a single parameter:
python infra/scripts/sync_ssm_parameters.py --only OPENAI_API_KEY
python infra/scripts/sync_ssm_parameters.py --only DATABASE_URL --from-rds --password "$RDS_DB_PASSWORD"
python infra/scripts/sync_ssm_parameters.py --only COGNITO_CLIENT_SECRET --from-terraform

# Also write combined infra/scripts/env.properties (gitignored)
python infra/scripts/sync_ssm_parameters.py --write-env-properties
```

### Set RDS `DATABASE_URL`

If API logs show connection to `127.0.0.1:5432`, sync overwrote with local `.env`:

```bash
export RDS_DB_PASSWORD='YourRdsPassword'

python infra/scripts/sync_ssm_parameters.py \
  --only DATABASE_URL --from-rds \
  --profile relaydesk-admin --region ap-south-1 --dry-run

python infra/scripts/sync_ssm_parameters.py \
  --only DATABASE_URL --from-rds \
  --profile relaydesk-admin --region ap-south-1
```

**Initialize tables** (run once after RDS is created — not during ECS startup):

```powershell
# With SSM tunnel to RDS
$env:RDS_DB_PASSWORD = "YourRdsPassword"
python infra/scripts/bootstrap_db.py --use-tunnel --password "$RDS_DB_PASSWORD" --yes
```

Drops all tables, recreates schema, and loads Deepak seed data. See [`infra/scripts/bootstrap_db.py`](scripts/bootstrap_db.py).

**Local API against AWS RDS** (SSM tunnel — see [Connect from your laptop](#connect-from-your-laptop-psql--pgadmin)):

```powershell
# Terminal 1 — leave open
python infra/scripts/rds_tunnel.py start

# Terminal 2 — write api/.env.local and start API
$env:RDS_DB_PASSWORD = "YourRdsPassword"
python infra/scripts/rds_tunnel.py write-env --password $env:RDS_DB_PASSWORD
cd api
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Then redeploy API (production SSM `DATABASE_URL` uses the private RDS endpoint, not localhost):

```bash
aws ecs update-service --cluster relaydesk-prod --service relaydesk-prod-api \
  --force-new-deployment --profile relaydesk-admin --region ap-south-1
```

### Connect from your laptop (psql / pgAdmin / local API)

RDS is **private** (`publicly_accessible = false`) in **private subnets**. Connect through an **SSM port-forward tunnel** via a running ECS API EC2 host:

1. Install the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) (Windows: `winget install Amazon.SessionManagerPlugin`, then restart the terminal).

2. Start the tunnel (**leave this terminal open**):

```powershell
python infra/scripts/rds_tunnel.py start
```

```bash
python infra/scripts/rds_tunnel.py start
```

3. Point tools at **localhost:15432**:

| Field | Value |
|-------|-------|
| Host | `localhost` or `127.0.0.1` |
| Port | `15432` |
| Database | `relaydesk` |
| Username | `relaydesk_admin` |
| Password | Your `TF_VAR_rds_master_password` |

**Local API** — write `api/.env.local` (loaded after `.env`):

```powershell
$env:RDS_DB_PASSWORD = "YourRdsPassword"
python infra/scripts/rds_tunnel.py write-env --password $env:RDS_DB_PASSWORD
```

```bash
export RDS_DB_PASSWORD='...'
python infra/scripts/rds_tunnel.py write-env --password "$RDS_DB_PASSWORD"
```

```bash
psql -h localhost -p 15432 -U relaydesk_admin -d relaydesk
```

**Revert public RDS** (if you previously enabled it): set `publicly_accessible = false` in Terraform and run `terraform apply`. Direct connections to the RDS hostname on port `5432` from the internet will stop working — use the tunnel above.

### Google SSO (optional)

1. `terraform apply` with `enable_cognito_google = false`
2. Add to `infra/scripts/env.properties`:
   ```properties
   GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-xxxxx
   ```
3. `python infra/scripts/sync_ssm_parameters.py --profile relaydesk-admin --region ap-south-1`
4. Set `enable_cognito_google = true` and `terraform apply`

Google redirect URI: `https://relaydesk-prod.auth.ap-south-1.amazoncognito.com/oauth2/idpresponse`

---

## 5. Build images and deploy ECS

### Manual push (all three services)

From **repo root**:

```bash
export PROFILE_NAME="relaydesk-admin"
export AWS_REGION="ap-south-1"
export IMAGE_TAG="latest"

cd infra/terraform
export ACCOUNT_ID="$(terraform output -raw aws_account_id)"
export ECR_API="$(terraform output -raw ecr_api_repository_url)"
export ECR_UI="$(terraform output -raw ecr_ui_repository_url)"
export ECR_VOICE="$(terraform output -raw ecr_voice_agent_repository_url)"
export CLUSTER="$(terraform output -raw ecs_cluster_name)"
cd ../..

aws ecr get-login-password --profile "$PROFILE_NAME" --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Verify each build succeeds before push
docker build -t "${ECR_API}:${IMAGE_TAG}" ./api
docker push "${ECR_API}:${IMAGE_TAG}"
docker push "${ECR_API}:latest"

docker build -t "${ECR_UI}:${IMAGE_TAG}" ./ui
docker push "${ECR_UI}:${IMAGE_TAG}"
docker push "${ECR_UI}:latest"

docker build -t "${ECR_VOICE}:${IMAGE_TAG}" ./voice-agent
docker push "${ECR_VOICE}:${IMAGE_TAG}"
docker push "${ECR_VOICE}:latest"

for SVC in relaydesk-prod-api relaydesk-prod-ui relaydesk-prod-voice-agent; do
  aws ecs update-service --cluster "$CLUSTER" --service "$SVC" \
    --force-new-deployment --profile "$PROFILE_NAME" --region "$AWS_REGION"
done
```

### GitHub Actions (CI/CD)

Workflow: `.github/workflows/deploy-ecs.yml`

1. Set repository variables: `AWS_REGION`, `AWS_ROLE_ARN` (from `terraform output github_actions_role_arn`)
2. Push to `main` — builds, pushes ECR, redeploys ECS

---

## 6. Custom domain (Cloudflare + ACM)

DNS is managed in **Cloudflare** (not Route 53). Terraform creates the ACM certificate and ALB HTTPS listener; you create matching CNAME records in Cloudflare.

### Prerequisites

- Domain already on Cloudflare (nameservers pointed to Cloudflare)
- `ui_domain_name` set in `terraform.tfvars` (e.g. `relaydesk.uk`)
- `api_publicly_accessible = true` (required for public HTTPS)

### Step-by-step Cloudflare DNS

**1. Create the ACM certificate first** (so Terraform can output validation records without waiting forever):

```bash
cd infra/terraform
terraform apply -target=aws_acm_certificate.ui[0]
```

**2. Print the records to create:**

```bash
terraform output -json cloudflare_dns_instructions
# or:
terraform output acm_dns_validation_records
terraform output -raw alb_dns_name
```

**3. In Cloudflare → your zone → DNS → Records**, add:

| Purpose | Type | Name (Cloudflare) | Target / Content | Proxy status |
|---------|------|-------------------|------------------|--------------|
| **ACM validation** | CNAME | Hostname from output (often `_xxxxx.relaydesk.uk` — if Cloudflare complains, use only the `_xxxxx` host label) | Value from `acm_dns_validation_records` (ends with `.acm-validations.aws.`) | **DNS only** (gray cloud) — required |
| **App traffic** | CNAME | `@` (apex) or `www` | ALB DNS from `terraform output -raw alb_dns_name` (e.g. `relaydesk-prod-….ap-south-1.elb.amazonaws.com`) | Start as **DNS only** (gray); optional orange cloud later |

Cloudflare supports **CNAME flattening** on the apex (`@`), so pointing `@` at the ALB is fine.

**4. Cloudflare SSL/TLS settings** (SSL/TLS → Overview / Edge Certificates):

| Setting | Value |
|---------|-------|
| Encryption mode | **Full (strict)** |
| Always Use HTTPS | On (recommended) |
| Minimum TLS Version | 1.2 |

Do **not** use Flexible SSL — ALB terminates real TLS; Flexible causes redirect loops / broken HTTPS.

**5. Finish Terraform** (waits until ACM sees the validation CNAME, then attaches HTTPS listener):

```bash
terraform apply
```

Validation usually takes **5–15 minutes** after the gray-cloud CNAME is correct.

**6. Confirm Cognito + UI env**

```bash
terraform output cognito_callback_urls
terraform output cognito_production_sso_ready   # should be true
```

Set in `ui/.env`:

```bash
AUTH_URL=https://relaydesk.uk
RELAYDESK_API_URL_AWS=https://relaydesk.uk
```

Then rebuild/redeploy UI:

```bash
python infra/scripts/deploy_ui.py --profile relaydesk-admin --region ap-south-1
```

**7. Smoke test**

```bash
curl -I https://relaydesk.uk/login
curl https://relaydesk.uk/api/health
```

### After `rebuild_infra.py` / `terraform destroy`

ACM CNAMEs and the app CNAME must be updated again — ALB DNS name changes on every recreate. Re-run steps 1–5 (or use `terraform output cloudflare_dns_instructions`). Keep encryption mode **Full (strict)**.

### DNS troubleshooting

| Symptom | Fix |
|---------|-----|
| `terraform apply` hangs on ACM validation | ACM CNAME missing, wrong value, or **proxied** (orange cloud). Must be **DNS only**. |
| ERR_SSL / certificate name mismatch | App CNAME must point at current ALB; wait for ACM **ISSUED**; use Full (strict). |
| Cognito redirect_uri mismatch | `AUTH_URL` must match `https://<ui_domain_name>`; check `cognito_callback_urls`. |
| Redirect loop | Cloudflare set to Flexible — switch to Full (strict). |

---

## 7. Cognito user roles

| Group | Access |
|-------|--------|
| `guest-clients` | Auto-assigned on SSO sign-up — view-only |
| `approved-clients` | Upload/delete knowledge documents |
| `relaydesk-admins` | Full console and API access |

Voice-agent M2M tokens bypass role checks.

```bash
# Promote a user (business phone is stored in PostgreSQL; requires DATABASE_URL)
python infra/scripts/approve_cognito_user.py \
  --email user@example.com --role approved-clients \
  --business-phone +911171366880 \
  --profile relaydesk-admin --region ap-south-1

python infra/scripts/approve_cognito_user.py \
  --email deepakdeshwal85@gmail.com --role relaydesk-admins \
  --business-phone +911171366880 \
  --profile relaydesk-admin --region ap-south-1

# Revoke elevated roles
python infra/scripts/approve_cognito_user.py \
  --email user@example.com --revoke \
  --profile relaydesk-admin --region ap-south-1
```

Users must **sign out and sign in again** after role changes.

---

## 8. Operational scripts

All scripts in `infra/scripts/`. Run from repo root unless noted.

| Script | Purpose | Example |
|--------|---------|---------|
| **`setup_infra.py`** | **First-time** new-account setup (NEW_INFRA_SETUP) | `python infra/scripts/setup_infra.py --init-tfvars` |
| **`rebuild_infra.py`** | Destroy / provision / full rebuild (unattended) | `python infra/scripts/rebuild_infra.py rebuild --yes` |
| **`deploy_api.py`** | Build, push, deploy API | `python infra/scripts/deploy_api.py` |
| **`deploy_ui.py`** | Build, push, deploy UI | `python infra/scripts/deploy_ui.py` |
| **`deploy_voice_agent.py`** | Build, push, deploy voice-agent | `python infra/scripts/deploy_voice_agent.py` |
| **`deploy_all.py`** | Deploy all services (parallel by default) | `python infra/scripts/deploy_all.py` |
| **`rds_tunnel.py`** | RDS SSM tunnel + local `DATABASE_URL` | `python infra/scripts/rds_tunnel.py start` |
| **`sync_ssm_parameters.py`** | Push secrets to SSM (all or `--only KEY`) | `python infra/scripts/sync_ssm_parameters.py --profile relaydesk-admin` |
| **`bootstrap_db.py`** | Drop, recreate, seed PostgreSQL (Deepak) | `python infra/scripts/bootstrap_db.py --use-tunnel --password "$RDS_DB_PASSWORD" --yes` |
| **`approve_cognito_user.py`** | Assign or revoke Cognito roles | `python infra/scripts/approve_cognito_user.py --email u@x.com --role relaydesk-admins` |
| **`cost_control.py`** | Stop/start ECS + ASG (+ optional RDS) | `python infra/scripts/cost_control.py status` |

`deploy_common.py` is a shared library used by the deploy scripts — not run directly.

### `setup_infra.py` (new AWS account)

Automates [`NEW_INFRA_SETUP.md`](NEW_INFRA_SETUP.md) phases 0–8: Terraform apply, `.env` patching from outputs, SSM sync, RDS bootstrap, ECS deploy, optional Cognito admin approval.

Prerequisites: filled `api/.env`, `ui/.env`, `voice-agent/.env` (vendor keys), `RDS_DB_PASSWORD`, and `terraform.tfvars` (or `--init-tfvars` + `setup.config.json`).

```powershell
$env:RDS_DB_PASSWORD = "YourStrongRdsPassword"
python infra/scripts/setup_infra.py --init-tfvars --dry-run --profile relaydesk-admin
python infra/scripts/setup_infra.py --init-tfvars --profile relaydesk-admin
```

See `setup.config.example.json` for optional `github_org`, `ui_domain_name`, and `approve_admin`.

### `rebuild_infra.py` (destroy / provision / rebuild)

Unattended orchestration of Terraform, SSM sync, Deepak DB seed, and `deploy_all.py`. Requires existing `api/.env`, `ui/.env`, `voice-agent/.env`, and `terraform.tfvars`.

```powershell
# Required once per shell
$env:RDS_DB_PASSWORD = "YourStrongRdsPassword"
$env:AWS_PROFILE = "relaydesk-admin"

# Preview steps (no changes)
python infra/scripts/rebuild_infra.py rebuild --yes --dry-run --profile relaydesk-admin

# Tear down AWS (near-zero bill; irreversible)
python infra/scripts/rebuild_infra.py destroy --yes --profile relaydesk-admin

# Recreate from scratch (apply → seed Deepak → SSM → deploy)
python infra/scripts/rebuild_infra.py provision --profile relaydesk-admin

# Full cycle: destroy + provision (~1–2 hours)
python infra/scripts/rebuild_infra.py rebuild --yes --profile relaydesk-admin --region ap-south-1
```

| Flag | Meaning |
|------|---------|
| `--yes` | Required for `destroy` / `rebuild` |
| `--skip-terraform` | Skip `terraform apply` (infra already exists) |
| `--skip-bootstrap` | Keep existing RDS data |
| `--skip-deploy` | Infra + DB only; no Docker/ECS |
| `--dry-run` | Print steps only |

**After rebuild, still manual:**

1. **Cloudflare DNS** — ALB hostname changed; follow [§6 Custom domain](#6-custom-domain-cloudflare--acm)
2. **Cognito users** — sign in once, then `approve_cognito_user.py`

When `ui_domain_name` is set, `provision` / `rebuild` creates the ACM cert first, prints the **ACM validation CNAME**, then **waits until the certificate is ISSUED** (add that Cloudflare gray-cloud CNAME while it waits). After apply finishes it prints the **ALB CNAME** for the apex/`www` record.

Qdrant collections and vendor API keys in local `.env` files are reused automatically.

### `sync_ssm_parameters.py` (single key)

```bash
# One parameter from local .env files:
python infra/scripts/sync_ssm_parameters.py --only OPENAI_API_KEY

# RDS DATABASE_URL for production SSM:
python infra/scripts/sync_ssm_parameters.py --only DATABASE_URL --from-rds --password "$RDS_DB_PASSWORD"

# Voice-agent Cognito M2M secret from Terraform state:
python infra/scripts/sync_ssm_parameters.py --only COGNITO_CLIENT_SECRET --from-terraform
```

### `cost_control.py`

Pause compute without destroying the VPC/NAT/ALB stack:

```bash
# Current desired counts
python infra/scripts/cost_control.py status \
  --profile relaydesk-admin --region ap-south-1

# Stop ECS tasks and scale ASGs to 0 (saves EC2 compute)
python infra/scripts/cost_control.py stop \
  --profile relaydesk-admin --region ap-south-1

# Also stop RDS (optional)
python infra/scripts/cost_control.py stop \
  --profile relaydesk-admin --region ap-south-1 --include-rds

# Restore from infra/scripts/cost-control-state.json
python infra/scripts/cost_control.py start \
  --profile relaydesk-admin --region ap-south-1 --include-rds
```

**Still billed while stopped:** NAT Gateway, ALB, EIPs, RDS storage, ECR, SSM.

| Goal | Use |
|------|-----|
| Short pause (days/weeks), fast resume | `cost_control.py stop --include-rds` |
| Long idle, near-zero AWS bill | `rebuild_infra.py destroy --yes` then later `provision` |

### ASG instance refresh (after changing instance type)

```bash
aws autoscaling start-instance-refresh \
  --auto-scaling-group-name relaydesk-prod-ecs-api \
  --region ap-south-1 --profile relaydesk-admin \
  --preferences '{"MinHealthyPercentage":0,"InstanceWarmup":300}'

aws autoscaling start-instance-refresh \
  --auto-scaling-group-name relaydesk-prod-ecs-voice \
  --region ap-south-1 --profile relaydesk-admin \
  --preferences '{"MinHealthyPercentage":0,"InstanceWarmup":300}'
```

---

## 9. Monitoring and logs

### CloudWatch log groups

| Service | Log group |
|---------|-----------|
| API | `/ecs/relaydesk-prod/api` |
| Voice agent | `/ecs/relaydesk-prod/voice-agent` |
| UI | `/ecs/relaydesk-prod/ui` |

```bash
export PROFILE_NAME="relaydesk-admin"
export AWS_REGION="ap-south-1"

aws logs tail /ecs/relaydesk-prod/api --since 10m --follow \
  --region "$AWS_REGION" --profile "$PROFILE_NAME"

aws logs tail /ecs/relaydesk-prod/voice-agent --since 10m --follow \
  --region "$AWS_REGION" --profile "$PROFILE_NAME"
```

### Cost monitoring

```bash
terraform output billing_dashboard_url
terraform output cost_explorer_url
```

Enable billing alerts in AWS Console → Billing preferences if the dashboard is empty.

---

## 10. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Cannot connect to RDS from laptop | `python infra/scripts/rds_tunnel.py start`, then `python infra/scripts/rds_tunnel.py write-env --password <RDS_PASSWORD>` |
| `SessionManagerPlugin is not found` | `winget install Amazon.SessionManagerPlugin` and restart terminal |
| Voice agent RAG `401` | `python infra/scripts/sync_ssm_parameters.py --only COGNITO_CLIENT_SECRET --from-terraform`, redeploy voice-agent |
| UI shows old code after push | Verify `docker build` succeeded; force ECS deployment |
| `client_email_id` errors in UI | Redeploy UI + API; sign out/in; complete profile on `/login` |
| Cognito callback mismatch | `terraform output cognito_callback_urls` must match UI `AUTH_URL` |
| Google SSO fails | Check SSM `GOOGLE_*` params and `enable_cognito_google = true` |
| ACM validation stuck | Cloudflare ACM CNAME must be **DNS only** (gray); check `terraform output acm_dns_validation_records` |
| HTTPS redirect loop | Cloudflare SSL mode must be **Full (strict)**, not Flexible |
| Domain after rebuild | ALB DNS changed — update app CNAME; see [§6](#6-custom-domain-cloudflare--acm) |

### Fix voice-agent M2M secret (Terraform targeted apply)

```bash
cd infra/terraform
terraform apply -target=aws_ssm_parameter.cognito_voice_client_secret[0]
```

---

## 11. Sizing defaults

| Component | ECS task | EC2 host |
|-----------|----------|----------|
| API | 0.25 vCPU, 512 MiB | `t3.small` |
| Voice agent | 2 vCPU, 7680 MiB | `t3.large` |
| UI | 0.25 vCPU, 512 MiB | Shares API ASG |

**Free Tier tip:** `api_ecs_instance_type = "t3.micro"`, `voice_agent_desired_count = 0`.

---

## Related docs

- [`../api/README.md`](../api/README.md) — API local run and scripts
- [`../ui/README.md`](../ui/README.md) — UI local run and Docker
- [`../voice-agent/README.md`](../voice-agent/README.md) — Agent local run and config
