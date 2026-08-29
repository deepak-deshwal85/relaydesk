locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
  }

  ecr_api_repo         = "${var.project_name}-api"
  ecr_voice_agent_repo = "${var.project_name}-voice-agent"
  ecr_ui_repo          = "${var.project_name}-ui"

  ssm_prefix_api         = "/${var.project_name}/${var.environment}/api"
  ssm_prefix_voice_agent = "/${var.project_name}/${var.environment}/voice-agent"
  ssm_prefix_ui          = "/${var.project_name}/${var.environment}/ui"
  ssm_prefix_cognito     = "/${var.project_name}/${var.environment}/cognito"

  cognito_secret_keys = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
  ]

  cognito_guest_group_name    = "guest-clients"
  cognito_approved_group_name = "approved-clients"
  cognito_admin_group_name    = "relaydesk-admins"

  api_image   = "${aws_ecr_repository.api.repository_url}:${var.api_ecr_image_tag}"
  voice_image = "${aws_ecr_repository.voice_agent.repository_url}:${var.voice_ecr_image_tag}"
  ui_image    = var.enable_ui ? "${aws_ecr_repository.ui[0].repository_url}:${var.ui_ecr_image_tag}" : ""

  service_discovery_namespace = "${var.project_name}.local"
  api_service_dns             = "api.${local.service_discovery_namespace}"
  # Voice agent → API via Cloud Map (bypasses ALB HTTP→HTTPS redirect on custom domain).
  api_rag_base_url            = "http://${local.api_service_dns}:8090"

  cognito_enabled = var.enable_cognito && var.enable_ui
  cognito_issuer = local.cognito_enabled ? (
    "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main[0].id}"
  ) : ""
  cognito_token_url = local.cognito_enabled ? (
    "https://${aws_cognito_user_pool_domain.main[0].domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
  ) : ""
  cognito_ui_client_id = local.cognito_enabled ? aws_cognito_user_pool_client.ui[0].id : ""
  cognito_m2m_client_id = local.cognito_enabled ? aws_cognito_user_pool_client.voice_m2m[0].id : ""

  api_oauth_environment = local.cognito_enabled ? [
    { name = "COGNITO_REGION", value = var.aws_region },
    { name = "COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.main[0].id },
    { name = "COGNITO_UI_CLIENT_ID", value = local.cognito_ui_client_id },
    { name = "COGNITO_M2M_CLIENT_ID", value = local.cognito_m2m_client_id },
    { name = "COGNITO_REQUIRED_SCOPE", value = "relaydesk-api/access" },
  ] : [
    { name = "OAUTH_DISABLED", value = "true" },
  ]

  api_environment = concat([
    { name = "RAG_API_HOST", value = "0.0.0.0" },
    { name = "RAG_API_PORT", value = "8090" },
    { name = "RAG_BACKEND", value = "qdrant" },
    {
      name = "CORS_ORIGINS"
      value = join(",", distinct(compact([
        local.ui_public_base_url,
        "http://${aws_lb.api.dns_name}",
        "http://localhost:3000",
      ])))
    },
  ], local.api_oauth_environment)

  voice_oauth_environment = local.cognito_enabled ? [
    { name = "COGNITO_TOKEN_URL", value = local.cognito_token_url },
    { name = "COGNITO_CLIENT_ID", value = local.cognito_m2m_client_id },
    { name = "COGNITO_SCOPE", value = "relaydesk-api/access" },
  ] : []

  voice_agent_environment = concat([
    { name = "RAG_BACKEND", value = "qdrant" },
    { name = "RAG_API_BASE_URL", value = local.api_rag_base_url },
    { name = "AGENT_NAME", value = "relaydesk-agent" },
    { name = "TURN_ENDPOINTING_MAX_DELAY", value = "1.0" },
    { name = "TURN_ENDPOINTING_MIN_DELAY", value = "0.3" },
  ], local.voice_oauth_environment)

  api_secret_keys = [
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "QDRANT_API_KEY",
    "QDRANT_CLUSTER_ENDPOINT",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
  ]

  voice_agent_secret_keys = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ASSEMBLYAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPGRAM_API_KEY",
    "CALCOM_API_KEY",
  ]

  alb_public = var.api_publicly_accessible || var.enable_ui

  ui_cognito_environment = local.cognito_enabled ? [
    { name = "COGNITO_ISSUER", value = local.cognito_issuer },
    { name = "COGNITO_CLIENT_ID", value = local.cognito_ui_client_id },
    { name = "COGNITO_SCOPE", value = "relaydesk-api/access" },
  ] : []

  ui_environment = concat([
    { name = "AUTH_URL", value = local.ui_public_base_url },
    { name = "AUTH_DISABLE_SSO", value = "false" },
    # Browser talks to UI; UI server proxies to API via HTTP ALB DNS (same VPC).
    { name = "RELAYDESK_API_TARGET", value = "aws" },
    { name = "RELAYDESK_API_URL_AWS", value = local.ui_https_enabled ? "https://${var.ui_domain_name}" : "http://${aws_lb.api.dns_name}" },
    { name = "RELAYDESK_API_URL_LOCAL", value = "http://127.0.0.1:8090" },
    { name = "AUTH_TRUST_HOST", value = "true" },
  ], local.ui_cognito_environment)

  ui_secret_keys = local.cognito_enabled ? [
    "AUTH_SECRET",
  ] : [
    "AUTH_SECRET",
  ]
}
