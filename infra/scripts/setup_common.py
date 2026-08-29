"""Shared helpers for first-time infrastructure setup (setup_infra.py)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "setup.config.json"

ENV_PATHS = {
    "api": REPO_ROOT / "api" / ".env",
    "ui": REPO_ROOT / "ui" / ".env",
    "voice-agent": REPO_ROOT / "voice-agent" / ".env",
}

ENV_EXAMPLES = {
    "api": REPO_ROOT / "api" / ".env.example",
    "ui": REPO_ROOT / "ui" / ".env.example",
    "voice-agent": REPO_ROOT / "voice-agent" / ".env.example",
}

REQUIRED_API_KEYS = (
    "OPENAI_API_KEY",
    "QDRANT_CLUSTER_ENDPOINT",
    "QDRANT_API_KEY",
)

REQUIRED_UI_KEYS = ("AUTH_SECRET",)

REQUIRED_VOICE_KEYS = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ASSEMBLYAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPGRAM_API_KEY",
)

UI_COGNITO_TF_RESOURCE = "aws_cognito_user_pool_client.ui[0]"
VOICE_COGNITO_TF_RESOURCE = "aws_cognito_user_pool_client.voice_m2m[0]"

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "change-me-to-a-random-secret",
        "your-cluster.aws.cloud.qdrant.io",
        "wss://your-project.livekit.cloud",
        "ap-south-1_xxxxxxxxx",
        "password",
    }
)


def load_config(path: Path | None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Config must be a JSON object: {config_path}")
    return data


def _aws_env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["AWS_PAGER"] = ""
    env["AWS_CLI_AUTO_PROMPT"] = "off"
    plugin = Path(r"C:\Program Files\Amazon\SessionManagerPlugin\bin")
    if plugin.is_dir():
        env["PATH"] = f"{plugin}{os.pathsep}{env.get('PATH', '')}"
    return env


def verify_aws_identity(*, profile: str, region: str, dry_run: bool = False) -> str:
    print("\n==> Verify AWS credentials")
    if dry_run:
        print("    [dry-run] skipped")
        return "000000000000"
    result = subprocess.run(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--profile",
            profile,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ],
        capture_output=True,
        text=True,
        env=_aws_env(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "AWS credentials check failed. Run `aws configure --profile "
            f"{profile}` and retry.\n{(result.stderr or result.stdout).strip()}"
        )
    payload = json.loads(result.stdout or "{}")
    account_id = str(payload.get("Account") or "")
    arn = str(payload.get("Arn") or "")
    print(f"    account: {account_id}")
    print(f"    identity: {arn}")
    if not account_id:
        raise RuntimeError("Could not read AWS account id from sts get-caller-identity")
    return account_id


def ensure_env_files(*, init: bool) -> None:
    missing = [name for name, path in ENV_PATHS.items() if not path.is_file()]
    if not missing:
        return
    if not init:
        raise RuntimeError(
            "Missing local .env files:\n"
            + "\n".join(f"  - {ENV_PATHS[name]}" for name in missing)
            + "\nCopy from .env.example and fill vendor API keys, or pass --init-env."
        )
    for name in missing:
        example = ENV_EXAMPLES[name]
        target = ENV_PATHS[name]
        if not example.is_file():
            raise RuntimeError(f"Missing template: {example}")
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"    created {target.relative_to(REPO_ROOT)} from .env.example")


def read_env_keys(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_VALUES:
        return True
    if "your-" in normalized or "xxxxx" in normalized or "change-me" in normalized:
        return True
    return False


def validate_env_secrets(*, skip_voice: bool, strict: bool = True) -> list[str]:
    """Return list of missing/placeholder keys. Raises when strict and any found."""
    issues: list[str] = []

    api_env = read_env_keys(ENV_PATHS["api"])
    for key in REQUIRED_API_KEYS:
        value = api_env.get(key, "")
        if not value or _is_placeholder(value):
            issues.append(f"api/.env -> {key}")

    ui_env = read_env_keys(ENV_PATHS["ui"])
    for key in REQUIRED_UI_KEYS:
        value = ui_env.get(key, "")
        if not value or _is_placeholder(value):
            issues.append(f"ui/.env -> {key}")

    if not skip_voice:
        voice_env = read_env_keys(ENV_PATHS["voice-agent"])
        for key in REQUIRED_VOICE_KEYS:
            value = voice_env.get(key, "")
            if not value or _is_placeholder(value):
                issues.append(f"voice-agent/.env -> {key}")

    if issues:
        message = (
            "Fill vendor API keys in local .env files before setup:\n"
            + "\n".join(f"  - {item}" for item in issues)
        )
        if strict:
            raise RuntimeError(message)
        print(f"Warning: {message}")
    return issues


def _read_tfvars(terraform_dir: Path) -> dict[str, str]:
    tfvars = terraform_dir / "terraform.tfvars"
    if not tfvars.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in tfvars.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def patch_tfvars_from_config(terraform_dir: Path, config: dict[str, Any]) -> bool:
    """Update placeholder tfvars from setup.config.json. Returns True if file changed."""
    target = terraform_dir / "terraform.tfvars"
    if not target.is_file():
        return False
    content = target.read_text(encoding="utf-8")
    patches = {
        "github_org": config.get("github_org"),
        "github_repo": config.get("github_repo"),
        "ui_domain_name": config.get("ui_domain_name"),
        "aws_region": config.get("aws_region"),
    }
    changed = False
    for key, value in patches.items():
        if not value:
            continue
        str_value = str(value)
        # Quoted string values
        pattern_quoted = rf'^({re.escape(key)}\s*=\s*")[^"]*(")'
        new_content, count = re.subn(
            pattern_quoted,
            rf'\1{str_value}\2',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if count:
            content = new_content
            changed = True
            continue
        # Unquoted values
        pattern_bare = rf'^({re.escape(key)}\s*=\s*)[^\n#]+'
        new_content, count = re.subn(
            pattern_bare,
            rf'\1"{str_value}"',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if count:
            content = new_content
            changed = True
    if changed:
        target.write_text(content, encoding="utf-8")
        print(f"    patched {target.relative_to(REPO_ROOT)} from setup.config.json")
    return changed


def validate_tfvars(terraform_dir: Path, config: dict[str, Any] | None = None) -> None:
    tfvars_path = terraform_dir / "terraform.tfvars"
    if not tfvars_path.is_file():
        raise RuntimeError(
            f"Missing {tfvars_path}. Copy terraform.tfvars.example or pass --init-tfvars."
        )
    if config:
        patch_tfvars_from_config(terraform_dir, config)
    values = _read_tfvars(terraform_dir)
    github_org = values.get("github_org", "")
    if not github_org or "YOUR_GITHUB" in github_org.upper():
        raise RuntimeError(
            "Set github_org in terraform.tfvars (required for GitHub OIDC deploy role). "
            "Add it to setup.config.json or edit terraform.tfvars directly."
        )


def ensure_tfvars(terraform_dir: Path, config: dict[str, Any]) -> None:
    example = terraform_dir / "terraform.tfvars.example"
    target = terraform_dir / "terraform.tfvars"
    if target.is_file():
        print(f"    using existing {target.relative_to(REPO_ROOT)}")
        return
    if not example.is_file():
        raise RuntimeError(f"Missing {example}")
    content = example.read_text(encoding="utf-8")
    patches = {
        "github_org": config.get("github_org"),
        "github_repo": config.get("github_repo"),
        "ui_domain_name": config.get("ui_domain_name"),
        "aws_region": config.get("aws_region"),
    }
    for key, value in patches.items():
        if not value:
            continue
        pattern = rf'^({re.escape(key)}\s*=\s*")[^"]*(")'
        replacement = rf'\1{value}\2'
        content, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
        if count == 0:
            pattern = rf"^({re.escape(key)}\s*=\s*)[^\n#]+"
            content, _ = re.subn(
                pattern, rf'\1"{value}"', content, count=1, flags=re.MULTILINE
            )
    target.write_text(content, encoding="utf-8")
    print(f"    created {target.relative_to(REPO_ROOT)} from example + config")


def terraform_output_raw(terraform_dir: Path, key: str) -> str | None:
    result = subprocess.run(
        ["terraform", "output", "-raw", key],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
        env=_aws_env(),
        check=False,
    )
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    if not value or value == "null":
        return None
    return value


def terraform_state_attr(terraform_dir: Path, resource: str, attr: str) -> str | None:
    result = subprocess.run(
        ["terraform", "state", "show", "-no-color", resource],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
        env=_aws_env(),
        check=False,
    )
    if result.returncode != 0:
        return None
    prefix = f"{attr} "
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped.removeprefix(prefix).strip().strip('"')
            if value.startswith("<<EOT"):
                continue
            return value or None
    return None


def set_env_value(path: Path, key: str, value: str) -> bool:
    """Set or append KEY=value in a dotenv file. Returns True if file changed."""
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    key_prefix = f"{key}="
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        current_key, _, _ = line.partition("=")
        if current_key.strip() == key:
            new_lines.append(f"{key}={value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"{key}={value}")
    new_content = "\n".join(new_lines).rstrip() + "\n"
    old_content = path.read_text(encoding="utf-8") if path.is_file() else ""
    if old_content == new_content:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def patch_env_from_terraform(
    terraform_dir: Path,
    *,
    region: str,
    dry_run: bool = False,
) -> list[str]:
    """Fill Cognito and URL fields in api/ui/voice .env from Terraform outputs."""
    print("\n==> Patch local .env files from Terraform outputs")
    if dry_run:
        print("    [dry-run] skipped")
        return []

    updates: list[tuple[Path, str, str]] = []

    pool_id = terraform_output_raw(terraform_dir, "cognito_user_pool_id")
    ui_client_id = terraform_output_raw(terraform_dir, "cognito_ui_client_id")
    m2m_client_id = terraform_output_raw(terraform_dir, "cognito_m2m_client_id")
    if not m2m_client_id:
        m2m_client_id = terraform_state_attr(
            terraform_dir, VOICE_COGNITO_TF_RESOURCE, "id"
        )
    issuer = terraform_output_raw(terraform_dir, "cognito_issuer")
    ui_url = terraform_output_raw(terraform_dir, "ui_url")
    token_url = terraform_output_raw(terraform_dir, "cognito_token_url")
    if not token_url and pool_id:
        domain = terraform_state_attr(
            terraform_dir, "aws_cognito_user_pool_domain.main[0]", "domain"
        )
        if domain:
            token_url = (
                f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"
            )

    ui_client_secret = terraform_state_attr(
        terraform_dir, UI_COGNITO_TF_RESOURCE, "client_secret"
    )
    voice_client_secret: str | None = None
    try:
        from sync_ssm_parameters import cognito_voice_secret_from_terraform

        voice_client_secret = cognito_voice_secret_from_terraform(
            terraform_dir=terraform_dir,
            resource=VOICE_COGNITO_TF_RESOURCE,
        )
    except (ImportError, RuntimeError, subprocess.CalledProcessError):
        voice_client_secret = terraform_state_attr(
            terraform_dir, VOICE_COGNITO_TF_RESOURCE, "client_secret"
        )

    if pool_id:
        updates.extend(
            [
                (ENV_PATHS["api"], "COGNITO_REGION", region),
                (ENV_PATHS["api"], "COGNITO_USER_POOL_ID", pool_id),
                (ENV_PATHS["api"], "OAUTH_DISABLED", "false"),
            ]
        )
    if ui_client_id:
        updates.append((ENV_PATHS["api"], "COGNITO_UI_CLIENT_ID", ui_client_id))
    if m2m_client_id:
        updates.extend(
            [
                (ENV_PATHS["api"], "COGNITO_M2M_CLIENT_ID", m2m_client_id),
                (ENV_PATHS["voice-agent"], "COGNITO_CLIENT_ID", m2m_client_id),
            ]
        )
    if issuer:
        updates.append((ENV_PATHS["ui"], "COGNITO_ISSUER", issuer))
    if ui_client_id:
        updates.append((ENV_PATHS["ui"], "COGNITO_CLIENT_ID", ui_client_id))
    if ui_client_secret:
        updates.append((ENV_PATHS["ui"], "COGNITO_CLIENT_SECRET", ui_client_secret))
    if ui_url:
        updates.extend(
            [
                (ENV_PATHS["ui"], "AUTH_URL", ui_url),
                (ENV_PATHS["ui"], "RELAYDESK_API_URL_AWS", ui_url),
                (ENV_PATHS["ui"], "AUTH_DISABLE_SSO", "false"),
            ]
        )
    if token_url:
        updates.append((ENV_PATHS["voice-agent"], "COGNITO_TOKEN_URL", token_url))
    if voice_client_secret:
        updates.append(
            (ENV_PATHS["voice-agent"], "COGNITO_CLIENT_SECRET", voice_client_secret)
        )
        updates.append((ENV_PATHS["voice-agent"], "COGNITO_SCOPE", "relaydesk-api/access"))

    changed_keys: list[str] = []
    for path, key, value in updates:
        if set_env_value(path, key, value):
            rel = path.relative_to(REPO_ROOT)
            changed_keys.append(f"{rel} -> {key}")
            print(f"    updated {rel}: {key}")

    if not changed_keys:
        print("    (no changes - values already match Terraform)")
    return changed_keys


def http_check(url: str, *, timeout_s: int = 15) -> tuple[int | None, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def run_health_checks(terraform_dir: Path, *, dry_run: bool = False) -> None:
    print("\n==> Health checks")
    if dry_run:
        print("    [dry-run] skipped")
        return

    ui_url = terraform_output_raw(terraform_dir, "ui_url")
    alb = terraform_output_raw(terraform_dir, "alb_dns_name")
    candidates: list[str] = []
    if ui_url:
        base = ui_url.rstrip("/")
        candidates.extend([f"{base}/api/health", base])
    elif alb:
        candidates.append(f"http://{alb}/api/health")

    if not candidates:
        print("    skipped (no ui_url or alb_dns_name in Terraform outputs)")
        return

    for url in candidates:
        status, err = http_check(url)
        if status is not None and 200 <= status < 400:
            print(f"    OK {status} {url}")
        else:
            detail = err or f"HTTP {status}"
            print(f"    WARN {url} - {detail}")


def print_setup_summary(terraform_dir: Path, *, profile: str, region: str) -> None:
    print("\n" + "=" * 60)
    print("Setup complete - manual follow-ups (if not done yet)")
    print("=" * 60)

    ui_domain = terraform_output_raw(terraform_dir, "ui_domain_name")
    alb = terraform_output_raw(terraform_dir, "alb_dns_name")
    ui_url = terraform_output_raw(terraform_dir, "ui_url")
    github_role = terraform_output_raw(terraform_dir, "github_actions_role_arn")
    hosted_ui = terraform_output_raw(terraform_dir, "cognito_hosted_ui_url")

    if ui_domain and alb:
        print("\nCloudflare DNS (infra/README.md section 6):")
        print(f"  App CNAME -> {alb}  (DNS only / gray cloud first)")
        print("  ACM validation CNAME - see terraform output acm_dns_validation_records")
        print("  SSL mode: Full (strict)")
    elif alb:
        print(f"\nALB (no custom domain): http://{alb}")

    if ui_url:
        print(f"\nUI URL: {ui_url}")
        print(f"  API health: {ui_url.rstrip('/')}/api/health")

    if hosted_ui:
        print("\nCognito sign-in (sign in once before approve_cognito_user.py):")
        print(f"  {hosted_ui[:120]}...")

    print("\nCognito admin approval (after first SSO sign-in):")
    print(
        "  python infra/scripts/approve_cognito_user.py "
        f"--email YOU@example.com --role relaydesk-admins "
        f"--business-phone +1XXXXXXXXXX --profile {profile} --region {region}"
    )

    if github_role:
        print("\nGitHub Actions (optional):")
        print(f"  AWS_ROLE_ARN = {github_role}")
        print(f"  AWS_REGION   = {region}")

    print("\nLiveKit telephony (optional): see NEW_INFRA_SETUP.md Phase 9")
    print("Docs: infra/NEW_INFRA_SETUP.md | infra/README.md")
