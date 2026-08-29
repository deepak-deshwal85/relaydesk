"""Shared helpers for infra/scripts/bootstrap_db.py."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
from dotenv import load_dotenv

SCRIPTS_DIR = Path(__file__).resolve().parent
DB_DIR = SCRIPTS_DIR / "db"
REPO_ROOT = SCRIPTS_DIR.parents[1]
API_DIR = REPO_ROOT / "api"


def load_env() -> None:
    load_dotenv(API_DIR / ".env.local")
    load_dotenv(API_DIR / ".env")


def resolve_database_url(explicit: str | None = None) -> str:
    database_url = (explicit or os.getenv("DATABASE_URL", "")).strip()
    if not database_url:
        raise ValueError(
            "DATABASE_URL is required. Set it in api/.env or the environment."
        )
    if not re.match(r"^postgresql(\+asyncpg)?://", database_url):
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL URL "
            "(postgresql+asyncpg://user:pass@host:port/db)."
        )
    return database_url


def to_asyncpg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return database_url


def asyncpg_connect_kwargs(database_url: str, *, use_tunnel: bool = False) -> dict:
    """Return asyncpg.connect kwargs. RDS requires SSL even via SSM port-forward."""
    hostname = urlparse(database_url).hostname or ""
    if not use_tunnel and hostname in {"", "localhost", "127.0.0.1"}:
        return {}

    import ssl

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return {"ssl": ssl_context}


def split_sql_statements(sql_text: str) -> list[str]:
    """Split SQL into statements on semicolons outside quotes and dollar-quoted blocks."""
    statements: list[str] = []
    buffer: list[str] = []
    i = 0
    n = len(sql_text)
    dollar_delim: str | None = None
    in_single = False

    while i < n:
        if dollar_delim is not None:
            if sql_text.startswith(dollar_delim, i):
                buffer.append(dollar_delim)
                i += len(dollar_delim)
                dollar_delim = None
                continue
            buffer.append(sql_text[i])
            i += 1
            continue

        if in_single:
            ch = sql_text[i]
            buffer.append(ch)
            if ch == "'" and i + 1 < n and sql_text[i + 1] == "'":
                buffer.append("'")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if sql_text.startswith("--", i):
            while i < n and sql_text[i] != "\n":
                i += 1
            continue

        if sql_text[i] == "$":
            j = i + 1
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                j += 1
            if j < n and sql_text[j] == "$":
                dollar_delim = sql_text[i : j + 1]
                buffer.append(dollar_delim)
                i = j + 1
                continue

        if sql_text[i] == "'":
            in_single = True
            buffer.append("'")
            i += 1
            continue

        if sql_text[i] == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(sql_text[i])
        i += 1

    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


async def run_sql_file(connection: asyncpg.Connection, path: Path) -> int:
    sql_text = path.read_text(encoding="utf-8")
    statements = split_sql_statements(sql_text)
    for statement in statements:
        await connection.execute(statement)
    return len(statements)


async def drop_schema(connection: asyncpg.Connection) -> int:
    path = DB_DIR / "drop.sql"
    count = await run_sql_file(connection, path)
    print(f"Dropped tables ({count} statements) from {path.name}")
    return count


async def apply_schema(connection: asyncpg.Connection) -> int:
    path = DB_DIR / "schema.sql"
    count = await run_sql_file(connection, path)
    print(f"Applied schema ({count} statements) from {path.name}")
    return count
