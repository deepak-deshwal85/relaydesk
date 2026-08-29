#!/usr/bin/env python3
"""Automated first-time RelayDesk AWS infrastructure setup.

Runs NEW_INFRA_SETUP phases 0–8 unattended: prerequisites, Terraform apply,
.env patching from outputs, SSM sync, RDS bootstrap, ECS deploy, and optional
Cognito admin approval.

Fill vendor API keys in api/.env, ui/.env, and voice-agent/.env before running.
Set RDS_DB_PASSWORD (or pass --password). Optionally copy setup.config.example.json
to setup.config.json and edit github_org / ui_domain_name.

Examples (from repo root):
  # Preview all steps
  python infra/scripts/setup_infra.py --dry-run --profile relaydesk-admin

  # First-time setup (creates terraform.tfvars from config if missing)
  $env:RDS_DB_PASSWORD = "YourStrongRdsPassword"
  python infra/scripts/setup_infra.py --init-tfvars --profile relaydesk-admin

  # API + UI only (voice_agent_desired_count=0 in tfvars)
  python infra/scripts/setup_infra.py --skip-voice --profile relaydesk-admin

  # Infra already applied — patch .env, sync, bootstrap, deploy
  python infra/scripts/setup_infra.py --skip-terraform --profile relaydesk-admin
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import rebuild_infra as ri  # noqa: E402
import setup_common as sc  # noqa: E402

DEFAULT_TERRAFORM_DIR = sc.DEFAULT_TERRAFORM_DIR


def _resolve_from_config(config: dict, key: str, explicit: str | None, env_key: str) -> str | None:
    if explicit:
        return explicit
    value = config.get(key)
    if value:
        return str(value)
    env_val = os.getenv(env_key)
    return env_val if env_val else None


def _run_approve_admin(
    *,
    profile: str,
    region: str,
    approve: dict,
    dry_run: bool,
) -> None:
    email = str(approve.get("email") or "").strip()
    role = str(approve.get("role") or "relaydesk-admins").strip()
    phone = str(approve.get("business_phone") or "").strip()
    if not email:
        return

    args = ["--email", email, "--role", role, "--profile", profile, "--region", region]
    if phone:
        args.extend(["--business-phone", phone])

    print("\n==> Approve Cognito admin user")
    print("    Note: user must sign in via SSO at least once before approval succeeds.")
    ri._run_python_script(
        "approve_cognito_user.py",
        args,
        label=f"approve_cognito_user.py ({email} -> {role})",
        dry_run=dry_run,
    )


def _deploy_services(
    *,
    profile: str,
    region: str,
    terraform_dir: Path,
    skip_voice: bool,
    dry_run: bool,
) -> None:
    deploy_args = ["--profile", profile, "--region", region, "--terraform-dir", str(terraform_dir)]
    if skip_voice:
        deploy_args.extend(["--only", "api,ui"])
    ri._run_python_script(
        "deploy_all.py",
        deploy_args,
        label="Build and deploy ECS services",
        dry_run=dry_run,
    )


def _wait_services(
    *,
    profile: str,
    region: str,
    terraform_dir: Path,
    skip_voice: bool,
    dry_run: bool,
) -> None:
    if dry_run:
        ri._wait_ecs_services_running(
            profile=profile,
            region=region,
            cluster="relaydesk-prod",
            services=["relaydesk-prod-api", "relaydesk-prod-ui"],
            dry_run=True,
        )
        return

    cluster = ri._terraform_output(terraform_dir, "ecs_cluster_name")
    services = ri._collect_ecs_services(terraform_dir)
    if skip_voice:
        voice = ri._terraform_output(terraform_dir, "ecs_service_voice_agent_name")
        services = [name for name in services if name != voice]
    ri._wait_ecs_services_running(
        profile=profile,
        region=region,
        cluster=cluster,
        services=services,
        dry_run=False,
    )


def setup(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve() if args.config else None
    config = sc.load_config(config_path)

    profile = ri._resolve_profile(
        _resolve_from_config(config, "aws_profile", args.profile, "AWS_PROFILE")
    )
    region = (
        _resolve_from_config(config, "aws_region", args.region, "AWS_REGION") or "ap-south-1"
    )
    password = ri._resolve_password(args.password, required=not args.dry_run)
    terraform_dir = Path(
        _resolve_from_config(config, "terraform_dir", str(args.terraform_dir), "")
        or DEFAULT_TERRAFORM_DIR
    ).resolve()

    print("RelayDesk infrastructure setup")
    print(f"  profile:   {profile}")
    print(f"  region:    {region}")
    print(f"  terraform: {terraform_dir.relative_to(REPO_ROOT)}")

    ri._check_prerequisites(require_env_files=not args.init_env)
    sc.verify_aws_identity(profile=profile, region=region, dry_run=args.dry_run)

    if args.init_env:
        sc.ensure_env_files(init=True)
    else:
        sc.ensure_env_files(init=False)

    sc.validate_env_secrets(skip_voice=args.skip_voice, strict=not args.dry_run)

    if args.init_tfvars:
        sc.ensure_tfvars(terraform_dir, config)
    sc.validate_tfvars(terraform_dir, config)

    # Phase 2 — Terraform apply
    if not args.skip_terraform:
        ri._terraform_apply(
            terraform_dir,
            password=password,
            profile=profile,
            region=region,
            dry_run=args.dry_run,
        )
        sc.patch_env_from_terraform(terraform_dir, region=region, dry_run=args.dry_run)

    # Phase 4–6 — bootstrap, SSM, deploy (reuse rebuild_infra helpers)
    ri._active_profile = profile
    ri._active_region = region
    ri._active_terraform_dir = terraform_dir

    if args.dry_run:
        rds_id = "relaydesk-prod-postgres"
    else:
        rds_id = ri._terraform_output(terraform_dir, "rds_instance_identifier")

    ri._wait_rds_available(
        profile=profile,
        region=region,
        instance_id=rds_id,
        dry_run=args.dry_run,
    )

    if not args.skip_bootstrap:
        ri._bootstrap_database(password=password, dry_run=args.dry_run)

    ri._sync_secrets(
        profile=profile,
        region=region,
        password=password,
        terraform_dir=terraform_dir,
        dry_run=args.dry_run,
    )

    if not args.skip_deploy:
        _deploy_services(
            profile=profile,
            region=region,
            terraform_dir=terraform_dir,
            skip_voice=args.skip_voice,
            dry_run=args.dry_run,
        )
        _wait_services(
            profile=profile,
            region=region,
            terraform_dir=terraform_dir,
            skip_voice=args.skip_voice,
            dry_run=args.dry_run,
        )

    approve = config.get("approve_admin") if isinstance(config.get("approve_admin"), dict) else {}
    approve_email = args.approve_admin_email or str(approve.get("email") or "").strip()
    if approve_email:
        approve_cfg = {
            "email": approve_email,
            "role": args.approve_admin_role or approve.get("role") or "relaydesk-admins",
            "business_phone": args.approve_admin_phone or approve.get("business_phone") or "",
        }
        _run_approve_admin(
            profile=profile,
            region=region,
            approve=approve_cfg,
            dry_run=args.dry_run,
        )

    sc.run_health_checks(terraform_dir, dry_run=args.dry_run)
    sc.print_setup_summary(terraform_dir, profile=profile, region=region)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None, help="AWS CLI profile (or AWS_PROFILE)")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    parser.add_argument("--password", default=None, help="RDS password (or RDS_DB_PASSWORD)")
    parser.add_argument("--terraform-dir", type=Path, default=DEFAULT_TERRAFORM_DIR)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON config (default: infra/scripts/setup.config.json if present)",
    )
    parser.add_argument(
        "--init-tfvars",
        action="store_true",
        help="Create terraform.tfvars from example + config when missing",
    )
    parser.add_argument(
        "--init-env",
        action="store_true",
        help="Copy missing .env files from .env.example (fill secrets before apply)",
    )
    parser.add_argument(
        "--skip-terraform",
        action="store_true",
        help="Skip terraform apply (infra already exists)",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip RDS drop/seed (keep existing DB)",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip Docker build and ECS deploy",
    )
    parser.add_argument(
        "--skip-voice",
        action="store_true",
        help="Deploy api+ui only (set voice_agent_desired_count=0 in tfvars to save cost)",
    )
    parser.add_argument(
        "--approve-admin-email",
        default=None,
        help="Run approve_cognito_user.py after deploy (user must sign in first)",
    )
    parser.add_argument(
        "--approve-admin-role",
        default=None,
        help="Cognito role for --approve-admin-email (default: relaydesk-admins)",
    )
    parser.add_argument(
        "--approve-admin-phone",
        default=None,
        help="Business phone for admin approval (required for relaydesk-admins)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print steps only; make no changes")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return setup(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
