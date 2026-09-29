"""
供应链模拟系统示例模块

本模块提供供应链模拟系统的启动入口，支持预设企业网络架构、
注册企业及功能部门，并在时间轴上模拟企业运营。
包含模拟系统的启动入口和配置示例。
"""

from .simulation import SupplyChainSimulation, main

__all__ = ['SupplyChainSimulation', 'main']
__version__ = '1.0.0'