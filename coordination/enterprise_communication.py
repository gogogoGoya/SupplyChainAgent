"""Merge optional department communication sidecars into the existing blackboard."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from coordination.communication_protocol import (
    CommunicationEntry,
    deduplicate_entries,
    validate_communications,
)
from coordination.semantic_rule_packs import apply_semantic_rules


class EnterpriseCommunicationCoordinator:
    """Enterprise-private communication extension, not a second blackboard."""

    def __init__(
        self,
        enterprise_workspace: Path,
        enabled_departments: Iterable[str],
        source_departments: Iterable[str] = None,
        validation_mode: str = "off",
        semantic_rule_pack: str = "none",
        semantic_auto_repair: bool = False,
    ):
        self.enterprise_workspace = Path(enterprise_workspace)
        self.enabled_departments = {
            str(item).strip().lower()
            for item in enabled_departments
            if str(item).strip()
        }
        self.source_departments = {
            str(item).strip().lower()
            for item in (source_departments or self.enabled_departments)
            if str(item).strip()
        }
        self.validation_mode = validation_mode
        self.semantic_rule_pack = semantic_rule_pack
        self.semantic_auto_repair = semantic_auto_repair

    def _blackboard_dir(self, round_id: int) -> Path:
        return (
            self.enterprise_workspace
            / "department"
            / "blackboard"
            / f"day{round_id}"
        )

    def _blackboard_path(self, round_id: int) -> Path:
        return self._blackboard_dir(round_id) / "blackboard.json"

    def _merge_report_path(self, round_id: int) -> Path:
        return self._blackboard_dir(round_id) / "communication_merge_report.json"

    @staticmethod
    def _read_json(path: Path, default=None) -> Any:
        if not path.exists():
            return {} if default is None else default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _communication_path(self, department: str, round_id: int) -> Path:
        return (
            self.enterprise_workspace
            / "department"
            / department
            / f"day{round_id}"
            / f"{department}_communication.json"
        )

    def _update_skill_audit(
        self,
        *,
        department: str,
        round_id: int,
        validation_payload: Dict[str, Any],
    ) -> None:
        audit_path = (
            self.enterprise_workspace
            / "department"
            / department
            / f"day{round_id}"
            / "skill_execution_audit.json"
        )
        if not audit_path.exists():
            return
        audit = self._read_json(audit_path, {})
        audit["communication_validation"] = validation_payload
        self._write_json(audit_path, audit)

    def merge_round(self, round_id: int) -> Dict[str, Any]:
        blackboard_path = self._blackboard_path(round_id)
        blackboard = self._read_json(blackboard_path, {})
        # Re-merging must hash the underlying observation snapshot, not the
        # coordination block produced by an earlier merge.
        blackboard.pop("coordination", None)
        blackboard.pop("coordination_hash", None)
        base_snapshot_hash = self._canonical_hash(blackboard)
        validation_results = {}
        all_entries: List[CommunicationEntry] = []
        missing_sidecars = []

        for department in sorted(self.source_departments):
            sidecar_path = self._communication_path(department, round_id)
            if not sidecar_path.exists():
                if self.validation_mode == "strict":
                    missing_sidecars.append(department)
                continue
            payload = self._read_json(sidecar_path, {})
            validation = validate_communications(
                source_department=department,
                payload=payload,
                enabled_departments=self.enabled_departments,
                round_id=round_id,
                mode=self.validation_mode,
            )
            validation_payload = validation.to_dict()
            validation_payload["source_file"] = str(sidecar_path)
            semantic_entries, semantic_issues, semantic_repairs = (
                apply_semantic_rules(
                    entries=validation.entries,
                    rule_pack_id=self.semantic_rule_pack,
                    auto_repair=self.semantic_auto_repair,
                )
            )
            rejected_entry_indexes = sorted(
                {
                    int(issue["entry_index"])
                    for issue in semantic_issues
                    if isinstance(issue.get("entry_index"), int)
                }
            )
            accepted_semantic_entries = semantic_entries
            if self.validation_mode == "strict" and rejected_entry_indexes:
                rejected = set(rejected_entry_indexes)
                accepted_semantic_entries = [
                    entry
                    for index, entry in enumerate(semantic_entries)
                    if index not in rejected
                ]
            validation_payload["entries"] = [
                entry.to_dict() for entry in semantic_entries
            ]
            validation_payload["accepted_entries"] = [
                entry.to_dict() for entry in accepted_semantic_entries
            ]
            validation_payload["rejected_entry_indexes"] = (
                rejected_entry_indexes
            )
            validation_payload["semantic_rule_pack"] = self.semantic_rule_pack
            validation_payload["semantic_issues"] = semantic_issues
            validation_payload["semantic_repairs"] = semantic_repairs
            validation_payload["issues"].extend(semantic_issues)
            validation_payload["repairs"].extend(semantic_repairs)
            validation_payload["ok"] = (
                not validation_payload["issues"]
                or self.validation_mode != "strict"
            )
            validation_results[department] = validation_payload
            all_entries.extend(accepted_semantic_entries)
            self._update_skill_audit(
                department=department,
                round_id=round_id,
                validation_payload=validation_payload,
            )

        unique_entries, duplicates = deduplicate_entries(all_entries)
        entries_by_target: Dict[str, List[Dict[str, Any]]] = {}
        for entry in unique_entries:
            entries_by_target.setdefault(entry.to_department, []).append(
                entry.to_dict()
            )

        issues = [
            {
                **issue,
                "source_department": department,
            }
            for department, result in validation_results.items()
            for issue in result.get("issues", [])
        ]
        issues.extend(
            {
                "code": "missing_sidecar",
                "source_department": department,
            }
            for department in missing_sidecars
        )
        strict_failure = self.validation_mode == "strict" and bool(issues)
        generated_at = datetime.now(timezone.utc).isoformat()
        coordination_payload = {
            "schema_version": "enterprise_communication.v1",
            "round_id": round_id,
            "generated_at": generated_at,
            "validation_mode": self.validation_mode,
            "semantic_rule_pack": self.semantic_rule_pack,
            "semantic_auto_repair": self.semantic_auto_repair,
            "base_snapshot_hash": base_snapshot_hash,
            "entries": [entry.to_dict() for entry in unique_entries],
            "entries_by_target": entries_by_target,
            "duplicates": duplicates,
            "issues": issues,
        }
        blackboard["coordination"] = coordination_payload
        blackboard["coordination_hash"] = self._canonical_hash(
            {
                key: value
                for key, value in coordination_payload.items()
                if key != "generated_at"
            }
        )
        self._write_json(blackboard_path, blackboard)

        report = {
            "schema_version": "communication_merge_report.v1",
            "round_id": round_id,
            "generated_at": generated_at,
            "validation_mode": self.validation_mode,
            "semantic_rule_pack": self.semantic_rule_pack,
            "semantic_auto_repair": self.semantic_auto_repair,
            "ok": not strict_failure,
            "base_snapshot_hash": base_snapshot_hash,
            "coordination_hash": blackboard["coordination_hash"],
            "enabled_departments": sorted(self.enabled_departments),
            "source_departments": sorted(self.source_departments),
            "source_count": len(validation_results),
            "entry_count": len(unique_entries),
            "target_count": len(entries_by_target),
            "duplicate_count": len(duplicates),
            "issue_count": len(issues),
            "missing_sidecars": missing_sidecars,
            "validations": validation_results,
            "blackboard_path": str(blackboard_path),
        }
        self._write_json(self._merge_report_path(round_id), report)
        return report
