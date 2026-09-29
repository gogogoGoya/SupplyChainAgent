# Experiment interface and artifacts

`visualization/` contains the React/Vite interface for selecting scenarios, setting controller conditions, starting and stopping jobs, and inspecting firm and system outcomes. Views cover enterprise operations, B2B exchange, order propagation, market price dynamics, herding, shared resources, and long-horizon evolution.

The frontend proxies `/operations` requests to the FastAPI service. During local development Vite serves files from ignored run folders for charts and detailed inspection. These folders can contain model messages and full operating state, so only reviewed exports should be shared.

| Ignored local path | Contents |
| --- | --- |
| `ccAgent/CCSDKAgent/workspace_jobs/` | Job metadata, per-firm output, public snapshots, and archives |
| `ccAgent/CCSDKAgent/workspace_multi/` | Active multi-enterprise working state |
| `ccAgent/CCSDKAgent/simulation_runs/` | Legacy local archives, when present |
| `ccAgent/CCSDKAgent/workspace_jobs/_operations/` | SQLite operations mirror |

A fresh checkout contains source and executable templates, but no completed experiments, checkpoints, conversations, or operational databases.
