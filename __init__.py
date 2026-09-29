"""
supply_chain_agent - 产业链仿真系统V2.0

这是一个基于事件驱动架构的产业链仿真系统，支持多企业交互和异步协商。
"""

__version__ = "2.0.0"
__author__ = "Supply Chain Agent Team"
__description__ = "产业链仿真系统核心模块"

# 导入主要模块
from supply_chain_agent import config
from supply_chain_agent import core
from supply_chain_agent import data_models
from supply_chain_agent import enterprise
from supply_chain_agent import message
from supply_chain_agent import network
from supply_chain_agent import utils

# 包级别导出
__all__ = [
    "config",
    "core",
    "data_models",
    "enterprise",
    "message",
    "network",
    "utils"
]

# 版本信息
def get_version():
    """获取当前版本号"""
    return __version__