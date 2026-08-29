#!/usr/bin/env python3
"""Upload RelayDesk ECS secrets to AWS SSM Parameter Store.

Reads each app's .env by default (api/.env, voice-agent/.env, ui/.env),
optionally merges infra/scripts/env.properties, then uploads SSM parameters.

Usage:
  python infra/scripts/sync_ssm_parameters.py --dry-run
  python infra/scripts/sync_ssm_parameters.py --profile relaydesk-admin --region ap-south-1

  # Upload a single parameter from local .env files:
  python infra/scripts/sync_ssm_parameters.py --only OPENAI_API_KEY
  python infra/scripts/sync_ssm_parameters.py --only DATABASE_URL

  # Build DATABASE_URL from RDS terraform outputs (not localhost):
  python infra/scripts/sync_ssm_parameters.py --only DATABASE_URL --from-rds --password "$RDS_DB_PASSWORD"

  # Sync voice-agent Cognito M2M secret from Terraform state:
  python infra/scripts/sync_ssm_parameters.py --only COGNITO_CLIENT_SECRET --from-terraform

  # Patch local voice-agent/.env when Terraform hides the secret:
  python infra/scripts/patch_voice_cognito_secret.py --from-cognito-api --profile relaydesk-admin
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PROPERTIES = SCRIPTS_DIR / "env.properties"
DEFAULT_TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"

API_SECRET_KEYS = [
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "QDRANT_API_KEY",
    "QDRANT_CLUSTER_ENDPOINT",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
]

VOICE_AGENT_SECRET_KEYS = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ASSEMBLYAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPGRAM_API_KEY",
    "CALCOM_API_KEY",
    "COGNITO_CLIENT_SECRET",
]

UI_SECRET_KEYS = [
    "AUTH_SECRET",
    "COGNITO_CLIENT_SECRET",
]

COGNITO_SECRET_KEYS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
]

ALL_KNOWN_KEYS = sorted(
    set(API_SECRET_KEYS)
    | set(VOICE_AGENT_SECRET_KEYS)
    | set(UI_SECRET_KEYS)
    | set(COGNITO_SECRET_KEYS)
)

VOICE_COGNITO_TF_RESOURCE = "aws_cognito_user_pool_client.voice_m2m[0]"


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def merge_sources(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        merged.update(source)
    return merged


def ssm_name(prefix: str, key: str) -> str:
    return f"{prefix.rstrip('/')}/{key}"


def validate_database_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "postgresql+asyncpg":
        raise ValueError("DATABASE_URL must start with postgresql+asyncpg://")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise ValueError("DATABASE_URL is missing host or database name.")
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        raise ValueError(
            "DATABASE_URL points to localhost. For AWS, use:\n"
            "  python infra/scripts/sync_ssm_parameters.py "
            "--only DATABASE_URL --from-rds --password <RDS_PASSWORD>"
        )


def terraform_outputs(terraform_dir: Path) -> dict[str, object]:
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return __import__("json").loads(result.stdout or "{}")


def terraform_output_value(outputs: dict[str, object], key: str) -> str:
    entry = outputs.get(key)
    if not isinstance(entry, dict):
        raise RuntimeError(f"Missing terraform output: {key}")
    value = entry.get("value")
    if value is None or value == "" or value == "null":
        raise RuntimeError(f"Terraform output {key!r} is empty")
    return str(value).strip()


def build_database_url_from_rds(*, terraform_dir: Path, password: str) -> str:
    outputs = terraform_outputs(terraform_dir)
    endpoint = terraform_output_value(outputs, "rds_endpoint")
    db_name = terraform_output_value(outputs, "rds_database_name")
    username = terraform_output_value(outputs, "rds_master_username")
    port = terraform_output_value(outputs, "rds_port")
    encoded = quote_plus(password.strip())
    return (
        f"postgresql+asyncpg://{username}:{encoded}@{endpoint}:{port}/{db_name}"
    )


def cognito_voice_secret_from_terraform(
    *,
    terraform_dir: Path,
    resource: str,
) -> str:
    stdout = ""
    for extra in (["-show-sensitive"], []):
        cmd = ["terraform", "state", "show", *extra, resource]
        result = subprocess.run(
            cmd,
            cwd=str(terraform_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        stdout = result.stdout or ""
        match = re.search(
            r'^\s*client_secret\s*=\s*"(.*)"\s*$',
            stdout,
            re.MULTILINE,
        )
        if match:
            secret = match.group(1)
            if secret and secret not in {"CHANGEME", "(sensitive value)"}:
                return secret
    raise RuntimeError("Could not find client_secret in terraform state")


def put_parameter(
    *,
    name: str,
    value: str,
    region: str,
    profile: str | None,
    dry_run: bool,
) -> bool:
    if dry_run:
        print(f"[dry-run] would set {name}")
        return True

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

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print(f"failed {name}", file=sys.stderr)
        return False
    print(f"set {name}")
    return True


def write_env_properties(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Optional combined SSM upload file — do not commit.",
        "# Preferred source: api/.env, voice-agent/.env, ui/.env",
        "# Used by: python infra/scripts/sync_ssm_parameters.py",
        "",
    ]
    for key in ALL_KNOWN_KEYS:
        value = values.get(key, "")
        if value:
            lines.append(f"{key}={value}")
        else:
            lines.append(f"# {key}=")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def upload_targets_for_key(
    key: str,
    *,
    prefixes: dict[str, str],
    voice_only: bool = False,
) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    if key in API_SECRET_KEYS:
        targets.append((prefixes["api"], key))
    if key in VOICE_AGENT_SECRET_KEYS:
        targets.append((prefixes["voice"], key))
    if key in UI_SECRET_KEYS and not (voice_only and key == "COGNITO_CLIENT_SECRET"):
        targets.append((prefixes["ui"], key))
    if key in COGNITO_SECRET_KEYS:
        targets.append((prefixes["cognito"], key))
    return targets


def upload_key(
    key: str,
    value: str,
    *,
    prefixes: dict[str, str],
    region: str,
    profile: str | None,
    dry_run: bool,
) -> int:
    if not value.strip():
        print(f"No value for {key}", file=sys.stderr)
        return 1

    if key == "DATABASE_URL":
        try:
            validate_database_url(value)
        except ValueError as exc:
            print(f"invalid DATABASE_URL: {exc}", file=sys.stderr)
            return 1

    targets = upload_targets_for_key(
        key,
        prefixes=prefixes,
        voice_only=(key == "COGNITO_CLIENT_SECRET"),
    )
    if not targets:
        print(f"Unknown parameter key: {key}", file=sys.stderr)
        return 1

    errors = 0
    for prefix, param_key in targets:
        if not put_parameter(
            name=ssm_name(prefix, param_key),
            value=value,
            region=region,
            profile=profile,
            dry_run=dry_run,
        ):
            errors += 1
    return 1 if errors else 0


def upload_all(
    *,
    api_properties: dict[str, str],
    voice_properties: dict[str, str],
    ui_properties: dict[str, str],
    fallback_properties: dict[str, str],
    prefixes: dict[str, str],
    region: str,
    profile: str | None,
    dry_run: bool,
) -> int:
    missing: list[str] = []
    errors = 0

    for key in API_SECRET_KEYS:
        value = api_properties.get(key, "").strip()
        if not value:
            missing.append(ssm_name(prefixes["api"], key))
            continue
        if key == "DATABASE_URL":
            try:
                validate_database_url(value)
            except ValueError as exc:
                print(
                    f"skipping {prefixes['api']}/DATABASE_URL ({exc})",
                    file=sys.stderr,
                )
                continue
        if not put_parameter(
            name=ssm_name(prefixes["api"], key),
            value=value,
            region=region,
            profile=profile,
            dry_run=dry_run,
        ):
            errors += 1

    for key in VOICE_AGENT_SECRET_KEYS:
        value = voice_properties.get(key, "").strip()
        if not value:
            missing.append(ssm_name(prefixes["voice"], key))
            continue
        if not put_parameter(
            name=ssm_name(prefixes["voice"], key),
            value=value,
            region=region,
            profile=profile,
            dry_run=dry_run,
        ):
            errors += 1

    for key in UI_SECRET_KEYS:
        value = ui_properties.get(key, "").strip()
        if not value:
            missing.append(ssm_name(prefixes["ui"], key))
            continue
        if not put_parameter(
            name=ssm_name(prefixes["ui"], key),
            value=value,
            region=region,
            profile=profile,
            dry_run=dry_run,
        ):
            errors += 1

    cognito_properties = merge_sources(fallback_properties, api_properties, ui_properties)

    for key in COGNITO_SECRET_KEYS:
        value = cognito_properties.get(key, "").strip()
        if not value:
            continue
        if not put_parameter(
            name=ssm_name(prefixes["cognito"], key),
            value=value,
            region=region,
            profile=profile,
            dry_run=dry_run,
        ):
            errors += 1

    if missing:
        print("\nMissing values (not uploaded):", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)

    if errors:
        return 1
    if missing and not dry_run:
        print(
            "\nSome parameters were skipped. Add keys to each app's .env and re-run.",
            file=sys.stderr,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync RelayDesk secrets to AWS SSM.")
    parser.add_argument(
        "--properties",
        type=Path,
        default=DEFAULT_PROPERTIES,
        help=f"Properties file (default: {DEFAULT_PROPERTIES})",
    )
    parser.add_argument("--api-env", type=Path, default=REPO_ROOT / "api" / ".env")
    parser.add_argument(
        "--voice-env", type=Path, default=REPO_ROOT / "voice-agent" / ".env"
    )
    parser.add_argument("--ui-env", type=Path, default=REPO_ROOT / "ui" / ".env")
    parser.add_argument(
        "--write-env-properties",
        action="store_true",
        help="Build env.properties from local .env files (no AWS calls)",
    )
    parser.add_argument(
        "--only",
        metavar="KEY",
        help="Upload a single parameter (e.g. OPENAI_API_KEY, DATABASE_URL)",
    )
    parser.add_argument(
        "--from-rds",
        action="store_true",
        help="With --only DATABASE_URL: build URL from RDS terraform outputs",
    )
    parser.add_argument(
        "--from-terraform",
        action="store_true",
        help=(
            "With --only COGNITO_CLIENT_SECRET: read voice M2M secret "
            "from Terraform state"
        ),
    )
    parser.add_argument(
        "--patch-voice-env",
        action="store_true",
        help=(
            "With --only COGNITO_CLIENT_SECRET --from-terraform: write secret "
            "to voice-agent/.env instead of uploading to SSM"
        ),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("RDS_DB_PASSWORD", ""),
        help="RDS password for --from-rds (or RDS_DB_PASSWORD env var)",
    )
    parser.add_argument(
        "--terraform-dir",
        default=str(DEFAULT_TERRAFORM_DIR),
    )
    parser.add_argument(
        "--terraform-resource",
        default=VOICE_COGNITO_TF_RESOURCE,
        help="Terraform resource for --from-terraform COGNITO_CLIENT_SECRET",
    )
    parser.add_argument("--project", default="relaydesk")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    properties = merge_sources(
        parse_env_file(args.properties),
        parse_env_file(args.api_env),
        parse_env_file(args.voice_env),
        parse_env_file(args.ui_env),
    )

    if args.write_env_properties:
        write_env_properties(args.properties, properties)
        return 0

    prefixes = {
        "api": f"/{args.project}/{args.environment}/api",
        "voice": f"/{args.project}/{args.environment}/voice-agent",
        "ui": f"/{args.project}/{args.environment}/ui",
        "cognito": f"/{args.project}/{args.environment}/cognito",
    }
    terraform_dir = Path(args.terraform_dir).resolve()

    if args.only:
        key = args.only.strip()
        if args.from_rds:
            if key != "DATABASE_URL":
                print("--from-rds only applies to DATABASE_URL", file=sys.stderr)
                return 1
            if not args.password.strip():
                print("Provide --password or set RDS_DB_PASSWORD.", file=sys.stderr)
                return 1
            try:
                value = build_database_url_from_rds(
                    terraform_dir=terraform_dir,
                    password=args.password,
                )
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return upload_key(
                key,
                value,
                prefixes=prefixes,
                region=args.region,
                profile=args.profile,
                dry_run=args.dry_run,
            )

        if args.from_terraform:
            if key != "COGNITO_CLIENT_SECRET":
                print(
                    "--from-terraform only applies to COGNITO_CLIENT_SECRET",
                    file=sys.stderr,
                )
                return 1
            try:
                value = cognito_voice_secret_from_terraform(
                    terraform_dir=terraform_dir,
                    resource=args.terraform_resource,
                )
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.patch_voice_env:
                sys.path.insert(0, str(SCRIPT_DIR))
                from setup_common import set_env_value

                voice_env = Path(args.voice_env).resolve()
                if set_env_value(voice_env, "COGNITO_CLIENT_SECRET", value):
                    print(f"patched COGNITO_CLIENT_SECRET in {voice_env}")
                else:
                    print(f"COGNITO_CLIENT_SECRET unchanged in {voice_env}")
                return 0
            return upload_key(
                key,
                value,
                prefixes=prefixes,
                region=args.region,
                profile=args.profile,
                dry_run=args.dry_run,
            )

        value = properties.get(key, "").strip()
        if not value:
            print(
                f"No local value for {key}. Set it in .env or use "
                "--from-rds / --from-terraform where supported.",
                file=sys.stderr,
            )
            return 1
        return upload_key(
            key,
            value,
            prefixes=prefixes,
            region=args.region,
            profile=args.profile,
            dry_run=args.dry_run,
        )

    if not properties:
        print(
            "No values found. Copy each app's .env.example to .env and fill secrets, "
            f"or create {args.properties}.",
            file=sys.stderr,
        )
        return 1

    return upload_all(
        api_properties=parse_env_file(args.api_env),
        voice_properties=parse_env_file(args.voice_env),
        ui_properties=parse_env_file(args.ui_env),
        fallback_properties=properties,
        prefixes=prefixes,
        region=args.region,
        profile=args.profile,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1) from exc
