"""
运行环境配置中心。

这个文件只放“跨模块共享、偏运行时”的配置，主要包括：
- 仿真时间推进规则
- 本地 HTTP / Agent 网关接入地址
- Agent SDK 默认连接参数

不放在这里的数据：
- 四家企业、Beer Game 需求、初始化动作、每日固定动作
  这些统一放在 `simulation_preset_config.py`
- 各业务模块自己的阈值和时间消耗
  这些统一放在 `module_config.py`
"""

import json
import os
import re
from pathlib import Path


def _load_runtime_env_file() -> None:
    """Load non-empty values from scripts/.env without overriding shell env."""
    env_path = Path(__file__).resolve().parents[1] / "scripts" / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _first_env_value(*names: str) -> str:
    for name in names:
        value = _env_value(name)
        if value:
            return value
    return ""


def _clean_model_name(value: object) -> str:
    """Return a plain model id, dropping malformed JSON/list punctuation."""
    text = str(value or "").strip().strip('"').strip("'").strip()
    text = text.strip("[]{}()").strip().strip('"').strip("'").strip()
    if not text:
        return ""
    if any(char in text for char in "[]{}\"'"):
        return ""
    return text


def _parse_model_list_env(raw_value: str) -> list:
    """Parse ANTHROPIC_MODEL_LIST from JSON, comma list, or lightly malformed .env."""
    raw = str(raw_value or "").strip()
    if not raw:
        return []

    candidates = []
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None

    if isinstance(parsed, list):
        candidates = parsed
    elif isinstance(parsed, str):
        candidates = re.split(r"[,;\s]+", parsed)
    else:
        normalized = raw.strip().strip('"').strip("'").strip()
        if normalized.startswith("[") and normalized.endswith("]"):
            normalized = normalized[1:-1]
        normalized = normalized.replace('"', "").replace("'", "")
        candidates = re.split(r"[,;\s]+", normalized)

    result = []
    seen = set()
    for candidate in candidates:
        model_name = _clean_model_name(candidate)
        if model_name and model_name not in seen:
            result.append(model_name)
            seen.add(model_name)
    return result


_load_runtime_env_file()


class EnvironmentConfig:
    """
    跨模块运行环境配置。

    使用范围：
    - `core/async_time_manager.py`：读取时间推进常量
    - `agent/*`：读取服务地址、模型网关地址与默认模型连接参数
    - `simulate/*`：通过环境服务 URL 对接本地仿真服务

    设计边界：
    - 这里只保留“运行环境级”的共享配置
    - `workspace` / `workspace_multi` 这类目录名按当前约定保留在各自模块中，
      不额外抽到这里统一管理
    """

    # ==================== 仿真时间配置 ====================
    # 仿真起始时刻。当前以“第 0 天 09:00”作为开局时间。
    START_TICK = 9 * 60 * 60
    # 一天对应的 tick 数。当前按真实 24 小时换算。
    TICKS_PER_DAY = 24 * 60 * 60
    # 工作日开始时刻。`AsyncTimeManager` 会据此跳转到下一个工作日开始。
    ON_WORK_PER_DAY = 9 * 60 * 60
    # 工作日结束时刻。用于判定是否已下班。
    OFF_WORK_PER_DAY = 17 * 60 * 60

    # 向后兼容旧命名，避免影响已存在调用。
    OnWork_PER_DAY = ON_WORK_PER_DAY
    OffWork_PER_DAY = OFF_WORK_PER_DAY

    # ==================== 本地服务接入配置 ====================
    # 仿真 HTTP 服务地址。`StaticUtils` / `MultiTenantUtils` 通过它请求 `/state`、`/execute` 等接口。
    SIMULATION_API_BASE_URL = _env_value("SIMULATION_API_BASE_URL")
    # Agent / 模型网关地址。多企业与单企业 Agent 都通过它连接 Claude Agent SDK 网关。
    LOCAL_AGENT_GATEWAY_BASE_URL = _first_env_value("ANTHROPIC_BASE_URL", "AGENT_GATEWAY_BASE_URL")
    # 代理绕过配置，由 `scripts/.env` 或宿主环境显式提供。
    LOCAL_NO_PROXY = _first_env_value("NO_PROXY", "no_proxy")

    # ==================== Agent 默认连接参数 ====================
    # 模型名与认证信息只从统一环境入口读取，不保留旧版本硬编码 fallback。
    DEFAULT_AGENT_MODEL = _env_value("ANTHROPIC_MODEL")
    DEFAULT_CEO_MODEL = _env_value("ANTHROPIC_CEO_MODEL") or DEFAULT_AGENT_MODEL
    DEFAULT_AGENT_MODEL_LIST = _parse_model_list_env(_env_value("ANTHROPIC_MODEL_LIST"))
    DEFAULT_AGENT_AUTH_TOKEN = _first_env_value("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")

    @classmethod
    def get_agent_env(cls) -> dict:
        """Return non-empty Agent SDK env values from the unified config."""
        values = {
            "ANTHROPIC_BASE_URL": cls.LOCAL_AGENT_GATEWAY_BASE_URL,
            "ANTHROPIC_MODEL": cls.DEFAULT_AGENT_MODEL,
            "ANTHROPIC_AUTH_TOKEN": cls.DEFAULT_AGENT_AUTH_TOKEN,
            "ANTHROPIC_API_KEY": cls.DEFAULT_AGENT_AUTH_TOKEN,
            "NO_PROXY": cls.LOCAL_NO_PROXY,
            "no_proxy": cls.LOCAL_NO_PROXY,
        }
        return {key: value for key, value in values.items() if value}

    @classmethod
    def missing_agent_env_keys(cls) -> list:
        """Keys required for Agent Skill mode to connect to Agent Environment."""
        required = {
            "ANTHROPIC_BASE_URL": cls.LOCAL_AGENT_GATEWAY_BASE_URL,
            "ANTHROPIC_MODEL": cls.DEFAULT_AGENT_MODEL,
            "ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY": cls.DEFAULT_AGENT_AUTH_TOKEN,
        }
        return [key for key, value in required.items() if not value]
