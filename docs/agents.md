# Firm agents and Skills

An enterprise runtime combines an analyst, role-specific departments, and private coordination. `agent/EnterpriseRuntime.py` supplies working paths and observations; `agent/MultiEnterpriseAgentManager.py` coordinates multiple firms. `runtime/single_enterprise/orchestrator.py` reuses the enterprise runtime for controlled single-firm runs, with `agent/SingleEnterpriseAgentManager.py` as its direct CLI entry point.

The analyst reads authorized enterprise state and produces a structured analysis. Department Skills then consider their observations and coordination context, write action proposals, and receive environment execution feedback. The runtime records both accepted and rejected actions for subsequent decisions. Skills and action examples are under `agent/.claude/skills/` and cover analyst, buyer, seller, procurement, production, sales, finance, and staffing roles.

`agent/scripted_rule_runner.py` implements deterministic decision policies through the same action path. These policies differ from the fixed JSON warm-up actions in `agent/static_commands/single_enterprise/`, which only establish starting states. The files in `agent/workspace/` are runtime templates; generated jobs, messages, and logs are ignored. Model credentials are supplied through local environment settings and are never part of committed templates.
