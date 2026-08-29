#!/usr/bin/env python3
"""Assign a RelayDesk Cognito role group to a user by email.

Users must have signed in at least once (native or Google SSO) so Cognito has
created their user record. The script removes the user from other RelayDesk
role groups before adding the requested one.

When approving to approved-clients or relaydesk-admins, --business-phone is
required and stored on the client's profile in PostgreSQL.

Roles:
  guest-clients      — default for new SSO sign-ups (view-only; no Cognito group required)
  approved-clients   — upload/delete knowledge-base documents
  relaydesk-admins   — full console and API access

Usage:
  python infra/scripts/approve_cognito_user.py --email deepakdeshwal85@gmail.com --role relaydesk-admins --business-phone +911171366880
  python infra/scripts/approve_cognito_user.py --email you@example.com --role approved-clients --business-phone +911171366880
  python infra/scripts/approve_cognito_user.py --email you@example.com --role guest-clients
  python infra/scripts/approve_cognito_user.py --email you@example.com --revoke
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from rds_tunnel import port_is_open, rds_tunnel_context  # noqa: E402

RELAYDESK_ROLE_GROUPS = (
    "guest-clients",
    "approved-clients",
    "relaydesk-admins",
)

ROLES_REQUIRING_BUSINESS_PHONE = frozenset({"approved-clients", "relaydesk-admins"})


def read_database_url_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            value = stripped.removeprefix("DATABASE_URL=").strip().strip('"').strip("'")
            return value or None
    return None


def fetch_database_url_from_ssm(
    *,
    profile: str | None,
    region: str,
    project: str,
    environment: str,
) -> str | None:
    name = f"/{project}/{environment}/api/DATABASE_URL"
    cmd = aws_cmd(
        profile,
        region,
        "ssm",
        "get-parameter",
        "--name",
        name,
        "--with-decryption",
    )
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout or "{}")
    value = payload.get("Parameter", {}).get("Value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_tunnel_database_url(
    *,
    terraform_dir: Path,
    password: str,
    local_port: int = 15432,
) -> str:
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    outputs = json.loads(result.stdout)

    def _value(key: str) -> str:
        obj = outputs.get(key)
        if not isinstance(obj, dict):
            raise RuntimeError(f"Missing terraform output: {key}")
        raw = obj.get("value")
        if not raw:
            raise RuntimeError(f"Terraform output {key} is empty")
        return str(raw)

    username = _value("rds_master_username")
    db_name = _value("rds_database_name")
    encoded_password = quote_plus(password)
    return (
        f"postgresql+asyncpg://{username}:{encoded_password}"
        f"@127.0.0.1:{local_port}/{db_name}"
    )


def rewrite_database_url_for_tunnel(database_url: str, *, local_port: int = 15432) -> str:
    parsed = urlparse(database_url)
    if not parsed.scheme or not parsed.path:
        raise RuntimeError(f"Invalid DATABASE_URL: {database_url!r}")
    netloc = parsed.netloc
    if "@" in netloc:
        auth, _host = netloc.rsplit("@", 1)
        netloc = f"{auth}@127.0.0.1:{local_port}"
    else:
        netloc = f"127.0.0.1:{local_port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _is_localhost_database_url(database_url: str) -> bool:
    hostname = urlparse(database_url).hostname or ""
    return hostname in {"127.0.0.1", "localhost"}


def resolve_database_url(
    *,
    repo_root: Path,
    profile: str | None,
    region: str,
    project: str,
    environment: str,
    terraform_dir: Path,
    explicit_url: str | None,
    use_tunnel: bool,
    tunnel_port: int,
) -> str:
    candidates: list[tuple[str, str | None]] = []

    if explicit_url:
        candidates.append(("--database-url", explicit_url.strip()))

    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        candidates.append(("DATABASE_URL env var", env_url))

    for label, path in (
        ("api/.env.local", repo_root / "api" / ".env.local"),
        ("api/.env", repo_root / "api" / ".env"),
    ):
        file_url = read_database_url_from_env_file(path)
        if file_url:
            candidates.append((label, file_url))

    ssm_url = fetch_database_url_from_ssm(
        profile=profile,
        region=region,
        project=project,
        environment=environment,
    )
    if ssm_url:
        candidates.append((f"SSM /{project}/{environment}/api/DATABASE_URL", ssm_url))

    password = os.getenv("RDS_DB_PASSWORD", "").strip()
    if password:
        try:
            tunnel_url = build_tunnel_database_url(
                terraform_dir=terraform_dir,
                password=password,
                local_port=tunnel_port,
            )
            candidates.insert(0, ("RDS tunnel URL", tunnel_url))
        except (subprocess.CalledProcessError, RuntimeError, json.JSONDecodeError):
            pass

    for _source, url in candidates:
        if not url:
            continue
        if use_tunnel and "127.0.0.1" not in url and "localhost" not in url:
            try:
                return rewrite_database_url_for_tunnel(url, local_port=tunnel_port)
            except RuntimeError:
                continue
        return url

    raise RuntimeError(
        "DATABASE_URL is required to store the client business phone number.\n"
        "Options:\n"
        "  1. Start the RDS tunnel: python infra/scripts/rds_tunnel.py start\n"
        "  2. Set RDS_DB_PASSWORD and re-run with --use-tunnel\n"
        "  3. Export DATABASE_URL in your shell\n"
        "  4. Run: python infra/scripts/rds_tunnel.py write-env --password <RDS_PASSWORD>\n"
        "  5. For SSM: python infra/scripts/sync_ssm_parameters.py --only DATABASE_URL --from-rds"
    )


def aws_cmd(profile: str | None, region: str, *args: str) -> list[str]:
    cmd = ["aws", *args, "--region", region, "--output", "json"]
    if profile:
        cmd.extend(["--profile", profile])
    return cmd


def run_json(cmd: list[str]) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout or "{}")


def terraform_output(terraform_dir: Path, name: str) -> str | None:
    result = subprocess.run(
        ["terraform", "output", "-raw", name],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def find_username_by_email(
    *,
    profile: str | None,
    region: str,
    user_pool_id: str,
    email: str,
) -> str:
    payload = run_json(
        aws_cmd(
            profile,
            region,
            "cognito-idp",
            "list-users",
            "--user-pool-id",
            user_pool_id,
            "--filter",
            f'email = "{email}"',
        )
    )
    users = payload.get("Users") or []
    if not users:
        raise RuntimeError(
            f"No Cognito user found for email {email!r}. "
            "Ask them to sign in once via SSO, then retry."
        )
    if len(users) > 1:
        usernames = [user.get("Username", "") for user in users]
        raise RuntimeError(
            f"Multiple Cognito users match email {email!r}: {usernames}"
        )
    username = users[0].get("Username")
    if not username:
        raise RuntimeError(f"Cognito user for {email!r} has no Username")
    return str(username)


def remove_from_role_groups(
    *,
    profile: str | None,
    region: str,
    user_pool_id: str,
    username: str,
    dry_run: bool,
) -> None:
    for group_name in RELAYDESK_ROLE_GROUPS:
        if dry_run:
            print(f"[dry-run] would remove {username!r} from {group_name!r}")
            continue
        subprocess.run(
            aws_cmd(
                profile,
                region,
                "cognito-idp",
                "admin-remove-user-from-group",
                "--user-pool-id",
                user_pool_id,
                "--username",
                username,
                "--group-name",
                group_name,
            ),
            check=False,
        )


def set_group_membership(
    *,
    profile: str | None,
    region: str,
    user_pool_id: str,
    username: str,
    group_name: str,
    revoke: bool,
    dry_run: bool,
) -> None:
    if revoke:
        if dry_run:
            print(
                f"[dry-run] would revoke all RelayDesk roles for {username!r} "
                f"(pool {user_pool_id})"
            )
            return
        remove_from_role_groups(
            profile=profile,
            region=region,
            user_pool_id=user_pool_id,
            username=username,
            dry_run=False,
        )
        print(f"Revoked RelayDesk roles for {username!r}")
        return

    if dry_run:
        print(
            f"[dry-run] would assign {username!r} to {group_name!r} "
            f"(pool {user_pool_id})"
        )
        return

    remove_from_role_groups(
        profile=profile,
        region=region,
        user_pool_id=user_pool_id,
        username=username,
        dry_run=False,
    )
    subprocess.run(
        aws_cmd(
            profile,
            region,
            "cognito-idp",
            "admin-add-user-to-group",
            "--user-pool-id",
            user_pool_id,
            "--username",
            username,
            "--group-name",
            group_name,
        ),
        check=True,
    )
    print(f"Assigned {username!r} to group {group_name!r}")


def upsert_client_business_phone(
    *,
    email: str,
    business_phone: str,
    database_url: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    api_dir = repo_root / "api"
    script = f"""
