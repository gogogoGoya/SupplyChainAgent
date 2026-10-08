"""
Example module of supply chain simulation system

This module provides access to the supply chain simulation system to support the pre-set enterprise network structure,
Register enterprise and function department and simulate enterprise on the time axis.
Include examples of start-up access and configuration of analog systems.
"""

from .simulation import SupplyChainSimulation, main

__all__ = ['SupplyChainSimulation', 'main']
__version__ = '1.0.0'
