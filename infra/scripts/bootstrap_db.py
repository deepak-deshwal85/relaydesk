#!/usr/bin/env python3
"""Drop all tables, recreate schema, and load Deepak bootstrap seed data.

Destructive — deletes every row in all RelayDesk tables, then inserts:
  - clients: deepakdeshwal85@gmail.com, deepakdeshwal85@yahoo.com
  - shared business phone: 911171366880
  - voice agent configs with Cal.com settings for both clients
  - dummy consumers, call jobs, and call summaries

Usage (from repo root):
  python infra/scripts/bootstrap_db.py --yes
  python infra/scripts/bootstrap_db.py --use-tunnel --password "$RDS_DB_PASSWORD" --yes

  # Or via api venv explicitly:
  cd api && uv run python ../infra/scripts/bootstrap_db.py --yes
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

SEED_FILE = "seed_deepak.sql"


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


async def _run(*, database_url: str, use_tunnel: bool = False) -> None:
    import asyncpg

    sys.path.insert(0, str(SCRIPTS_DIR))
    from db_runner import (
        DB_DIR,
        apply_schema,
        asyncpg_connect_kwargs,
        drop_schema,
        run_sql_file,
        to_asyncpg_dsn,
    )

    dsn = to_asyncpg_dsn(database_url)
    connect_kwargs = asyncpg_connect_kwargs(database_url, use_tunnel=use_tunnel)
    connection = await asyncpg.connect(dsn, **connect_kwargs)
    try:
        await drop_schema(connection)
        await apply_schema(connection)
        seed_path = DB_DIR / SEED_FILE
        count = await run_sql_file(connection, seed_path)
        print(f"Applied seed data ({count} statements) from {seed_path.name}")
    finally:
        await connection.close()


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv if argv is not None else sys.argv[1:])
    _ensure_api_venv(args_list)

    sys.path.insert(0, str(SCRIPTS_DIR))
    from db_runner import load_env, resolve_database_url

    parser = argparse.ArgumentParser(
        description="Drop, recreate, and seed RelayDesk PostgreSQL for Deepak dev data."
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation — this deletes all application data.",
    )
    args = parser.parse_args(args_list)

    if not args.yes:
        print(
            "Refusing to run without --yes. This drops all tables and reloads seed data.",
            file=sys.stderr,
        )
        return 1

    database_url = args.database_url
    if args.use_tunnel:
        if not args.password:
            print(
                "Set RDS_DB_PASSWORD or pass --password when using --use-tunnel.",
                file=sys.stderr,
            )
            return 1
        database_url = build_tunnel_database_url(
            password=args.password,
            username=args.username,
            db_name=args.db_name,
        )

    load_env()
    try:
        database_url = resolve_database_url(database_url or None)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("WARNING: Dropping all RelayDesk tables, recreating schema, loading Deepak seed.")
    try:
        asyncio.run(_run(database_url=database_url, use_tunnel=args.use_tunnel))
    except Exception as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
