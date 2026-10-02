from agent.MultiEnterpriseAgentManager import MultiEnterpriseClaudeManager


def test_model_assignment_never_truncates_dynamic_enterprise_counts():
    assert MultiEnterpriseClaudeManager._resolve_model_name_list(["m1"], 1) == ["m1"]
    assert MultiEnterpriseClaudeManager._resolve_model_name_list(
        ["m1", "m2"], 5
    ) == ["m1", "m2", "m2", "m2", "m2"]
    assert len(
        MultiEnterpriseClaudeManager._resolve_model_name_list(["m1"], 8)
    ) == 8


def test_model_assignment_truncates_surplus_models_without_changing_enterprises():
    assert MultiEnterpriseClaudeManager._resolve_model_name_list(
        ["m1", "m2", "m3"], 2
    ) == ["m1", "m2"]
    assert MultiEnterpriseClaudeManager._resolve_model_name_list(["m1"], 0) == []

