#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
供应链模拟入口

这个模块提供了供应链模拟系统的入口点，仅负责读取配置并调用控制器
执行实际的模拟逻辑。
"""

import os
import sys
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.controller import Controller
from config.simulation_preset_config import get_active_enterprise_configs
from utils.config_utils import ConfigUtils
from config.simulation_preset_config import get_default_simulation_config

# 使用ConfigUtils类的load_config方法
load_config = ConfigUtils.load_config


class SupplyChainSimulation:
    """
    供应链模拟入口类
    
    仅负责读取配置并将控制权转交给Controller执行实际的模拟逻辑。
    不再负责组件的创建和初始化，这些职责已完全移至Controller。
    """
    
    def __init__(self, config_path: str = None,enterprise_config=None):
        """
        初始化模拟系统
        
        Args:
            config_path: 配置文件路径
        """
        # 仅读取配置
        self.config = load_config(config_path) if config_path else self._get_config_from_modules()
        
        # 创建控制器，将配置传递给控制器
        self.controller = Controller(self.config,enterprise_config)
        
        self.is_running = False
    
    def _get_config_from_modules(self) -> Dict:
        """
        从config目录下的配置模块获取配置
        
        Returns:
            dict: 配置字典，包含模拟所需的所有参数
        """
        return get_default_simulation_config()
    
    def preset_network_structure(self, structure: str = None):
        """
        预设网络结构配置
        
        Args:
            structure: 网络结构类型 (linear, star, mesh等)，如果不指定则使用配置中的值
        """
        # 只更新配置，不直接调用控制器方法
        if structure:
            self.config["network_config"]["structure"] = structure
            print(f"已更新网络结构配置: {structure}")
        else:
            print(f"当前网络结构配置: {self.config['network_config'].get('structure', '未设置')}")
        
        # 注意：网络结构的实际初始化将由控制器在run_simulation时处理
    
    async def run_simulation(self, workflow):
        """
        运行模拟
        
            
        Returns:
            dict: 模拟结果
        """
        
        # 设置运行状态
        self.is_running = True
        
        # 将控制权完全交给控制器，由控制器执行整个模拟过程
        # 控制器会从配置中读取所有需要的参数
        results = await self.controller.run_simulation(workflow=workflow)
        
        # print("模拟完成",results)
        return results


def main():
    """
    主函数入口
    """
    simulation = SupplyChainSimulation(enterprise_config=get_active_enterprise_configs())
    print(f"Simulation initialized with {len(simulation.controller.enterprises)} enterprises.")

if __name__ == "__main__":
    main()
