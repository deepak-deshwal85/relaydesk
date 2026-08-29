#!/usr/bin/env python3
"""Patch voice-agent/.env COGNITO_CLIENT_SECRET from Terraform or Cognito API."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
DEFAULT_VOICE_ENV = REPO_ROOT / "voice-agent" / ".env"
VOICE_M2M_RESOURCE = "aws_cognito_user_pool_client.voice_m2m[0]"


def secret_from_terraform(terraform_dir: Path, resource: str) -> str:
    for extra in (["-show-sensitive"], []):
        result = subprocess.run(
            ["terraform", "state", "show", *extra, resource],
            cwd=str(terraform_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        match = re.search(
            r'^\s*client_secret\s*=\s*"(.*)"\s*$',
            result.stdout or "",
            re.MULTILINE,
        )
        if match:
            secret = match.group(1)
            if secret and secret not in {"CHANGEME", "(sensitive value)"}:
                return secret
    raise RuntimeError("Could not read voice M2M client_secret from Terraform state")


def secret_from_cognito_api(
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
    import json

    payload = json.loads(result.stdout or "{}")
    secret = payload.get("UserPoolClient", {}).get("ClientSecret")
    if isinstance(secret, str) and secret.strip():
        return secret.strip()
    raise RuntimeError("Cognito API did not return ClientSecret for voice M2M client")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write voice-agent COGNITO_CLIENT_SECRET from Terraform or Cognito."
    )
    parser.add_argument("--terraform-dir", default=str(DEFAULT_TERRAFORM_DIR))
    parser.add_argument("--voice-env", default=str(DEFAULT_VOICE_ENV))
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument(
        "--from-cognito-api",
        action="store_true",
        help="Fetch secret from Cognito API when Terraform state hides it",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(SCRIPT_DIR))
    from setup_common import set_env_value, terraform_output_raw, terraform_state_attr

    terraform_dir = Path(args.terraform_dir).resolve()
    voice_env = Path(args.voice_env).resolve()

    secret: str | None = None
    try:
        secret = secret_from_terraform(terraform_dir, VOICE_M2M_RESOURCE)
    except RuntimeError:
        secret = None

    if secret is None and args.from_cognito_api:
        pool_id = terraform_output_raw(terraform_dir, "cognito_user_pool_id")
        client_id = terraform_output_raw(terraform_dir, "cognito_m2m_client_id")
        if not client_id:
            client_id = terraform_state_attr(terraform_dir, VOICE_M2M_RESOURCE, "id")
        if not pool_id or not client_id:
            print("Missing cognito_user_pool_id or m2m client id", file=sys.stderr)
            return 1
        secret = secret_from_cognito_api(
            profile=args.profile,
            region=args.region,
            user_pool_id=pool_id,
            client_id=client_id,
        )

    if secret is None:
        print(
            "Could not resolve voice M2M client secret. "
            "Re-run with --from-cognito-api (requires AWS credentials).",
            file=sys.stderr,
        )
        return 1

    if set_env_value(voice_env, "COGNITO_CLIENT_SECRET", secret):
        print(f"patched COGNITO_CLIENT_SECRET in {voice_env}")
    else:
        print(f"COGNITO_CLIENT_SECRET already correct in {voice_env}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc, file=sys.stderr)
        raise SystemExit(exc.returncode or 1) from exc
