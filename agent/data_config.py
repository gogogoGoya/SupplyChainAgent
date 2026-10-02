from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any

# ============================================================
# 数据结构
# ============================================================

@dataclass
class DepartmentSpec:
    """部门配置"""
    dept_id: str
    role: str
    name: str
    skill_name: str
    enabled: bool = True
    retry_limit: int = 3
    timeout: int = 120
    metadata: Dict[str, Any] = field(default_factory=dict)
    type: str = "Auto"
    need_trade: bool = False


@dataclass
class EnterpriseSpec:
    """企业配置"""
    enterprise_id: str
    enterprise_name: str
    analyst_skill_name: str = "analyst"
    departments: List[DepartmentSpec] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
