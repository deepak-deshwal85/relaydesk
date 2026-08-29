#!/usr/bin/env python3
"""Build and deploy API, UI, and voice-agent to ECS.

Default: parallel + fast (downtime OK, ECR layer cache, stop old tasks).

Usage (from repo root):
  python infra/scripts/deploy_all.py
  python infra/scripts/deploy_all.py --only api
  python infra/scripts/deploy_all.py --only api,ui
  python infra/scripts/deploy_all.py --safe
  python infra/scripts/deploy_all.py --sequential
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_common import (  # noqa: E402
    DEPLOY_TARGETS,
    DeployTarget,
    deploy_service,
    resolve_profile,
)

DEPLOY_ORDER = ("api", "ui", "voice-agent")


def _deploy_one(
    target: DeployTarget,
    *,
    profile: str,
    region: str,
    image_tag: str | None,
    terraform_dir: Path,
    dry_run: bool,
    build_only: bool,
    skip_deploy: bool,
    fast: bool,
) -> tuple[str, str | None]:
    try:
        deploy_service(
            target,
            profile=profile,
            region=region,
            image_tag=image_tag,
            terraform_dir=terraform_dir,
            dry_run=dry_run,
            build_only=build_only,
            skip_deploy=skip_deploy,
            fast=fast,
        )
        return target.name, None
    except Exception as exc:
        return target.name, str(exc)


def _deploy_sequential(
    targets: list[DeployTarget],
    **kwargs: object,
) -> int:
    for target in targets:
        print(f"\n{'=' * 60}\nDeploy {target.name}\n{'=' * 60}")
        _, error = _deploy_one(target, **kwargs)  # type: ignore[arg-type]
        if error:
            print(f"FAIL {target.name} deploy failed: {error}", file=sys.stderr)
            return 1
    return 0


def _deploy_parallel(targets: list[DeployTarget], **kwargs: object) -> int:
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {
            pool.submit(_deploy_one, target, **kwargs): target.name  # type: ignore[arg-type]
            for target in targets
        }
        for future in as_completed(futures):
            service, error = future.result()
            if error:
                failed.append(service)
                print(f"FAIL {service} deploy failed: {error}", file=sys.stderr)
            else:
                print(f"OK {service} deploy finished")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build and deploy API, UI, and voice-agent to ECS "
            "(parallel + fast by default)"
        )
    )
    parser.add_argument(
        "--only",
        help="Comma-separated services: api, ui, voice-agent (default: all)",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Deploy one service at a time",
    )
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument(
        "--image-tag",
        default=None,
        help="ECR tag for all services (default: from running ECS task)",
    )
    parser.add_argument(
        "--safe",
        action="store_true",
        help="Slower rolling deploy (keep old task until new is healthy)",
    )
    parser.add_argument("--terraform-dir", default="infra/terraform")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--skip-deploy", action="store_true")
    args = parser.parse_args()

    if args.only:
        selected = [part.strip() for part in args.only.split(",") if part.strip()]
        unknown = [name for name in selected if name not in DEPLOY_TARGETS]
        if unknown:
            print(f"Unknown service(s): {', '.join(unknown)}", file=sys.stderr)
            return 1
        service_names = [name for name in DEPLOY_ORDER if name in selected]
    else:
        service_names = list(DEPLOY_ORDER)

    targets = [DEPLOY_TARGETS[name] for name in service_names]
    fast = not args.safe
    profile = resolve_profile(args.profile)
    terraform_dir = Path(args.terraform_dir)

    print(
        f"Deploy mode: {'safe (rolling)' if args.safe else 'fast (downtime OK)'} | "
        f"services: {', '.join(service_names)}"
    )

    deploy_kwargs = {
        "profile": profile,
        "region": args.region,
        "image_tag": args.image_tag,
        "terraform_dir": terraform_dir,
        "dry_run": args.dry_run,
        "build_only": args.build_only,
        "skip_deploy": args.skip_deploy,
        "fast": fast,
    }

    if args.sequential:
        code = _deploy_sequential(targets, **deploy_kwargs)
    else:
        code = _deploy_parallel(targets, **deploy_kwargs)

    if code == 0:
        print("\nAll selected services deployed successfully")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
