#!/usr/bin/env python3
"""Find and optionally remove simulation_runs copies backed by workspace_jobs.

The current operations flow writes the authoritative run artifacts under
ccAgent/CCSDKAgent/workspace_jobs and archives a simplified copy under
ccAgent/CCSDKAgent/simulation_runs. This utility identifies archive copies
whose run_id is present in workspace_jobs and whose non-run_meta files match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PROJECT_ROOT / "ccAgent" / "CCSDKAgent"
DEFAULT_SIMULATION_RUNS = AGENT_ROOT / "simulation_runs"
DEFAULT_WORKSPACE_JOBS = AGENT_ROOT / "workspace_jobs"
DEFAULT_MANIFEST_DIR = DEFAULT_WORKSPACE_JOBS / "_operations"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_id_for_dir(path: Path) -> str:
    meta = read_json(path / "run_meta.json")
    return str(meta.get("run_id") or path.name)


def file_entries(root: Path, *, hash_files: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        if rel_path == "run_meta.json":
            continue
        stat = path.stat()
        entry: dict[str, Any] = {"path": rel_path, "size": stat.st_size}
        if hash_files:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            entry["sha256"] = digest.hexdigest()
        entries.append(entry)
    return entries


def dir_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def build_workspace_index(workspace_jobs: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if not workspace_jobs.exists():
        return index
    for path in sorted(workspace_jobs.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        run_id = run_id_for_dir(path)
        index.setdefault(run_id, []).append(path)
    return index


def scan(
    simulation_runs: Path,
    workspace_jobs: Path,
    *,
    hash_files: bool = False,
) -> dict[str, Any]:
    workspace_index = build_workspace_index(workspace_jobs)
    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for sim_dir in sorted(simulation_runs.iterdir() if simulation_runs.exists() else []):
        if not sim_dir.is_dir():
            continue
        run_id = run_id_for_dir(sim_dir)
        candidates = workspace_index.get(run_id) or []
        if not candidates:
            skipped.append(
                {
                    "simulation_run": sim_dir.name,
                    "run_id": run_id,
                    "reason": "no_matching_workspace_job",
                }
            )
            continue

        sim_entries = file_entries(sim_dir, hash_files=hash_files)
        matched_workspace: Path | None = None
        mismatch_summaries: list[dict[str, Any]] = []
        for workspace_dir in candidates:
            workspace_entries = file_entries(workspace_dir, hash_files=hash_files)
            if sim_entries == workspace_entries:
                matched_workspace = workspace_dir
                break
            sim_paths = {item["path"] for item in sim_entries}
            workspace_paths = {item["path"] for item in workspace_entries}
            mismatch_summaries.append(
                {
                    "workspace_job": workspace_dir.name,
                    "simulation_files": len(sim_entries),
                    "workspace_files": len(workspace_entries),
                    "path_delta": len(sim_paths ^ workspace_paths),
                }
            )

        if matched_workspace is None:
            skipped.append(
                {
                    "simulation_run": sim_dir.name,
                    "run_id": run_id,
                    "reason": "matched_run_id_but_artifacts_differ",
                    "candidates": mismatch_summaries,
                }
            )
            continue

        eligible.append(
            {
                "simulation_run": sim_dir.name,
                "simulation_path": str(sim_dir),
                "workspace_job": matched_workspace.name,
                "workspace_path": str(matched_workspace),
                "run_id": run_id,
                "file_count_excluding_run_meta": len(sim_entries),
                "size_bytes": dir_size_bytes(sim_dir),
            }
        )

    return {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "simulation_runs_dir": str(simulation_runs),
        "workspace_jobs_dir": str(workspace_jobs),
        "comparison_mode": "sha256" if hash_files else "path_and_size",
        "eligible_count": len(eligible),
        "eligible_size_bytes": sum(item["size_bytes"] for item in eligible),
        "eligible": eligible,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def write_manifest(payload: dict[str, Any], manifest_path: Path | None = None) -> Path:
    DEFAULT_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    if manifest_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest_path = DEFAULT_MANIFEST_DIR / f"cleanup_simulation_runs_{stamp}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def write_txt_summary(payload: dict[str, Any], manifest_path: Path) -> Path:
    txt_path = manifest_path.with_suffix(".txt")
    lines = [
        f"created_at: {payload['created_at']}",
        f"comparison_mode: {payload['comparison_mode']}",
        f"eligible_count: {payload['eligible_count']}",
        f"eligible_size_bytes: {payload['eligible_size_bytes']}",
        "",
        "eligible simulation_runs directories:",
    ]
    for item in payload["eligible"]:
        lines.append(
            f"- {item['simulation_run']} -> {item['workspace_job']} "
            f"({item['size_bytes']} bytes)"
        )
    lines.extend(
        [
            "",
            f"skipped_count: {payload['skipped_count']}",
            "skipped directories are retained.",
        ]
    )
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return txt_path


def validate_delete_target(path: Path, simulation_runs: Path) -> Path:
    resolved = path.resolve()
    simulation_root = simulation_runs.resolve()
    if not resolved.is_dir():
        raise ValueError(f"delete target is not a directory: {path}")
    if resolved == simulation_root or simulation_root not in resolved.parents:
        raise ValueError(f"delete target is outside simulation_runs: {path}")
    return resolved


def delete_from_manifest(
    manifest_path: Path,
    simulation_runs: Path,
    workspace_jobs: Path,
    *,
    hash_files: bool = False,
) -> list[str]:
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema: {manifest_path}")

    current = scan(simulation_runs, workspace_jobs, hash_files=hash_files)
    current_eligible = {
        item["simulation_run"]: item
        for item in current["eligible"]
    }
    deleted: list[str] = []
    for item in manifest.get("eligible") or []:
        name = str(item.get("simulation_run") or "")
        if name not in current_eligible:
            raise ValueError(f"manifest item is no longer eligible: {name}")
        target = validate_delete_target(simulation_runs / name, simulation_runs)
        shutil.rmtree(target)
        deleted.append(name)
    return deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean simulation_runs archive copies that are backed by workspace_jobs.",
    )
    parser.add_argument("--simulation-runs", type=Path, default=DEFAULT_SIMULATION_RUNS)
    parser.add_argument("--workspace-jobs", type=Path, default=DEFAULT_WORKSPACE_JOBS)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--hash-files",
        action="store_true",
        help="Compare SHA-256 hashes in addition to relative paths and sizes.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete directories listed in --manifest after revalidation.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required with --delete.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.delete:
        if not args.yes:
            raise SystemExit("--delete requires --yes")
        if args.manifest is None:
            raise SystemExit("--delete requires --manifest")
        deleted = delete_from_manifest(
            args.manifest,
            args.simulation_runs,
            args.workspace_jobs,
            hash_files=args.hash_files,
        )
        print(f"deleted_count={len(deleted)}")
        for name in deleted:
            print(name)
        return 0

    payload = scan(
        args.simulation_runs,
        args.workspace_jobs,
        hash_files=args.hash_files,
    )
    manifest_path = write_manifest(payload, args.manifest)
    txt_path = write_txt_summary(payload, manifest_path)
    print(f"manifest={manifest_path}")
    print(f"summary={txt_path}")
    print(f"eligible_count={payload['eligible_count']}")
    print(f"eligible_size_bytes={payload['eligible_size_bytes']}")
    print(f"skipped_count={payload['skipped_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
