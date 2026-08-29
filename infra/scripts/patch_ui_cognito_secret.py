#!/usr/bin/env python3
"""Restore UI COGNITO_CLIENT_SECRET in SSM from the Cognito UI app client."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
UI_TF_RESOURCE = "aws_cognito_user_pool_client.ui[0]"


def fetch_ui_client_secret(
    *,
    profile: str | None,
    region: str,
    user_pool_id: str,
    client_id: str,
) -> str:
    cmd = [
        "aws",
        "cognito-idp",
        "describe-user-pool-client",
        "--user-pool-id",
        user_pool_id,
        "--client-id",
        client_id,
        "--region",
        region,
        "--output",
        "json",
        "--no-cli-pager",
    ]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout or "{}")
    secret = payload.get("UserPoolClient", {}).get("ClientSecret")
    if isinstance(secret, str) and secret.strip():
        return secret.strip()
    raise RuntimeError("Cognito API did not return UI ClientSecret")


def put_ssm(
    *,
    name: str,
    value: str,
    region: str,
    profile: str | None,
) -> None:
    cmd = [
        "aws",
        "ssm",
        "put-parameter",
        "--name",
        name,
        "--value",
        value,
        "--type",
        "SecureString",
        "--overwrite",
        "--region",
        region,
        "--no-cli-pager",
    ]
    if profile:
        cmd.extend(["--profile", profile])
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix UI Cognito client secret in SSM.")
    parser.add_argument("--terraform-dir", default=str(DEFAULT_TERRAFORM_DIR))
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--project", default="relaydesk")
    parser.add_argument("--environment", default="prod")
    parser.add_argument(
        "--patch-ui-env",
        action="store_true",
        help="Also write COGNITO_CLIENT_SECRET to ui/.env",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(SCRIPT_DIR))
    from setup_common import set_env_value, terraform_output_raw, terraform_state_attr

    terraform_dir = Path(args.terraform_dir).resolve()
    pool_id = terraform_output_raw(terraform_dir, "cognito_user_pool_id")
    client_id = terraform_output_raw(terraform_dir, "cognito_ui_client_id")
    if not client_id:
        client_id = terraform_state_attr(terraform_dir, UI_TF_RESOURCE, "id")
    if not pool_id or not client_id:
        print("Missing Cognito UI client metadata", file=sys.stderr)
        return 1

    secret = fetch_ui_client_secret(
        profile=args.profile,
        region=args.region,
        user_pool_id=pool_id,
        client_id=client_id,
    )
    ssm_name = f"/{args.project}/{args.environment}/ui/COGNITO_CLIENT_SECRET"
    put_ssm(name=ssm_name, value=secret, region=args.region, profile=args.profile)
    print(f"restored {ssm_name}")

    if args.patch_ui_env:
        ui_env = REPO_ROOT / "ui" / ".env"
        if set_env_value(ui_env, "COGNITO_CLIENT_SECRET", secret):
            print(f"patched COGNITO_CLIENT_SECRET in {ui_env}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc, file=sys.stderr)
        raise SystemExit(exc.returncode or 1) from exc
