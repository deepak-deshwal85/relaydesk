#!/usr/bin/env python3
"""RDS SSM port-forward and local DATABASE_URL setup.

Usage (from repo root):
  # Start tunnel (blocking — leave terminal open):
  python infra/scripts/rds_tunnel.py
  python infra/scripts/rds_tunnel.py start

  # Write api/.env.local for local API dev:
  python infra/scripts/rds_tunnel.py write-env --password "$RDS_DB_PASSWORD"
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote_plus

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
DEFAULT_LOCAL_PORT = 15432
DEFAULT_ENV_FILE = REPO_ROOT / "api" / ".env.local"
SESSION_MANAGER_PLUGIN_WIN = (
    Path(r"C:\Program Files\Amazon\SessionManagerPlugin\bin")
)


def _aws_env() -> dict[str, str]:
    env = os.environ.copy()
    env["AWS_PAGER"] = ""
    if SESSION_MANAGER_PLUGIN_WIN.is_dir():
        env["PATH"] = f"{SESSION_MANAGER_PLUGIN_WIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def _resolve_profile(explicit: str | None) -> str:
    return (
        explicit
        or os.getenv("PROFILE_NAME")
        or os.getenv("AWS_PROFILE")
        or "relaydesk-admin"
    )


def terraform_outputs(terraform_dir: Path) -> dict[str, object]:
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout or "{}")


def terraform_output_value(outputs: dict[str, object], key: str) -> str:
    entry = outputs.get(key)
    if not isinstance(entry, dict):
        raise RuntimeError(f"Missing terraform output: {key}")
    value = entry.get("value")
    if value is None or value == "" or value == "null":
        raise RuntimeError(f"Terraform output {key!r} is empty")
    return str(value).strip()


def resolve_rds_host(terraform_dir: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    return terraform_output_value(terraform_outputs(terraform_dir), "rds_endpoint")


def port_is_open(host: str, port: int, *, timeout_s: float = 2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, *, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if port_is_open(host, port):
            return
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {host}:{port}")


@contextlib.contextmanager
def rds_tunnel_context(
    *,
    profile: str,
    region: str,
    terraform_dir: Path,
    local_port: int = DEFAULT_LOCAL_PORT,
    instance_id: str | None = None,
    rds_host: str | None = None,
) -> Iterator[None]:
    """Start an RDS SSM port-forward if localhost:local_port is not already open."""
    if port_is_open("127.0.0.1", local_port):
        yield
        return

    remote_host = resolve_rds_host(terraform_dir, rds_host)
    target_instance = resolve_instance_id(
        profile=profile,
        region=region,
        explicit=instance_id,
    )

    print(f"Starting RDS tunnel via {target_instance} -> 127.0.0.1:{local_port}")
    proc = subprocess.Popen(
        [
            "aws",
            "ssm",
            "start-session",
            "--profile",
            profile,
            "--region",
            region,
            "--target",
            target_instance,
            "--document-name",
            "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters",
            f"host={remote_host},portNumber=5432,localPortNumber={local_port}",
        ],
        env=_aws_env(),
    )
    try:
        wait_for_port("127.0.0.1", local_port)
        print(f"RDS tunnel ready on 127.0.0.1:{local_port}")
        yield
    finally:
        print("Stopping RDS tunnel")
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def resolve_instance_id(
    *,
    profile: str,
    region: str,
    explicit: str | None,
) -> str:
    if explicit:
        return explicit.strip()
    result = subprocess.run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--profile",
            profile,
            "--region",
            region,
            "--filters",
            "Name=tag:Name,Values=relaydesk-prod-ecs-api",
            "Name=instance-state-name,Values=running",
            "--query",
            "Reservations[0].Instances[0].InstanceId",
            "--output",
            "text",
            "--no-cli-pager",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=_aws_env(),
    )
    instance_id = (result.stdout or "").strip()
    if not instance_id or instance_id == "None":
        raise RuntimeError(
            "No running relaydesk-prod-ecs-api EC2 instance found. "
            "Start the ECS API ASG first."
        )
    return instance_id


def cmd_start(args: argparse.Namespace) -> int:
    terraform_dir = Path(args.terraform_dir).resolve()
    profile = _resolve_profile(args.profile)
    rds_host = resolve_rds_host(terraform_dir, args.rds_host)
    instance_id = resolve_instance_id(
        profile=profile,
        region=args.region,
        explicit=args.instance_id,
    )

    print("RDS tunnel")
    print(f"  local:  localhost:{args.local_port}")
    print(f"  remote: {rds_host}:5432")
    print(f"  via:    {instance_id} (SSM)")
    print()
    print(
        f"pgAdmin / psql: Host=localhost Port={args.local_port} "
        "DB=relaydesk User=relaydesk_admin"
    )
    print("Leave this terminal open while connected. Press Ctrl+C to stop.")
    print()

    try:
        subprocess.run(
            [
                "aws",
                "ssm",
                "start-session",
                "--profile",
                profile,
                "--region",
                args.region,
                "--target",
                instance_id,
                "--document-name",
                "AWS-StartPortForwardingSessionToRemoteHost",
                "--parameters",
                (
                    f"host={rds_host},portNumber=5432,"
                    f"localPortNumber={args.local_port}"
                ),
            ],
            env=_aws_env(),
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Tunnel failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    return 0


def _write_database_url(path: Path, database_url: str) -> None:
    lines: list[str] = []
    if path.is_file():
        replaced = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                lines.append(f"DATABASE_URL={database_url}")
                replaced = True
            else:
                lines.append(line)
        if not replaced:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"DATABASE_URL={database_url}")
    else:
        lines = [
            "# Generated by infra/scripts/rds_tunnel.py write-env",
            "# Start the tunnel first: python infra/scripts/rds_tunnel.py start",
            f"DATABASE_URL={database_url}",
            "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_write_env(args: argparse.Namespace) -> int:
    password = (args.password or os.getenv("RDS_DB_PASSWORD", "")).strip()
    if not password:
        print("Provide --password or set RDS_DB_PASSWORD.", file=sys.stderr)
        return 1

    terraform_dir = Path(args.terraform_dir).resolve()
    outputs = terraform_outputs(terraform_dir)
    username = terraform_output_value(outputs, "rds_master_username")
    db_name = terraform_output_value(outputs, "rds_database_name")
    encoded = quote_plus(password)
    database_url = (
        f"postgresql+asyncpg://{username}:{encoded}"
        f"@127.0.0.1:{args.local_port}/{db_name}"
    )

    env_path = Path(args.env_file).resolve()
    _write_database_url(env_path, database_url)
    print(f"wrote {env_path}")
    print("Start the tunnel in another terminal:")
    print("  python infra/scripts/rds_tunnel.py start")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RDS SSM tunnel and local DATABASE_URL setup."
    )
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    parser.add_argument(
        "--terraform-dir",
        default=str(DEFAULT_TERRAFORM_DIR),
    )
    parser.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT)
    subparsers = parser.add_subparsers(dest="command")
    # Defaults for running with no subcommand (same as `start`).
    parser.set_defaults(
        func=cmd_start,
        command="start",
        instance_id=None,
        rds_host=None,
    )

    start_parser = subparsers.add_parser(
        "start", help="Open SSM port-forward to RDS (blocking; default command)"
    )
    start_parser.add_argument("--instance-id", default=None)
    start_parser.add_argument("--rds-host", default=None)
    start_parser.set_defaults(func=cmd_start, command="start")

    write_parser = subparsers.add_parser(
        "write-env",
        help="Write api/.env.local DATABASE_URL for tunnel access",
    )
    write_parser.add_argument(
        "--password",
        default=None,
        help="RDS master password (or RDS_DB_PASSWORD env var)",
    )
    write_parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
    )
    write_parser.set_defaults(func=cmd_write_env, command="write-env")

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or str(exc)).strip()
        print(stderr or f"command failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