import asyncio
import sys

sys.path.insert(0, "src")

from app.core.config import Settings
from app.db.postgres.client_repository import ClientRepository
from app.db.postgres.session import dispose_engine, get_session_factory, init_engine


async def _run() -> None:
    settings = Settings(database_url={database_url!r})
    init_engine(settings)
    session_factory = get_session_factory()
    try:
        async with session_factory() as session:
            repository = ClientRepository(session)
            client = await repository.set_business_phone(
                client_email_id={email!r},
                client_business_phone_number={business_phone!r},
            )
            print(
                f"Stored business phone {{client.client_business_phone_number!r}} "
                f"for client {{client.client_email_id!r}}"
            )
    finally:
        await dispose_engine()


asyncio.run(_run())
"""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    if _is_localhost_database_url(database_url):
        env["DATABASE_SSL"] = "1"
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=str(api_dir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"Failed to store business phone in database:\n{detail}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assign or revoke a RelayDesk Cognito role for a user by email."
    )
    parser.add_argument("--email", required=True, help="User email in Cognito")
    parser.add_argument(
        "--role",
        choices=RELAYDESK_ROLE_GROUPS,
        default="relaydesk-admins",
        help="RelayDesk role group to assign (default: relaydesk-admins)",
    )
    parser.add_argument(
        "--business-phone",
        help="Client business phone number (required for approved-clients and relaydesk-admins)",
    )
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE"),
        help="AWS CLI profile (or set AWS_PROFILE).",
    )
    parser.add_argument(
        "--user-pool-id",
        help="Cognito user pool ID (default: terraform output cognito_user_pool_id)",
    )
    parser.add_argument(
        "--terraform-dir",
        default="infra/terraform",
        help="Path to Terraform directory for default pool ID lookup",
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL (postgresql+asyncpg://...). Overrides env/SSM when set.",
    )
    parser.add_argument(
        "--use-tunnel",
        action="store_true",
        help="Rewrite remote DATABASE_URL to localhost tunnel port.",
    )
    parser.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Do not auto-start the RDS SSM tunnel (assume it is already running).",
    )
    parser.add_argument(
        "--tunnel-port",
        type=int,
        default=15432,
        help="Local RDS tunnel port when --use-tunnel is set (default: 15432)",
    )
    parser.add_argument("--project", default="relaydesk")
    parser.add_argument("--environment", default="prod")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Remove the user from all RelayDesk role groups",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not email or "@" not in email:
        print("invalid --email", file=sys.stderr)
        return 1

    if not args.revoke and args.role in ROLES_REQUIRING_BUSINESS_PHONE:
        business_phone = (args.business_phone or "").strip()
        if not business_phone:
            print(
                "--business-phone is required when assigning "
                f"{args.role!r}",
                file=sys.stderr,
            )
            return 1

    user_pool_id = args.user_pool_id
    if not user_pool_id:
        user_pool_id = terraform_output(Path(args.terraform_dir).resolve(), "cognito_user_pool_id")
    if not user_pool_id:
        print(
            "Could not resolve user pool ID. Pass --user-pool-id or run from a "
            "configured terraform directory.",
            file=sys.stderr,
        )
        return 1

    username = find_username_by_email(
        profile=args.profile,
        region=args.region,
        user_pool_id=user_pool_id,
        email=email,
    )
    set_group_membership(
        profile=args.profile,
        region=args.region,
        user_pool_id=user_pool_id,
        username=username,
        group_name=args.role,
        revoke=args.revoke,
        dry_run=args.dry_run,
    )
    if (
        not args.revoke
        and not args.dry_run
        and args.role in ROLES_REQUIRING_BUSINESS_PHONE
    ):
        repo_root = Path(__file__).resolve().parents[2]
        database_url = resolve_database_url(
            repo_root=repo_root,
            profile=args.profile,
            region=args.region,
            project=args.project,
            environment=args.environment,
            terraform_dir=Path(args.terraform_dir).resolve(),
            explicit_url=args.database_url,
            use_tunnel=args.use_tunnel,
            tunnel_port=args.tunnel_port,
        )
        if _is_localhost_database_url(database_url):
            profile = args.profile or os.getenv("AWS_PROFILE") or "relaydesk-admin"
            if args.no_tunnel:
                if not port_is_open("127.0.0.1", args.tunnel_port):
                    raise RuntimeError(
                        f"No RDS tunnel on 127.0.0.1:{args.tunnel_port}. "
                        "Start one with: python infra/scripts/rds_tunnel.py start"
                    )
                upsert_client_business_phone(
                    email=email,
                    business_phone=args.business_phone.strip(),
                    database_url=database_url,
                )
            else:
                with rds_tunnel_context(
                    profile=profile,
                    region=args.region,
                    terraform_dir=Path(args.terraform_dir).resolve(),
                    local_port=args.tunnel_port,
                ):
                    upsert_client_business_phone(
                        email=email,
                        business_phone=args.business_phone.strip(),
                        database_url=database_url,
                    )
        else:
            upsert_client_business_phone(
                email=email,
                business_phone=args.business_phone.strip(),
                database_url=database_url,
            )
        print(f"Tell {email} to sign out and sign in again to refresh access.")
    elif not args.revoke and not args.dry_run:
        print(f"Tell {email} to sign out and sign in again to refresh access.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"aws command failed: {exc.stderr or exc}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
