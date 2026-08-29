aws_region   = "ap-south-1"
environment  = "prod"
project_name = "relaydesk"

# Required: your GitHub org or username (for OIDC deploy role trust)
github_org  = "deepak-deshwal85"
github_repo = "relaydesk"

# Separate EC2 hosts (API and voice agent do not share a machine)
api_ecs_instance_type             = "t3.small"
api_ecs_instance_desired_capacity = 1
voice_ecs_instance_type             = "t3.large"
voice_ecs_instance_desired_capacity = 1

api_ecr_image_tag   = "latest"
voice_ecr_image_tag = "latest"

voice_agent_desired_count = 1
voice_agent_cpu           = 2048   # 2 vCPU on dedicated voice host
voice_agent_memory        = 7680   # ~7.5 GiB on t3.large

# Set true only if you need to upload documents from the public internet
api_publicly_accessible = true

# Set false if GitHub OIDC provider already exists in this AWS account
manage_github_oidc_provider = true

# Must match aws_region — Mumbai only (avoid ap-south-1c)
availability_zones = ["ap-south-1a", "ap-south-1b"]

# RDS PostgreSQL (used by API DATABASE_URL)
enable_rds_postgres = true
rds_engine_version  = "16.14"
rds_instance_class  = "db.t3.micro"
rds_database_name   = "relaydesk"
rds_master_username = "relaydesk_admin"

# Cost monitoring
enable_cost_monitoring = true
monthly_budget_usd     = 75
budget_alert_emails    = ["deepakdeshwal85@gmail.com"]

enable_cognito = true

# Custom domain (Cloudflare DNS + ACM on ALB). Cognito callbacks auto-added for HTTPS.
ui_domain_name = "relaydesk.uk"

cognito_ui_callback_urls = ["http://localhost:3000/api/auth/callback/cognito"]
cognito_ui_logout_urls   = ["http://localhost:3000/login"]

# Google IdP: put credentials in SSM (not here), then set true.
#   /relaydesk/prod/cognito/GOOGLE_CLIENT_ID
#   /relaydesk/prod/cognito/GOOGLE_CLIENT_SECRET
# Sync via: python infra/scripts/sync_ssm_parameters.py
# (add GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to infra/scripts/env.properties)
enable_cognito_google = true