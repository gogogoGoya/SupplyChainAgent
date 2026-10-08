#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Supply chain simulation portal

This module provides access points to the supply chain simulation system and is responsible only for reading configurations and calling controllers
Implements actual simulation logic.
"""

import os
import sys
from typing import Dict, Any

# Add Item Root Directory to Python Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.controller import Controller
from config.simulation_preset_config import get_active_enterprise_configs
from utils.config_utils import ConfigUtils
from config.simulation_preset_config import get_default_simulation_config

# Use load config method for ConfigUtils
load_config = ConfigUtils.load_config


class SupplyChainSimulation:
    """
    Supply chain simulation entry class
        
    Only to read the configuration and transfer control to Controller to implement the actual simulation logic.
    No longer responsible for the creation and initialization of the components, these functions have been completely moved to Contractor.
        """
    
    def __init__(self, config_path: str = None,enterprise_config=None):
        """
        Initialization Simulation System
                
        Args:
            parameter: Profile path
                """
        # Read Configuration Only
        self.config = load_config(config_path) if config_path else self._get_config_from_modules()
        
        # Create controller, pass configuration to controller
        self.controller = Controller(self.config,enterprise_config)
        
        self.is_running = False
    
    def _get_config_from_modules(self) -> Dict:
        """
        Get configuration from the configuration module under the config directory
                
        Returns:
            dict: Configure Dictionary with all the parameters required for simulation
                """
        return get_default_simulation_config()
    
    def preset_network_structure(self, structure: str = None):
        """
        Preset network configuration
                
        Args:
            stringure: network structure type (linear, star, mesh, etc.), if not specified, use the configuration value
                """
        # Only update configuration, do not directly call controller method
        if structure:
            self.config["network_config"]["structure"] = structure
            print(f"Updated network structure: {structure}")
        else:
            print(f"Current network structure: {self.config['network_config'].get('structure', 'not set')}")
        
        # Note: The actual initialization of the network structure will be handled by the controller when running simulation
    
    async def run_simulation(self, workflow):
        """
        Run Simulation
                
                        
        Returns:
            dict: Simulation results
                """
        
        # Set the status of operation
        self.is_running = True
        
        # Give control to the controller and perform the entire simulation.
        # The controller will read all required parameters from the configuration
        results = await self.controller.run_simulation(workflow=workflow)
        
        # print ("Simulation Done", results)
        return results


def main():
    """
    Main Function Entry
        """
    simulation = SupplyChainSimulation(enterprise_config=get_active_enterprise_configs())
    print(f"Simulation initialized with {len(simulation.controller.enterprises)} enterprises.")

if __name__ == "__main__":
    main()
