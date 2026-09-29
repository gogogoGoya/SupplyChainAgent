# Scenarios and configuration

`config/simulation_preset_config.py` is the scenario registry and source of the default simulation settings. `SIMULATION_SCENARIO_ID` overrides `DEFAULT_ACTIVE_SCENARIO_ID` for direct runs. The experiment interface sends the selected scenario and controller condition to the operations API, which stores the resolved configuration with each job.

| Configuration area | Responsibility |
| --- | --- |
| `meta`, `simulation` | Scenario identity, round count, market mode, and products |
| `enterprise_specs` | Firms, suppliers, initial cash, staff, inventory, capacity, and products |
| `agent_enterprise_layout` | Enabled departments and Agent or scripted control |
| `initial_action_batches`, `daily_actions` | Starting conditions and scheduled operations |
| `runtime_injection` | Decision context, information visibility, and mechanism policy |
| `auto_policy` | Scripted decision and fallback settings |

Trade routes require explicit supplier relationships and compatible products. Supported families include supply-chain topology checks, bullwhip propagation, cobweb price feedback, herding, renewable shared resources, long-horizon shocks, and controlled single-enterprise cases. Single-enterprise JSON warm-up actions establish case-specific states before decision control begins.

To introduce a scenario, declare firms and products, choose its market mechanism, define initialization and department policies, and exercise the resulting configuration through the operations interface and contract tests.
