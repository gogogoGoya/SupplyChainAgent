# SupplyChainAgent

SupplyChainAgent simulates multi-enterprise supply chains with role-specific Agent Skills or scripted decisions. A programmatic environment executes business actions and advances inventory, cash, production, delivery, and B2B transactions. The browser interface configures experiments and displays run results.

## Start locally

The clean-install smoke test was verified with Python 3.12.3, Node.js 18.19.1, and npm 9.2.0. Agent-driven runs also require a configured Agent SDK and model gateway; scripted runs do not require model credentials.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd visualization && npm ci && cd ..
./scripts/start_integrated_app.sh
```

The script starts the FastAPI service at `http://127.0.0.1:8000` and the experiment interface at `http://127.0.0.1:3000`. Set `PYTHON_BIN` to another compatible interpreter if needed. Model gateway settings can be provided through environment variables or a local `scripts/.env`; available names are shown in `scripts/.env.example`. Do not commit credentials.

In a second terminal, this two-round scripted smoke test exercises job creation, the multi-enterprise environment, checkpointing, and the operations database mirror without model credentials:

```bash
JOB_ID=$(curl -fsS -X POST http://127.0.0.1:8000/operations/jobs \
  -H 'Content-Type: application/json' \
  --data '{"scenario_id":"beer_game_scripted","planned_total_steps":2,"config_overrides":{"simulation":{"service_total_steps":2,"agent_run_steps":2}}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["job_id"])')
curl -fsS -X POST "http://127.0.0.1:8000/operations/jobs/$JOB_ID/run" \
  -H 'Content-Type: application/json' --data '{}'
curl -fsS "http://127.0.0.1:8000/operations/jobs/$JOB_ID"
```

The final response should report `status: completed` and `completed_steps: 2`. Job dispatch is asynchronous, so query the final URL again if the first response still reports a running job. The browser interface is available at `http://127.0.0.1:3000`.


## Project layout

| Directory | Purpose |
| --- | --- |
| `config/` | Scenario registry, firm specifications, policies, and environment settings |
| `agent/` | Agent orchestration, Skills, scripted decisions, and run handling |
| `core/`, `enterprise/`, `network/` | Economic rules, department operations, and B2B exchange |
| `simulate/` | Simulation API and environment adapter |
| `runtime/`, `persistence/` | Job control, run archives, checkpoints, and the SQLite operations mirror |
| `database/` | Optional SQLAlchemy business models and repository access |
| `visualization/` | React/Vite experiment and analysis interface |
| `test/` | Contract and runtime regression tests |

The active scenario is selected through the experiment interface or `SIMULATION_SCENARIO_ID`. The default is `architecture_linear_chain_short`; the registry also contains bullwhip, cobweb, herding, shared-resource, long-horizon, and single-enterprise cases. The scenario sent to the Agent runtime must match the scenario loaded by the simulation service.

Run artifacts, model messages, logs, and local SQLite files are written below `agent/workspace_jobs/` and are excluded from Git. This repository contains executable templates but no completed simulation data.

## Documentation

- [Architecture and round lifecycle](docs/architecture.md)
- [Scenarios and configuration](docs/configuration.md)
- [Firm agents and Skills](docs/agents.md)
- [Database storage](docs/database.md)
- [Experiment interface and artifacts](docs/interface_and_artifacts.md)

Run regression tests with `python -m pytest test/`. Build the frontend with `cd visualization && npm run build`.

This source release is under the [MIT License](LICENSE). Completed experiment data are distributed separately and are not required for the scripted smoke test.
