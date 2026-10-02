# Architecture and round lifecycle

The simulator separates enterprise decisions from authoritative economic state. An Agent or scripted controller proposes structured actions. The FastAPI environment validates and executes eligible actions through business modules, returns feedback, and advances persistent processes.

`config/simulation_preset_config.py` defines firms, network topology, market mechanisms, initial actions, departments, and runtime policies. `agent/MultiEnterpriseAgentManager.py` constructs firm runtimes and schedules decisions. `simulate/simulation_server.py` exposes the environment to those runtimes. `core/` applies actions and events, `enterprise/modules/` maintains business operations, and `network/exchange_manager.py` mediates B2B proposals and confirmed orders. `runtime/operations/` manages experiment jobs, while `persistence/` records run artifacts and mirrors selected data in SQLite.

One round follows this order:

1. Apply scheduled daily operations and produce role-scoped observations.
2. Run firm analysis and department Agent Skills or scripted policies.
3. Normalize proposals and execute eligible actions in the environment.
4. Process exchange requests, counterparty responses, and order confirmation.
5. Advance production, delivery, settlement, and other multi-round processes.
6. Record observations, actions, feedback, exchange snapshots, and completed state.

Action acceptance, transaction commitment, and fulfilled delivery are distinct events. The environment remains the authority for state changes; firms also affect each other indirectly through markets, peer information, and shared resources.
