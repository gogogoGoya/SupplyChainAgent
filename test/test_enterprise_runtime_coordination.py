import json

from data_config import DepartmentSpec, EnterpriseSpec
from EnterpriseRuntime import EnterpriseRuntime


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_enterprise_runtime_merges_only_when_profile_enables_coordination(tmp_path):
    runtime = EnterpriseRuntime.__new__(EnterpriseRuntime)
    runtime.client_dir = tmp_path
    runtime.enterprise_spec = EnterpriseSpec(
        enterprise_id="Enterprise_A",
        enterprise_name="Enterprise_A",
        departments=[
            DepartmentSpec(
                dept_id="sales",
                role="Sales",
                name="Sales",
                skill_name="sales",
                type="Agent",
            ),
            DepartmentSpec(
                dept_id="hr",
                role="HR",
                name="HR",
                skill_name="hr",
                type="Auto",
            ),
        ],
    )
    workspace = tmp_path / "workspace_multi"
    _write_json(
        workspace / "run_meta.json",
        {
            "scenario_config": {},
            "integration_profiles": {
                "capabilities": {
                    "coordination": {
                        "blackboard_enabled": True,
                        "two_phase_enabled": False,
                        "communication_validation": "warn",
                    }
                }
            },
        },
    )
    enterprise_workspace = workspace / "enterprises" / "Enterprise_A"
    _write_json(
        enterprise_workspace
        / "department"
        / "blackboard"
        / "day0"
        / "blackboard.json",
        {"round_id": 0},
    )
    _write_json(
        enterprise_workspace
        / "department"
        / "sales"
        / "day0"
        / "sales_communication.json",
        {
            "messages": [
                {
                    "to_department": "hr",
                    "message": "Need sales staffing support.",
                    "round_id": 0,
                }
            ]
        },
    )

    report = runtime._merge_department_communications(0)

    assert report["ok"] is True
    assert report["source_departments"] == ["sales"]
    assert report["entry_count"] == 1
