"""
配置目录对外导出入口。

目录内当前长期维护的三份核心配置文件为：
- `environment_config.py`：运行环境级共享配置
- `module_config.py`：六个业务模块自身参数
- `simulation_preset_config.py`：多企业模拟场景级固定数据
"""

from .simulation_preset_config import (
    ACTIVE_SCENARIO_ID,
    AUTO_HR_POLICY,
    AUTO_INVENTORY_POLICY,
    DEFAULT_ACTIVE_SCENARIO_ID,
    DEFAULT_AGENT_MODEL_NAME_LIST,
    DEFAULT_AGENT_RUN_STEPS,
    DEFAULT_BEER_GAME_CUSTOMER_DELIVERY_LEAD_TIME,
    DEFAULT_BEER_GAME_DEMAND_SERIES,
    DEFAULT_BEER_GAME_PRODUCT_ID,
    DEFAULT_BEER_GAME_UNIT_PRICE,
    DEFAULT_COBWEB_CONFIG,
    DEFAULT_HERDING_CONFIG,
    EXTERNAL_MARKET_ORDER_POLICY,
    DEFAULT_MARKET_DEMAND_MODE,
    DEFAULT_MAX_DEPARTMENT_CONCURRENCY,
    DEFAULT_MAX_ENTERPRISE_CONCURRENCY,
    DEFAULT_SERVICE_TOTAL_STEPS,
    DEFAULT_SHARED_RESOURCE_CONFIG,
    HERDING_EXPERIMENT_POLICY,
    LEGACY_MARKET_DEMAND_MODE_BEER_GAME,
    MARKET_DEMAND_MODE_SCHEDULED_EXTERNAL,
    SIMULATION_SCENARIO_ENV_VAR,
    SHARED_RESOURCE_GOVERNANCE_POLICY,
    get_active_enterprise_specs,
    get_active_enterprise_configs,
    get_active_scenario_id,
    get_active_scenario_metadata,
    get_agent_enterprise_layout,
    get_available_scenarios,
    get_auto_policy_config,
    get_daily_actions,
    get_default_market_config,
    get_default_simulation_config,
    get_initial_action_batches,
    get_runtime_injection_config,
    get_scenario_config,
    get_static_command_payloads,
    normalize_market_demand_mode,
)
from .integration_profiles import (
    DEFAULT_INTEGRATION_PROFILES,
    get_scenario_integration_profiles,
    resolve_integration_profiles,
    validate_integration_profiles,
)
