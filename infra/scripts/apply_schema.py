#!/usr/bin/env python3
"""Apply idempotent schema updates from infra/scripts/db/schema.sql.

Safe for production — does not drop tables or delete data.

Usage (from repo root):
  python infra/scripts/apply_schema.py
  python infra/scripts/apply_schema.py --use-tunnel --password "$RDS_DB_PASSWORD"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus

SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPTS_DIR.parents[1]
API_DIR = REPO_ROOT / "api"
TUNNEL_HOST = "127.0.0.1"
TUNNEL_PORT = 15432


def _reexec_via_api_venv(argv: list[str]) -> int:
    cmd = ["uv", "run", "python", str(SCRIPT_PATH), *argv]
    return subprocess.run(cmd, cwd=str(API_DIR)).returncode


def _ensure_api_venv(argv: list[str]) -> None:
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        raise SystemExit(_reexec_via_api_venv(argv))


def build_tunnel_database_url(*, password: str, username: str, db_name: str) -> str:
    encoded = quote_plus(password)
    return (
        f"postgresql+asyncpg://{username}:{encoded}"
        f"@{TUNNEL_HOST}:{TUNNEL_PORT}/{db_name}"
    )


async def _run(*, database_url: str) -> None:
    import asyncpg

    sys.path.insert(0, str(SCRIPTS_DIR))
    from db_runner import apply_schema, asyncpg_connect_kwargs, to_asyncpg_dsn

    dsn = to_asyncpg_dsn(database_url)
    connection = await asyncpg.connect(dsn, **asyncpg_connect_kwargs(database_url))
    try:
        await apply_schema(connection)
        print("Schema updates applied successfully.")
    finally:
        await connection.close()


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv if argv is not None else sys.argv[1:])
    _ensure_api_venv(args_list)

    sys.path.insert(0, str(SCRIPTS_DIR))
    from db_runner import load_env, resolve_database_url

    parser = argparse.ArgumentParser(
        description="Apply idempotent RelayDesk PostgreSQL schema updates."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "").strip(),
    )
    parser.add_argument("--use-tunnel", action="store_true")
    parser.add_argument(
        "--username",
        default=os.getenv("RDS_MASTER_USERNAME", "relaydesk_admin"),
    )
    parser.add_argument(
        "--db-name",
        default=os.getenv("RDS_DATABASE_NAME", "relaydesk"),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("RDS_DB_PASSWORD", "").strip(),
    )
    args = parser.parse_args(args_list)

    load_env()

    if args.use_tunnel:
        if not args.password:
            print("RDS password is required with --use-tunnel.", file=sys.stderr)
            return 1
        database_url = build_tunnel_database_url(
            password=args.password,
            username=args.username,
            db_name=args.db_name,
        )
    else:
        try:
            database_url = resolve_database_url(args.database_url or None)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    asyncio.run(_run(database_url=database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
