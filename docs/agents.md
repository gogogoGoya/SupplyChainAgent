# Firm agents and Skills

An enterprise runtime combines an analyst, role-specific departments, and private coordination. `EnterpriseRuntime.py` supplies working paths and observations; `MultiEnterpriseAgentManager.py` coordinates multiple firms; `SingleEnterpriseAgentManager.py` supports controlled single-firm runs.

The analyst reads authorized enterprise state and produces a structured analysis. Department Skills then consider their observations and coordination context, write action proposals, and receive environment execution feedback. The runtime records both accepted and rejected actions for subsequent decisions. Skills and action examples are under `ccAgent/CCSDKAgent/.claude/skills/` and cover analyst, buyer, seller, procurement, production, sales, finance, and staffing roles.

`scripted_rule_runner.py` implements deterministic decision policies through the same action path. These policies differ from the fixed JSON warm-up actions in `static_commands/single_enterprise/`, which only establish starting states. Model credentials are supplied through local environment settings and are never part of committed templates.
