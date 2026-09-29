"""Command line entry point for lightweight operations control."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Dict, Iterable, Optional, TextIO

from .api import OperationsAPI, ProfileLoader, RepositoryFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operations",
        description="Manage simulation experiment jobs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a queued experiment job.")
    create.add_argument("--scenario-id", required=True)
    create.add_argument("--steps", type=int, default=None)
    create.add_argument("--tag", action="append", dest="tags", default=[])
    create.add_argument("--requested-by", default=None)
    create.add_argument("--job-id", default=None)

    start = subparsers.add_parser("start", help="Mark a queued job as running.")
    start.add_argument("job_id")
    start.add_argument("--scenario-id", default=None)
    start.add_argument("--run-id", default=None)
    start.add_argument("--worker-id", default=None)
    start.add_argument("--artifact-root", default=None)

    stop = subparsers.add_parser("stop", help="Request safe stop after a full round.")
    stop.add_argument("job_id")
    stop.add_argument("--scenario-id", default=None)
    stop.add_argument("--reason", required=True)
    stop.add_argument("--requested-by", default=None)

    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="Record a full-round checkpoint for a running job.",
    )
    checkpoint.add_argument("job_id")
    checkpoint.add_argument("--scenario-id", default=None)
    checkpoint.add_argument("--completed-steps", type=int, required=True)
    checkpoint.add_argument("--last-complete-round", type=int, default=None)
    checkpoint.add_argument("--checkpoint-uri", default=None)
    checkpoint.add_argument("--artifact-root", default=None)
    checkpoint.add_argument("--details-json", default=None)

    list_jobs = subparsers.add_parser("list", help="List experiment jobs.")
    list_jobs.add_argument("--scenario-id", default=None)
    list_jobs.add_argument("--status", default=None)
    list_jobs.add_argument("--active-only", action="store_true")
    list_jobs.add_argument("--limit", type=int, default=None)

    get = subparsers.add_parser("get", help="Get a single experiment job.")
    get.add_argument("job_id")
    get.add_argument("--scenario-id", default=None)

    run_job = subparsers.add_parser("run-job", help="Run a queued job in this process.")
    run_job.add_argument("job_id")
    run_job.add_argument("--scenario-id", default=None)
    run_job.add_argument("--worker-id", default=None)
    run_job.add_argument("--client-dir", default=None)
    run_job.add_argument("--workspace-dir", default=None)

    return parser


def run_command(api: OperationsAPI, args: argparse.Namespace) -> Dict[str, Any]:
    if args.command == "create":
        return api.create_experiment(
            scenario_id=args.scenario_id,
            planned_total_steps=args.steps,
            tags=args.tags,
            requested_by=args.requested_by,
            job_id=args.job_id,
        )
    if args.command == "start":
        return api.start_experiment(
            args.job_id,
            scenario_id=args.scenario_id,
            run_id=args.run_id,
            worker_id=args.worker_id,
            artifact_root=args.artifact_root,
        )
    if args.command == "stop":
        return api.request_stop(
            args.job_id,
            scenario_id=args.scenario_id,
            reason=args.reason,
            requested_by=args.requested_by,
        )
    if args.command == "checkpoint":
        details = {}
        if args.details_json:
            details = json.loads(args.details_json)
        return api.record_checkpoint(
            args.job_id,
            scenario_id=args.scenario_id,
            completed_steps=args.completed_steps,
            last_complete_round=args.last_complete_round,
            checkpoint_uri=args.checkpoint_uri,
            artifact_root=args.artifact_root,
            details=details,
        )
    if args.command == "list":
        return api.list_jobs(
            scenario_id=args.scenario_id,
            status=args.status,
            active_only=args.active_only,
            limit=args.limit,
        )
    if args.command == "get":
        return api.get_job(args.job_id, scenario_id=args.scenario_id)
    if args.command == "run-job":
        return api.run_job(
            args.job_id,
            scenario_id=args.scenario_id,
            worker_id=args.worker_id,
            client_dir=args.client_dir,
            workspace_dir=args.workspace_dir,
        )
    return {
        "ok": False,
        "error": {
            "type": "ValueError",
            "message": f"Unsupported command: {args.command}",
        },
    }


def main(
    argv: Optional[Iterable[str]] = None,
    *,
    repository: Any = None,
    repository_factory: RepositoryFactory = None,
    profile_loader: ProfileLoader = None,
    scenario_loader: Callable[[str], Dict[str, Any]] = None,
    output: TextIO = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    api = OperationsAPI(
        repository,
        repository_factory=repository_factory,
        profile_loader=profile_loader,
        scenario_loader=scenario_loader,
    )
    response = run_command(api, args)
    stream = output or sys.stdout
    stream.write(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    stream.write("\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
