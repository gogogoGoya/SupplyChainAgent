"""
Inventory management module

Responsible for enterprise business logic related to inventory, including inventory tracking, inventory, early warning functions
"""

import time
from typing import Dict, List, Optional
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive
from config.module_config import InventoryConfig


class InventoryManager(EnhancedBaseModule):
    """
    Inventory Manager Category
    All business logic associated with enterprise inventory
        """
    def __init__(self, enterprise, initial_capacity: int = None, module_id=None, config: InventoryConfig = None):
        """
        Initialized inventory manager

        Args:
            Enterprise: Examples of enterprise
            parameter: Initial repository capacity (optional, read by default from config)
            module_id: Modular ID (optional)
            Config: Inventory Configuration Object (optional, default use InventoryConfig())
                """
        # Use configuration or default configuration
        self.config = config or InventoryConfig()

        # Call Parent Initialisation Method
        super().__init__(
            enterprise,
            module_id or f"inventory_{enterprise.id}",
            self.config
        )

        # Inventory tracking
        self.inventory: Dict[str, Dict] = {}  # Inventory information
        self.inventory_history: Dict[str, List] = {}  # Inventory-change history by item.

        # Inventory strategy
        self.reorder_points: Dict[str, float] = {}  # Order another {item_id: reorder_point}
        self.safety_stocks: Dict[str, float] = {}  # Secure inventory {item_id: safety_stock}

        # Warehouse management
        self.total_capacity = initial_capacity or self.config.INITIAL_CAPACITY  # Total capacity
        self.used_capacity = 0  # Used capacity
        self.expansion_history = []  # Warehouse Extension History

        # Inventory incidents
        self.inventory_events: List[Dict] = []  # Inventory Event Log

        # Inventory indicators
        self.inventory_metrics = {
            "total_items": 0,
            "total_value": 0.0,
            "inventory_turnover": 0.0,
            "stockout_rate": 0.0,
            "warehouse_utilization": 0.0,
            # "shrinkage_rate": 0.0
        }

        # Shortfall statistics (for the calculation of the rate)
        self.stockout_count = 0  # Number of missing goods
        self.total_outbound_requests = 0  # Total number of exit requests

        # Sales cost tracking (for inventory turnover)
        # parameter = 0.0 # sales cost
        # Average inventory value history is intentionally disabled.

        # Shrink tracking (used to calculate water shrunk rates)
        # parameter = 0.0 # Cumulative deflation value
        # Total inventory value at shrinkage is intentionally disabled.

        # Maintenance cost tracking
        self.maintenance_cost_rate = self.config.MAINTENANCE_COST_RATE  # Maintenance cost rate (read from config)
        self.total_maintenance_cost = 0.0  # Cumulative maintenance costs
        self.maintenance_cost_history = []  # Maintenance of cost history records

        self.operating_cost_rate = self.config.OPERATING_COST_RATE  # Operating cost rate (read from config)
        self.total_operating_cost = 0.0  # Cumulative operating costs
        self.operating_cost_history = []  # Operation cost history records

        # Module Type Identification
        self.module_type = "InventoryManager"

        # Unit conversion table: External - > SU (Death configuration, no dynamic change provided)
        # Format: parameter:{"to_su": ratio, "from_su": inverse_ratio}}
        # For example, a to_su ratio of 0.01 means 100 units of malt equal 1 SU.
        self.unit_conversion_table: Dict[str, Dict[str, float]] = {}

        # Default Unit Map (Death Profile)
        # 100 Malt = 1 SU, 10 Hops = 1 SU, 5 Yeast = 1 SU, 1 Beer = 1 SU
        self._initialize_default_unit_mappings()

    @with_response("add_inventory")
    @validate_positive("quantity")
    @validate_positive("purchase_price")
    def add_inventory(self, item_id: str, quantity: float, purchase_price: float, item_type: str, dry_run: bool = False,response: ModuleResponse = None) -> ModuleResponse:
        """
        Add to Library

        Decorator description:
        - parameter : Automatic creation of response objects, anomalies
        -@validate_positive: Autovalidation > 0 and purchase_price 0

        Args:
            item_id: Material ID (if containing unit information such as "malt_1, automatically detect and convert)
            Quantity: Number (external units, automatically converted to SU)
            purchase_price: purchase unit price (validated as greater than zero)
            item_type: "raw_material" or "product"
            parameter: Run for test
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unanimous object for the entry result

        **Code achieved**:
        - Validation > 0
        - Automatic detection units from material ID (e.g. "malt_1"→ "malt")
        - Internal calculations of external units converted to SU
        - Check for adequate storage capacity
        - Weighted average method used to calculate the new unit price (the new price was directly used when the original inventory was 0)
        - Updating of inventory and warehouse usage (using SU)
        - Recording history and events
                """
        # Automatically detect units from material ID
        original_unit = self._get_item_original_unit(item_id)
        normalized_item_type = self._normalize_item_type(item_id, item_type)

        # If unit detected, convert to SU
        su_quantity = self._to_su_quantity(quantity, original_unit)
        
        # 1. Inspection of warehouse capacity
        if self.used_capacity + su_quantity > self.total_capacity:
            remaining_capacity = self.total_capacity - self.used_capacity
            return self.error_response(
                response,
                "INSUFFICIENT_CAPACITY",
                f"Insufficient capacity for inbound inventory. Remaining: {remaining_capacity}; required: {su_quantity} SU"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", "Dry-run validation passed")

        
        # Update inventory (search or create)
        if item_id not in self.inventory:
            self.inventory[item_id] = {
                "quantity": 0,
                "unit_price": 0.0,
                "total_value": 0.0,
                "item_type": normalized_item_type,
                "original_unit": original_unit,  # Save detected original unit
                "last_updated": self.enterprise.time_manager.get_day()
            }

        # 3. Calculation of weighted average unit price
        current_stock = self.inventory[item_id]
        if current_stock.get("original_unit") is None:
            current_stock["original_unit"] = original_unit
        current_stock["item_type"] = self._normalize_item_type(
            item_id,
            normalized_item_type,
            current_stock.get("item_type")
        )
        original_value = current_stock["total_value"]
        current_pricing_quantity = self._to_pricing_quantity(
            current_stock["quantity"],
            current_stock.get("original_unit")
        )
        inbound_pricing_quantity = self._to_pricing_quantity(
            su_quantity,
            current_stock.get("original_unit")
        )
        new_value = inbound_pricing_quantity * purchase_price
        new_total_quantity = current_stock["quantity"] + su_quantity
        new_total_pricing_quantity = current_pricing_quantity + inbound_pricing_quantity

        # Use the new price directly if the original inventory is 0; otherwise weighted average
        if current_pricing_quantity == 0:
            new_unit_price = purchase_price
        else:
            new_unit_price = (original_value + new_value) / new_total_pricing_quantity

        # Update inventory records (internal use of SU)
        current_stock["quantity"] = new_total_quantity
        current_stock["unit_price"] = new_unit_price
        current_stock["total_value"] = original_value + new_value
        current_stock["last_updated"] = self.enterprise.time_manager.get_day()

        # 5. Updating of warehouse usage (using SU)
        self.used_capacity += su_quantity

        # 6. Recording history and events
        self._record_inventory_transaction(item_id, su_quantity, "inbound", "purchase/production")
        self._update_inventory_metrics()

        # Returns Successful Response
        response_data = {
            "item_id": item_id,
            "new_quantity": current_stock["quantity"],
            "new_unit_price": new_unit_price,
            "financial": {
                "total_value": current_stock["total_value"]
            },
            "inventory": {
                "item_type": current_stock["item_type"],
                "last_updated": current_stock["last_updated"]
            }
        }
        
        return self.success_response(
            response,
            f"Added {su_quantity} SU of item {item_id} ({quantity} {original_unit if original_unit else 'SU'}) to inventory",
            response_data
        )

    @with_response("check_capacity")
    @validate_positive("quantity")
    def check_capacity(self, item_id: str, quantity: float, response: ModuleResponse = None) -> ModuleResponse:
        """
        Validate whether a specified number of items can be added to the warehouse capacity

        Args:
            item_id: Items ID
            Quantity: Number to add (validated by decorator > 0)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified responder to the result of a volume check

        **Code achieved**:
        - Check the warehouse usage + whether the quantity to add is < = total capacity
        - Simple capacity validation method for binding inspections
                """
        original_unit = self._get_item_original_unit(item_id)
        su_quantity = self._to_su_quantity(quantity, original_unit)

        # Perform capacity checks
        is_valid = (self.used_capacity + su_quantity) <= self.total_capacity

        # Returns Successful Response
        return self.success_response(
            response,
            f"Capacity check {'passed' if is_valid else 'failed'}",
            {
                "item_id": item_id,
                "quantity": quantity,
                "su_quantity": su_quantity,
                "used_capacity": self.used_capacity,
                "total_capacity": self.total_capacity,
                "is_valid": is_valid
            }
        )

    @with_response("remove_inventory")
    @validate_positive("quantity")
    def remove_inventory(self, item_id: str, quantity: float, reason: str,
                        response: ModuleResponse = None) -> ModuleResponse:
        """
        Remove Inventory

        Args:
            item_id: Material ID (if containing unit information such as "malt_1, automatically detect and convert)
            Quantity: Number (external units, automatically converted to SU)
            Reason for removal (e.g, "protection", "sales")
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified responder to the results of the library

        **Code achieved**:
        - Validation > 0
        - Automatic detection units from material ID (e.g. "malt_1"→ "malt")
        - Internal calculations of external units converted to SU
        - Check for material.
        - Check for adequacy of stocks
        - Updating of inventory and warehouse usage (using SU)
        - Record the history of the library.
        - Statistics of the number of Treasury requests and the number of missing items (for the calculation of the rate)
                """
        # Automatically detect units from material ID
        original_unit = self._get_item_original_unit(item_id)

        # If unit detected, convert to SU
        su_quantity = self._to_su_quantity(quantity, original_unit)
        
        # 1. Check for inventory
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"Item {item_id} does not exist"
            )

        # 2. Check for adequacy of stocks
        current_stock = self.inventory[resolved_item_id]
        self.total_outbound_requests += 1  # Record library requests

        if current_stock["quantity"] < su_quantity:
            # Record missing goods
            self.stockout_count += 1
            self._update_stockout_rate()
            return self.error_response(
                response,
                "INSUFFICIENT_INVENTORY",
                f"Insufficient inventory. Required: {su_quantity} SU; available: {current_stock['quantity']} SU"
            )

        # 3. Updating of inventories (using SU)
        current_stock["quantity"] -= su_quantity
        remaining_pricing_quantity = self._to_pricing_quantity(
            current_stock["quantity"],
            current_stock.get("original_unit")
        )
        current_stock["total_value"] = remaining_pricing_quantity * current_stock["unit_price"]
        current_stock["last_updated"] = self.enterprise.time_manager.get_day()

        # Update warehouse usage (using SU)
        self.used_capacity -= su_quantity

        # 5. Recording history and events (using SU)
        self._record_inventory_transaction(resolved_item_id, -su_quantity, "outbound", reason)
        self._update_inventory_metrics()

        # Returns Successful Response
        response_data = {
            "item_id": resolved_item_id,
            "remaining_quantity": current_stock["quantity"],
            "financial": {
                "total_value": current_stock["total_value"]
            },
            "inventory": {
                "last_updated": current_stock["last_updated"]
            },
            "transaction": {
                "reason": reason,
                "quantity": su_quantity,
                "unit": "SU"
            }
        }
        
        
        return self.success_response(
            response,
            f"Removed {su_quantity} SU of item {resolved_item_id} ({quantity} {original_unit if original_unit else 'SU'}) from inventory",
            response_data
        )

    @with_response("expand_warehouse")
    def expand_warehouse(self, size: int, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Expansion of the warehouse

        Args:
            size: Expansion size (1000, 2000, 5000)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified responder to the result of the extension

        **Code achieved**:
        - Verifying whether the expansion is effective
        - Check the adequacy of enterprise funds
        - Cost deduction through the finance module
        - Immediate increase in warehouse capacity (no construction cycle)
        - Recording expansion history
                """
        costs = self.config.WAREHOUSE_EXPANSION_COSTS
        if size not in costs:
            return self.error_response(
                response,
                "INVALID_SIZE",
                "Invalid extension, select size 1000, 2000 or 5000"
            )
        needed_workers = self.config.WAREHOUSE_EXPANSION_WORKER_REQUIREMENTS.get(size, 1)
        base_cost = costs[size]
        cost_multiplier = self._long_horizon_cost_multiplier(
            "warehouse_expansion_cost_multiplier"
        )
        cost = base_cost * cost_multiplier
        finance_manager = super().get_module_by_type("FinanceManager")
        hr_manager = super().get_module_by_type("HRManager")

        # Interaction with the finance module
        if finance_manager.cash < cost:
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                f"Insufficient funds for expansion. Minimum required: {cost}"
            )

        # Inspection of human resources
        hr_result = hr_manager.get_available_workers(department="inventory")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < needed_workers:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"Insufficient staff for expansion. Minimum required: {needed_workers}"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", "Dry-run validation passed")

        assignment_id = f"warehouse_expand_{self.enterprise.time_manager.get_day()}_{size}"
        assign_result = hr_manager.assign_workers("inventory", assignment_id, needed_workers)
        if not getattr(assign_result, "success", True):
            return self.error_response(
                response,
                "ASSIGN_WORKERS_ERROR",
                getattr(assign_result, "message", "Warehouse expansion staff distribution failed")
            )

        # Less costs
        cost_result = finance_manager.add_cost(cost, "inventory_cost", "warehouse expand")
        if not getattr(cost_result, "success", True):
            hr_manager.release_workers("inventory", assignment_id, needed_workers, "cancelled")
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                getattr(cost_result, "message", "Failed to record warehouse expansion costs")
            )

        # Increased capacity
        self.total_capacity += size

        # Record history
        self.expansion_history.append({
            "time_step": self.enterprise.time_manager.get_day(),
            "expanded_size": size,
            "new_total_capacity": self.total_capacity,
            "cost": cost
        })

        self._update_inventory_metrics()
        hr_manager.release_workers("inventory", assignment_id, needed_workers, "completed")

        # Returns Successful Response
        return self.success_response(
            response,
            f"Warehouse expanded by {size} units; new total capacity is {self.total_capacity}",
            {
                "expanded_size": size,
                "new_total_capacity": self.total_capacity,
                "cost": cost,
                "warehouse": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "utilization": self.inventory_metrics["warehouse_utilization"]
                },
                "financial": {
                    "cost": cost
                }
            }
        )

    @with_response("get_inventory_level")
    def get_inventory_level(self, item_id: str, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        Inventory of individual items acquired

        Args:
            item_id: Material ID
            Response: Respond objects (injected by decorator)
            parameter: Whether to convert back to the original unit (defaultTrue)

        Returns:
            ModuleResponse: Harmonized response object with material stock

        **Code achieved**:
        - Parameter: `item_id` - Material ID
        - Return: ModuleResponse contains inventory (return 0 when the material does not exist)
        - If convert_to_original_unit is true and a source unit exists, convert back to that unit.
                """
        # Access to inventory data
        resolved_item_id = self._resolve_item_id(item_id)
        inventory_data = self.inventory.get(resolved_item_id, {}) if resolved_item_id else {}
        su_quantity = inventory_data.get("quantity", 0)
        
        # If there is an original unit and conversion is required, the original unit is returned
        original_unit = inventory_data.get("original_unit")
        quantity = su_quantity
        unit = None
        
        if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
            quantity = self._from_su_quantity(su_quantity, original_unit)
            unit = original_unit
        
        # Returns Successful Response
        response_data = {
            "item_id": resolved_item_id or item_id,
            "quantity": quantity
        }
        
        if unit:
            response_data["unit"] = unit
            response_data["su_quantity"] = su_quantity
        
        return self.success_response(
            response,
            f"Retrieved inventory quantity for item {resolved_item_id or item_id}",
            response_data
        )

    @with_response("get_inventory_detail")
    def get_inventory_detail(self, item_id: str, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        Access to detailed inventory information for individual materials, including secure stocks, reorder points, alert status, etc.

        Args:
            item_id: Material ID
            Response: Respond objects (injected by decorator)
            parameter: Whether to convert back to the original unit (defaultTrue)

        Returns:
            ModuleResponse: Unified response object with material details

        **Code achieved**:
        - Parameter: `item_id` - Material ID
        - Return: ModuleResponse contains complete material information
        - Return fields:
          - parameter: Current stock levels (conversion back to original unit)
          - original_unit: source unit, when available
          - su_quantity: quantity in internal storage units
          - unit_price: unit price
          Total value
          - item_type: material type
          - last_updated: latest update step
          - safety_stock: safety-stock threshold
          - reorder_point: reorder threshold
          - is_low_stock: whether inventory is below safety stock
          - parameter: Is it below the reorder point?
                """
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"Item {item_id} does not exist"
            )

        data = self.inventory[resolved_item_id]
        su_quantity = data["quantity"]
        
        # Convert to Original
        original_unit = data.get("original_unit")
        quantity = su_quantity
        unit = None
        
        if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
            quantity = self._from_su_quantity(su_quantity, original_unit)
            unit = original_unit

        safety_stock = self.safety_stocks.get(item_id, 0)
        reorder_point = self.reorder_points.get(item_id, 0)
        display_safety_stock = self._from_su_quantity(safety_stock, original_unit) if unit else safety_stock
        display_reorder_point = self._from_su_quantity(reorder_point, original_unit) if unit else reorder_point

        detail = {
            "item_id": resolved_item_id,
            "quantity": quantity,
            "unit_price": data["unit_price"],
            "total_value": data["total_value"],
            "item_type": data["item_type"],
            "last_updated": data["last_updated"],
            "safety_stock": display_safety_stock,
            "reorder_point": display_reorder_point,
            "is_low_stock": data["quantity"] < safety_stock,
            "is_below_reorder_point": data["quantity"] < reorder_point
        }
        
        if unit:
            detail["unit"] = unit
            detail["su_quantity"] = su_quantity

        # Returns Successful Response
        return self.success_response(
            response,
            f"Retrieved inventory details for item {resolved_item_id}",
            detail
        )

    @with_response("get_inventory_overview")
    def get_inventory_overview(self, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        Obtain inventory overview

        Args:
            Response: Respond objects (injected by decorator)
            parameter: Whether to convert back to the original unit (defaultTrue)

        Returns:
            ModuleResponse: Unified responder with inventory overview information

        **Code achieved**:
        - returns: ModuleResponse contains the following fields
          - raw_materials: list of raw-material records
          - products: list of product records
          - `total_inventory_value`: float - Total inventory value
          - warehouse: total capacity, used capacity, and utilization
          - Each material contains: `id`, `quantity`, `unit` (original unit), `su_quantity`, `unit_price`, `total_value`, `last_updated`
                """
        raw_materials = []
        products = []
        stocks = []
        for item_id, data in self.inventory.items():
            su_quantity = data["quantity"]
            original_unit = data.get("original_unit")
            quantity = su_quantity
            unit = None
            
            # Convert to Original
            if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
                quantity = self._from_su_quantity(su_quantity, original_unit)
                unit = original_unit
            
            item_info = {
                "id": item_id,
                "item_id": item_id,
                "quantity": quantity,
                "unit_price": data["unit_price"],
                "total_value": data["total_value"],
                "last_updated": data["last_updated"]
            }
            
            if unit:
                item_info["unit"] = unit
                item_info["su_quantity"] = su_quantity
            
            stocks.append(item_info)
            if data["item_type"] == "raw_material":
                raw_materials.append(item_info)
            else:
                products.append(item_info)

        # Returns Successful Response
        return self.success_response(
            response,
            "Successfully acquired inventory overview",
            {
                "stocks": stocks,
                "raw_materials": raw_materials,
                "products": products,
                "total_inventory_value": self.inventory_metrics["total_value"],
                "warehouse_info": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "utilization": self.inventory_metrics["warehouse_utilization"]
                }
            }
        )

    @with_response("check_low_stock_levels")
    def check_low_stock_levels(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Check low inventory material
                
        Args:
            Response: Respond objects (injected by decorator)
                
        Returns:
            ModuleResponse: Harmonized Response Object with Low Inventory List
                
        **Code achieved**: 
        - Return: ModuleResponse contains a list of low inventory items
        - Each contains: `item_id`, `current_quantity`, `safety_stock`, `shortfall` (shortfall)
                """
        low_stock_items = []
        for item_id, safety_stock in self.safety_stocks.items():
            if item_id not in self.inventory:
                continue
            current_su_quantity = self.inventory[item_id]["quantity"]
            original_unit = self.inventory[item_id].get("original_unit")
            if current_su_quantity < safety_stock:
                current_quantity = self._from_su_quantity(current_su_quantity, original_unit)
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit)
                low_stock_items.append({
                    "item_id": item_id,
                    "current_quantity": current_quantity,
                    "safety_stock": display_safety_stock,
                    "shortfall": display_safety_stock - current_quantity,
                    "unit": original_unit or "SU"
                })
        
        # Returns Successful Response
        return self.success_response(
            response,
            f"Low-stock check found {len(low_stock_items)} items",
            {
                "low_stock_items": low_stock_items,
                "total_low_stock_items": len(low_stock_items)
            }
        )
    
    @with_response("check_reorder_points")
    def check_reorder_points(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Check for reorder points

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Harmonized Response Object with List of Materials Needing Reorder

        **Code achieved**:
        - Return: ModuleResponse contains a list of items that need to be reordered
        - Each contains: `item_id`, `current_quantity`, `reorder_point`, `shortfall` (shortfall)
                """
        reorder_items = []
        for item_id, reorder_point in self.reorder_points.items():
            if item_id not in self.inventory:
                continue
            current_su_quantity = self.inventory[item_id]["quantity"]
            original_unit = self.inventory[item_id].get("original_unit")
            if current_su_quantity < reorder_point:
                current_quantity = self._from_su_quantity(current_su_quantity, original_unit)
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit)
                reorder_items.append({
                    "item_id": item_id,
                    "current_quantity": current_quantity,
                    "reorder_point": display_reorder_point,
                    "shortfall": display_reorder_point - current_quantity,
                    "unit": original_unit or "SU"
                })

        # Returns Successful Response
        return self.success_response(
            response,
            f"Reorder-point check found {len(reorder_items)} items requiring replenishment",
            {
                "reorder_items": reorder_items,
                "total_reorder_items": len(reorder_items)
            }
        )
    
    @with_response("get_capacity_warning")
    def get_capacity_warning(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to capacity early warning information

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Harmonized response audience with volume early warning information

        **Code achieved**:
        - Return: ModuleResponse contains early warning levels, usage, remaining capacity, recommendations, etc.
        - Early warning level:
          - parameter: Usage < 30%
          - parameter: 30% ≤ Usage < 75%
          - parameter: 75% ≤ Usage rate < 90%
          - critical: utilization at or above 90 percent
                """
        utilization = self.inventory_metrics["warehouse_utilization"]
        remaining_capacity = self.total_capacity - self.used_capacity

        if utilization < self.config.CAPACITY_LOW_THRESHOLD:
            level = "low"
            message = "Lower usage of warehouses and possible overinvestment"
            suggestion = "Consider optimizing inventory management or reducing warehouse capacity"
        elif utilization < self.config.CAPACITY_WARNING_THRESHOLD:
            level = "normal"
            message = "Warehouse usage is normal"
            suggestion = "Keep going."
        elif utilization < self.config.CAPACITY_CRITICAL_THRESHOLD:
            level = "warning"
            message = "Higher usage of warehouse, recommended consideration of expansion"
            suggestion = f"Warehouse expansion recommended; remaining capacity: {remaining_capacity}"
        else:
            level = "critical"
            message = "The use of the warehouse was significantly excessive and required urgent expansion"
            suggestion = f"Urgent warehouse expansion recommended; remaining capacity: {remaining_capacity}"

        # Returns Successful Response
        return self.success_response(
            response,
            f"Capacity alert: {message}",
            {
                "level": level,
                "utilization": utilization,
                "used_capacity": self.used_capacity,
                "total_capacity": self.total_capacity,
                "remaining_capacity": remaining_capacity,
                "message": message,
                "suggestion": suggestion
            }
        )
    
    @with_response("set_inventory_policy")
    def set_inventory_policy(self, item_id: str, reorder_point: float, safety_stock: float,
                            dry_run: bool = False,
                            response: ModuleResponse = None) -> ModuleResponse:
        """
        Set up an inventory policy
                
        Args:
            item_id: Material ID
            reorder_point: reorder point (validated as non-negative)
            safety_stock: Safe inventory (validated by decorator > = 0)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Set a unified response object for the result
                
        **Code achieved**: 
        - Parameter: `item_id` - Material ID, `reorder_point` - Reorder point, `safety_stock` - Secure inventory
        -Return: ModeuleResponse contains settings
        - Validate material presence and parameter validity
                """
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"Item {item_id} does not exist; policy cannot be configured"
            )

        if reorder_point < 0 or safety_stock < 0:
            return self.error_response(
                response,
                "INVALID_POLICY",
                "Reorder points and secure stocks must be greater than or equal to 0"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "item_id": resolved_item_id,
                    "policy": {
                        "reorder_point": reorder_point,
                        "safety_stock": safety_stock
                    }
                }
            )

        original_unit = self.inventory[resolved_item_id].get("original_unit")
        self.reorder_points[resolved_item_id] = self._to_su_quantity(reorder_point, original_unit)
        self.safety_stocks[resolved_item_id] = self._to_su_quantity(safety_stock, original_unit)
        
        # Returns Successful Response
        return self.success_response(
            response,
            f"Inventory policy configured for item {item_id}",
            {
                "item_id": resolved_item_id,
                "policy": {
                    "reorder_point": reorder_point,
                    "safety_stock": safety_stock
                }
            }
        )

    @with_response("get_inventory_history")
    def get_inventory_history(self, item_id: str, limit: int = 100,
                              response: ModuleResponse = None) -> ModuleResponse:
        """
        History of inventory changes to obtain material

        Args:
            item_id: Material ID
            Limited number of returned records (default 100, 0 means all returns)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: A unified response with historical history of inventory changes

        **Code achieved**:
        - Parameters: `item_id` - Material ID, `limit` - Return to record quantity limit
        - returns: ModuleResponse contains a list of historical records (recent record)
        - Each record contains: `time_step`, `quantity_change`, `type`, `reason`, `new_quantity`
        - Data structure: `self.inventory_history` - Dict[str, List [Dict]
                """
        if item_id not in self.inventory_history:
            # Return empty history
            return self.success_response(
                response,
                f"Item {item_id} has no inventory history",
                {
                    "item_id": item_id,
                    "history": [],
                    "total_records": 0
                }
            )

        history = self.inventory_history[item_id]
        result_history = history[-limit:] if limit > 0 else history

        # Returns Successful Response
        return self.success_response(
            response,
            f"Retrieved inventory history for item {item_id}",
            {
                "item_id": item_id,
                "history": result_history,
                "total_records": len(history),
                "returned_records": len(result_history),
                "limit": limit
            }
        )
    
    # @with_response("calculate_inventory_turnover")
    # def calculate_inventory_turnover(self, cost_of_goods_sold: Optional[float] = None,
    #                                  response: ModuleResponse = None) -> ModuleResponse:
    #     """
    # Computation of inventory turnover

    #     Args:
    # cost_of_goods_sold: Sales cost, using internal tracking value if None
    # Response: Respond objects (injected by decorator)

    #     Returns:
    # ModuleResponse: Unified target with inventory turnover

    # **Code achieved**:
    # - Parameter: `cost_of_goods_sold` - Sales cost (optional, default internal tracking value)
    # - Return: ModeuleResponse includes stock turnover
    # - Key logic:
    # - Calculation of averages using historical inventory values (most recently 100 time steps)
    # - turnover = sales cost / average inventory value
    # - Automatically update `inventory_metrics["inventory_turnover"]`
    #     """
    #     if cost_of_goods_sold is None:
    #         cost_of_goods_sold = self.cost_of_goods_sold

    # # Calculate average inventory value
    #     current_value = self.inventory_metrics["total_value"]

    # # If there's a history, calculate the average
    #     if len(self.average_inventory_value_history) > 0:
    #         avg_value = sum(self.average_inventory_value_history) / len(self.average_inventory_value_history)
    # # Add the current value
    #         avg_value = (avg_value + current_value) / 2
    #     else:
    #         avg_value = current_value

    # # Calculate the turnover rate
    #     turnover = 0.0
    #     if avg_value > 0:
    #         turnover = cost_of_goods_sold / avg_value
    #         self.inventory_metrics["inventory_turnover"] = turnover

    # # Return to a successful response
    #     return self.success_response(
    #         response,
    # "Successful calculation of inventory turnover"
    #         {
    #             "turnover": turnover,
    #             "cost_of_goods_sold": cost_of_goods_sold,
    #             "average_inventory_value": avg_value,
    #             "current_inventory_value": current_value
    #         }
    #     )
    
    # def record_sales_cost(self, cost: float):
    #     """
    # Recording of sales costs
        
    #     Args:
    # Cost of sales
        
    # **Code achieved**:
    # - Parameter: `cost` - Cost of sales
    # - Key logic:
    # - Accumulated sales costs to `cost_of_goods_sold`
    # - Record current inventory value to historical list
    # - Keep history within 100 steps.
    #     """
    #     self.cost_of_goods_sold += cost
    # # Recording current inventory value to history
    #     self.average_inventory_value_history.append(self.inventory_metrics["total_value"])
    # # Keep the historical record within reasonable limits (most recently 100 steps)
    #     if len(self.average_inventory_value_history) > 100:
    #         self.average_inventory_value_history.pop(0)

    @with_response("conduct_inventory_count")
    def conduct_inventory_count(self, item_id: str, actual_quantity: float,
                               response: ModuleResponse = None) -> ModuleResponse:
        """
        Implement inventory counts and adjustments

        Args:
            item_id: Inventory material ID
            actual_quantity: physical count (validated as non-negative)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: A unified response to an inventory adjustment

        **Code achieved**:
        - Parameter: `item_id` - Material ID, `actual_quantity` - Actual count
        - returns: ModuleResponse contains information on inventory results, discrepancies, etc.
        - Key logic:
          1. Validation of the existence of material
          2. Calculation differences (actual quantity - number of systems)
          If the difference is positive (increase), check whether the warehouse capacity is sufficient
          4. Updating of stock levels and total value
          5. Updating warehouse usage
          6. Records inventory history (type "adjustment")
          If the difference is negative (shrunk), calculate and update the deflation rate
        - Calculated deflation rate: Accumulated deflation value / Accumulated inventory value (including reduced)
                """
        # 1. Validation of the existence of material
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"Item {item_id} does not exist"
            )

        if actual_quantity < 0:
            return self.error_response(
                response,
                "INVALID_QUANTITY",
                "The number of counts must be greater than or equal to 0"
            )

        # 2. Differences in the number of access systems and their calculation
        original_unit = self.inventory[resolved_item_id].get("original_unit")
        actual_su_quantity = self._to_su_quantity(actual_quantity, original_unit)
        system_quantity = self.inventory[resolved_item_id]["quantity"]
        variance = actual_su_quantity - system_quantity
        shrinkage_value = 0.0

        if variance == 0:
            # The number of counts is consistent with the system and no adjustments are required
            system_quantity_display = self._from_su_quantity(system_quantity, original_unit)
            return self.success_response(
                response,
                "The number of counts is consistent with the system and no adjustments are required",
                {
                    "item_id": resolved_item_id,
                    "system_quantity": system_quantity_display,
                    "system_su_quantity": system_quantity,
                    "actual_quantity": actual_quantity,
                    "actual_su_quantity": actual_su_quantity,
                    "variance": 0,
                    "variance_su": 0,
                    "unit": original_unit or "SU"
                }
            )

        # 3. Inspection capacity (if increased)
        if variance > 0:
            if self.used_capacity + variance > self.total_capacity:
                return self.error_response(
                    response,
                    "INSUFFICIENT_CAPACITY",
                    f"Count adjustment would exceed capacity. Used: {self.used_capacity}; increase: {variance}; total: {self.total_capacity}"
                )

        # 4. Updating of inventories
        self.inventory[resolved_item_id]["quantity"] = actual_su_quantity
        pricing_quantity = self._to_pricing_quantity(actual_su_quantity, original_unit)
        self.inventory[resolved_item_id]["total_value"] = pricing_quantity * self.inventory[resolved_item_id]["unit_price"]

        # 5. Updated capacity
        self.used_capacity += variance

        # 6. Recording adjustments
        self._record_inventory_transaction(resolved_item_id, variance, "adjustment", "physical_count")
        self._update_inventory_metrics()

        # #7. Calculate water shrunk (if the number of counts decreases)
        # shrinkage_value = 0.0
        # if variance < 0:
        #     shrinkage_value = abs(variance) * self.inventory[item_id]["unit_price"]
        #     self.total_shrinkage_value += shrinkage_value
        # # Use of updated total inventory value
        #     total_value = self.inventory_metrics["total_value"]
        #     self.total_inventory_value_at_shrinkage += total_value + shrinkage_value

        # # Update deflation rate: Accumulated deflation value / Accumulated inventory value (including reduced)
        #     if self.total_inventory_value_at_shrinkage > 0:
        #         self.inventory_metrics["shrinkage_rate"] = self.total_shrinkage_value / self.total_inventory_value_at_shrinkage

        # Returns Successful Response
        system_quantity_display = self._from_su_quantity(system_quantity, original_unit)
        variance_display = self._from_su_quantity(variance, original_unit)
        return self.success_response(
            response,
            f"Inventory adjusted by {variance}",
            {
                "item_id": resolved_item_id,
                "system_quantity": system_quantity_display,
                "system_su_quantity": system_quantity,
                "actual_quantity": actual_quantity,
                "actual_su_quantity": actual_su_quantity,
                "variance": variance_display,
                "variance_su": variance,
                "shrinkage_value": shrinkage_value,
                "current_quantity": actual_quantity,
                "current_value": self.inventory[resolved_item_id]["total_value"],
                "unit": original_unit or "SU"
            }
        )

    # Synchronization helpers.

    def _active_runtime_injection_config(self) -> Dict:
        runtime_config = getattr(self.enterprise, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            controller = getattr(self.enterprise, "controller", None)
            runtime_config = getattr(controller, "runtime_injection_config", None)
        if isinstance(runtime_config, dict):
            return runtime_config
        try:
            from config.simulation_preset_config import get_runtime_injection_config

            return get_runtime_injection_config() or {}
        except Exception:
            return {}

    def _long_horizon_cost_multiplier(self, key: str) -> float:
        policy = self._active_runtime_injection_config().get("long_horizon_cost_policy") or {}
        target_ids = set(policy.get("target_enterprise_ids") or [])
        if not policy.get("enabled") or (
            target_ids and getattr(self.enterprise, "id", None) not in target_ids
        ):
            return 1.0
        try:
            return max(0.0, float(policy.get(key, 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _is_inventory_cost_exempt(self) -> bool:
        """
        To determine whether the current cost-exempt strategy of enterprise to hold a hit stockpile.
                """
        try:
            runtime_config = self._active_runtime_injection_config()
            policy = runtime_config.get("inventory_cost_exemption_policy") or {}
            if not policy.get("enabled"):
                return False

            target_enterprise_ids = set(policy.get("target_enterprise_ids") or [])
            if self.enterprise.id in target_enterprise_ids:
                return True

            target_role_tags = set(policy.get("target_role_tags") or [])
            enterprise_role_tags = set(getattr(self.enterprise, "role_tags", []) or [])
            return bool(target_role_tags and (enterprise_role_tags & target_role_tags))
        except Exception:
            return False

    @with_response("calculate_inventory_cost")
    def calculate_inventory_cost(self, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculate maintenance costs for current time steps

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with current cost, inventory value, etc.

        **Code achieved**:
        - Acquisition of total current inventory value
        - Calculate maintenance costs = inventory value x cost rate
        - Add to total maintenance costs
        - Record to history list.
        - Recording of expenditures through the finance module
        - Updating of inventory indicators
                """
        if self._is_inventory_cost_exempt():
            return self.success_response(
                response,
                "The cost exemption for inventory holding is in effect and is not carried over for the current round",
                {
                    "maintenance_cost": 0.0,
                    "operating_cost": 0.0,
                    "inventory_value": self.inventory_metrics["total_value"],
                    "cost_rate": self.maintenance_cost_rate,
                    "operating_cost_rate": self.operating_cost_rate,
                    "inventory_cost_exempt": True
                }
            )

        # 1. Acquisition of total current inventory value
        inventory_value = self.inventory_metrics["total_value"]

        # Calculation of maintenance costs
        maintenance_multiplier = self._long_horizon_cost_multiplier(
            "inventory_maintenance_cost_multiplier"
        )
        operating_multiplier = self._long_horizon_cost_multiplier(
            "warehouse_operating_cost_multiplier"
        )
        effective_maintenance_rate = self.maintenance_cost_rate * maintenance_multiplier
        effective_operating_rate = self.operating_cost_rate * operating_multiplier
        maintenance_cost = inventory_value * effective_maintenance_rate
        operating_cost = self.total_capacity * effective_operating_rate
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "maintenance_cost": maintenance_cost,
                    "operating_cost": operating_cost,
                    "inventory_value": inventory_value,
                    "cost_rate": effective_maintenance_rate,
                    "operating_cost_rate": effective_operating_rate,
                    "cost_policy_multipliers": {
                        "maintenance": maintenance_multiplier,
                        "operating": operating_multiplier,
                    },
                }
            )

        # 3. Cumulative to total maintenance costs
        self.total_maintenance_cost += maintenance_cost

        # 4. Historical list recorded
        maintenance_history_record = {
            "time_step": self.enterprise.time_manager.get_day(),
            "inventory_value": inventory_value,
            "cost_rate": effective_maintenance_rate,
            "maintenance_cost": maintenance_cost,
            "total_cost": self.total_maintenance_cost
        }
        self.maintenance_cost_history.append(maintenance_history_record)
        finance_manager = super().get_module_by_type("FinanceManager")

        # Calculation of operating costs

        # Add to total operating cost
        self.total_operating_cost += operating_cost

        # Record to History List
        operating_history_record = {
            "time_step": self.enterprise.time_manager.get_day(),
            "total_capacity": self.total_capacity,
            "cost_rate": effective_operating_rate,
            "operating_cost": operating_cost,
            "total_cost": self.total_operating_cost
        }
        self.operating_cost_history.append(operating_history_record)


        # Recording of expenditures through the finance module (if available)
        if maintenance_cost > 0:
            try:
                result = finance_manager.add_cost(
                    maintenance_cost,
                    "inventory_cost",
                    "inventory_maintenance"
                )
                # Addressing different types of return
                if hasattr(result, "success"):
                    if not result.success:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record maintenance cost: {result.message}")
                else:
                    if result:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record maintenance cost: {result}")
            except Exception as e:
                response.add_error("COST_RECORD_ERROR", f"Error recording maintenance cost: {e}")

        if operating_cost > 0:
            try:
                result = finance_manager.add_cost(
                    operating_cost,
                    "inventory_cost",
                    "inventory_operating"
                )
                # Addressing different types of return
                if hasattr(result, "success"):
                    if not result.success:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record operating cost: {result.message}")
                else:
                    if result:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record operating cost: {result}")
            except Exception as e:
                response.add_error("COST_RECORD_ERROR", f"Error recording operating cost: {e}")



        # 6. Updating of inventory indicators
        self._update_inventory_metrics()

        # Returns Successful Response
        return self.success_response(
            response,
            f"Maintenance cost calculated: {maintenance_cost:.2f}",
            {
                "maintenance_cost": maintenance_cost,
                "operating_cost": operating_cost,   
                "inventory_value": inventory_value,
                "cost_rate": effective_maintenance_rate,
                "operating_cost_rate": effective_operating_rate,
                "cost_policy_multipliers": {
                    "maintenance": maintenance_multiplier,
                    "operating": operating_multiplier,
                },
                "total_maintenance_cost": self.total_maintenance_cost,
                "maintenance_history_record": maintenance_history_record,
                "operating_history_record": operating_history_record
            }
        )

    @with_response("set_maintenance_cost_rate")
    def set_maintenance_cost_rate(self, rate: float, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Set maintenance cost rate

        Args:
            Rate: New cost rate (no. 1 decimal)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Set a unified response object for the result

        **Code achieved**:
        - Validation cost rate must > = 0 and < = 1
        - Update cost rate
        - Back to success.
                """
        # Validate cost range
        if rate < 0 or rate > 1:
            return self.error_response(
                response,
                "INVALID_RATE",
                "Maintenance cost rates must be between 0 and 1"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "old_rate": self.maintenance_cost_rate,
                    "new_rate": rate
                }
            )

        # Update cost rate
        old_rate = self.maintenance_cost_rate
        self.maintenance_cost_rate = rate

        # Returns Successful Response
        return self.success_response(
            response,
            f"Maintenance cost rate set to {rate*100:.2f}%",
            {
                "old_rate": old_rate,
                "new_rate": rate,
                "message": f"Maintenance cost rate updated from {old_rate*100:.2f}% to {rate*100:.2f}%"
            }
        )

    @with_response("get_maintenance_cost_summary")
    def get_maintenance_cost_summary(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Acquisition of summary maintenance costs

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with total cost, average cost, cost rate, etc.

        **Code achieved**:
        - Total return cost, current rate, historical number, average time-step cost
                """
        # Calculating summary maintenance information
        history_count = len(self.maintenance_cost_history)
        average_cost_per_step = (
            self.total_maintenance_cost / history_count
            if history_count > 0 else 0.0
        )

        # Returns Successful Response
        return self.success_response(
            response,
            "Summary of maintenance costs successfully acquired",
            {
                "total_cost": self.total_maintenance_cost,
                "current_rate": self.maintenance_cost_rate,
                "history_count": history_count,
                "average_cost_per_step": average_cost_per_step
            }
        )

    @with_response("get_maintenance_cost_history")
    def get_maintenance_cost_history(self, limit: int = 100, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access maintenance cost history

        Args:
            Limited number of returned records (default 100, 0 means all returns)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified Response Object with Historical Record List

        **Code achieved**:
        - Parameter: `limit` - Return number limits for records
        - returns: ModuleResponse contains a list of historical records (recent record)
                """
        # Access to historical records
        if limit == 0 or limit < 0:
            history = self.maintenance_cost_history
        else:
            history = self.maintenance_cost_history[-limit:]

        # Returns Successful Response
        return self.success_response(
            response,
            f"Retrieved {len(history)} maintenance-cost records",
            {
                "history": history,
                "total_records": len(self.maintenance_cost_history),
                "returned_records": len(history),
                "limit": limit
            }
        )
               
    @with_response("set_capacity")
    # Compatible old interfaces
    def set_capacity(self, capacity: int, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Set repository capacity

        Args:
            Capability: New warehouse capacity
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Set a unified response object for the result
                """
        
        # Validation capacity
        if capacity <= 0:
            return self.error_response(
                response,
                "INVALID_CAPACITY",
                "The capacity must be greater than 0",
                "Failed to set warehouse capacity"
            )
        
        # Setup is not allowed if new capacity is less than used
        if capacity < self.used_capacity:
            return self.error_response(
                response,
                "INSUFFICIENT_CAPACITY",
                f"New capacity cannot be below used capacity. Used: {self.used_capacity}; new: {capacity}",
                "Failed to set warehouse capacity"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", "Dry-run validation passed")
        
        # Update Capacity
        old_capacity = self.total_capacity
        self.total_capacity = capacity
        self._update_inventory_metrics()
        return self.success_response(
            response,
            f"Warehouse capacity set to {capacity}",
            {
                "old_capacity": old_capacity,
                "new_capacity": capacity,
                "used_capacity": self.used_capacity,
                "utilization": self.inventory_metrics["warehouse_utilization"]
            }
        )
    
    @with_response("initialize_inventory")
    def initialize_inventory(self, raw_materials: Dict = None, products: Dict = None,
                             dry_run: bool = False,
                             response: ModuleResponse = None) -> ModuleResponse:
        """
        Initialized inventory
                
        Args:
            raw_materials: Raw material inventory data item_id: parameter} or abbreviated quantity
            Products: Product inventory data {item_id:{"quantity": float, "unit_price": float}} or short quantities
                        
            Format description:
            - Short form: numeric quantity; full form: a parameter dictionary
            - Automatic detection units from material ID (e.g. "malt_1"→ "malt")
                        
        Returns:
            ModuleResponse: Unified response object for initialised results
                """
        
        raw_materials = raw_materials or {}
        products = products or {}
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "raw_material_count": len(raw_materials),
                    "product_count": len(products)
                }
            )

        initialized_count = 0
        errors = []
        all_items = []
        
        # Initialized raw materials inventory
        for item_id, item_data in raw_materials.items():
            quantity, unit_price, err = _parse_item_data(item_id, item_data)
            if err:
                errors.append(f"Raw material: {err}")
                continue
            
            if quantity > 0:
                result = self.add_inventory(item_id, quantity, unit_price, "raw_material")
                all_items.append({
                    "item_id": item_id,
                    "item_type": "raw_material",
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "success": result.success
                })
                if result.success:
                    initialized_count += 1
                else:
                    errors.append(f"Failed to initialize raw material {item_id}: {result.errors[0].message if result.errors else 'Unknown error'}")
        
        # Initialized product inventory
        for item_id, item_data in products.items():
            quantity, unit_price, err = _parse_item_data(item_id, item_data)
            if err:
                errors.append(f"Product: {err}")
                continue
            
            if quantity > 0:
                result = self.add_inventory(item_id, quantity, unit_price, "product")
                all_items.append({
                    "item_id": item_id,
                    "item_type": "product",
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "success": result.success
                })
                if result.success:
                    initialized_count += 1
                else:
                    errors.append(f"Failed to initialize product {item_id}: {result.errors[0].message if result.errors else 'Unknown error'}")
        
        # Set Response Status and Data
        total_items = len(raw_materials) + len(products)
        if len(errors) == 0:
            response.set_status(ResponseStatus.SUCCESS)
            response.set_message(f"Inventory initialization complete: {initialized_count} items initialized")
        elif initialized_count > 0:
            response.set_status(ResponseStatus.PARTIAL)
            response.set_message(f"Inventory initialization partially completed: {initialized_count} succeeded, {len(errors)} failed")
        else:
            response.set_status(ResponseStatus.FAILED)
            response.set_message(f"Inventory initialization failed for all {total_items} items")
        
        # Can not open message
        for error in errors:
            response.add_error("INITIALIZATION_ERROR", error)
        
        response.data = {
            "initialized_count": initialized_count,
            "total_items": total_items,
            "raw_materials_count": len(raw_materials),
            "products_count": len(products),
            "errors": errors,
            "all_items": all_items
        }
        return response
    
    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        Get Current Module Status

        Args:
            Response: Respond objects (injected by decorator)
            parameter: Whether to convert back to the original unit (defaultTrue)

        Returns:
            ModuleResponse: Unified response object with modular status
                """
        try:
            self._update_inventory_metrics()
            
            # Calculate total inventory quantity and value (using SU)
            total_inventory = 0
            total_value = 0

            for item_id, inventory_data in self.inventory.items():
                quantity = inventory_data.get("quantity", 0)
                unit_price = inventory_data.get("unit_price", 0)
                total_inventory += quantity
                total_value += inventory_data.get("total_value", 0)

            # Build detailed list of inventory items
            inventory_items = []
            for item_id, inventory_data in self.inventory.items():
                su_quantity = inventory_data.get("quantity", 0)
                original_unit = inventory_data.get("original_unit")
                quantity = su_quantity
                unit = None
                safety_stock = self.safety_stocks.get(item_id, 0)
                reorder_point = self.reorder_points.get(item_id, 0)
                
                # Convert to Original
                if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
                    quantity = self._from_su_quantity(su_quantity, original_unit)
                    unit = original_unit
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit) if unit else safety_stock
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit) if unit else reorder_point
                
                item_info = {
                    "item_id": item_id,
                    "item_type": inventory_data.get("item_type", "unknown"),
                    "quantity": quantity,
                    "unit_price": inventory_data.get("unit_price", 0),
                    "total_value": inventory_data.get("total_value", 0),
                    "last_updated": inventory_data.get("last_updated", 0),
                    "safety_stock": display_safety_stock,
                    "reorder_point": display_reorder_point,
                    "is_low_stock": su_quantity < safety_stock,
                    "is_below_reorder_point": su_quantity < reorder_point
                }
                
                if unit:
                    item_info["unit"] = unit
                    item_info["su_quantity"] = su_quantity
                
                inventory_items.append(item_info)

            state_data = {
                # "module_id": self.module_id,
                "module_type": self.module_type,
                "total_inventory": total_inventory,
                "total_inventory_su": total_inventory,
                "total_value": total_value,
                "warehouse_capacity": self.total_capacity,
                "used_capacity": self.used_capacity,
                "warehouse_utilization": self.inventory_metrics["warehouse_utilization"],
                "total_maintenance_cost":self.total_maintenance_cost,
                "total_operating_cost":self.total_operating_cost,
                "inventory_metrics": dict(self.inventory_metrics),
                "inventory_items": inventory_items,
                "event_count": len(self.inventory_events)
            }

            return self.success_response(
                response,
                "Successfully accessed modular status",
                state_data
            )
        except Exception as e:
            # Addressing anomalies
            return self.error_response(
                response,
                "STATE_ERROR",
                f"Failed to retrieve module status: {e}"
            )

        # Synchronization helpers.

    def _record_inventory_transaction(self, item_id: str, quantity: float, trans_type: str, reason: str):
        """
        Record inventory transaction history
                
        **Code achieved**: 
        - Private methods, called by open methods
        - Record inventory changes to `inventory_history`
        - Call `_log_inventory_event()` to record events
                """
        if item_id not in self.inventory_history:
            self.inventory_history[item_id] = []
        
        self.inventory_history[item_id].append({
            "time_step": self.enterprise.time_manager.get_day(),
            "quantity_change": quantity,
            "type": trans_type,
            "reason": reason,
            "new_quantity": self.inventory[item_id]["quantity"]
        })
        
        # Record Events
        self._log_inventory_event({
            "type": f"inventory_{trans_type}",
            "item_id": item_id,
            "quantity": abs(quantity),
            "reason": reason
        })

    def _update_inventory_metrics(self):
        """
        Update of key inventory indicators
                
        **Code achieved**: 
        - Private methods, called by open methods
        - Update `total_items`, `total_value`, `warehouse_utilization`
        - Automatically update `inventory_turnover` if sales costs are recorded
                """
        total_value = sum(item["total_value"] for item in self.inventory.values())
        self.inventory_metrics["total_items"] = len(self.inventory)
        self.inventory_metrics["total_value"] = total_value
        
        if self.total_capacity > 0:
            self.inventory_metrics["warehouse_utilization"] = self.used_capacity / self.total_capacity
        else:
            self.inventory_metrics["warehouse_utilization"] = 0
        
        # Updated inventory turnover rate (if sales costs are recorded)
        # if self.cost_of_goods_sold > 0:
        #     self.calculate_inventory_turnover()
    
    def _update_stockout_rate(self):
        """
        Update stockout rate
                
        **Code achieved**: 
        - Private methods, called by `remove_inventory()`
        - Calculation of the missing rate = number of missing items / total number of Treasury requests
                """
        if self.total_outbound_requests > 0:
            self.inventory_metrics["stockout_rate"] = self.stockout_count / self.total_outbound_requests

    def _log_inventory_event(self, event: Dict):
        """
        Record inventory-related incidents

        **Code achieved**:
        - Private methods, called by `_record_inventory_transaction()`
        - Add event record to `inventory_events` list
                """
        self.inventory_events.append(event)

    @with_response("generate_inventory_analysis")
    def generate_inventory_analysis(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Generate inventory change analysis JSON

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: A unified response to JSON with inventory change analysis
                """
        try:
            # Inventory level analysis
            inventory_levels = {}
            total_value = 0
            total_quantity = 0
            for item_id, item_data in self.inventory.items():
                su_quantity = item_data.get("quantity", 0)
                original_unit = item_data.get("original_unit")
                quantity = self._from_su_quantity(su_quantity, original_unit)
                inventory_levels[item_id] = {
                    "quantity": quantity,
                    "su_quantity": su_quantity,
                    "unit": original_unit or "SU",
                    "unit_price": item_data.get("unit_price", 0),
                    "total_value": item_data.get("total_value", 0),
                    "item_type": item_data.get("item_type", "unknown"),
                    "last_updated": item_data.get("last_updated")
                }
                total_value += item_data.get("total_value", 0)
                total_quantity += su_quantity

            # Analysis of stock type distribution
            inventory_by_type = {}
            for item_id, item_data in self.inventory.items():
                item_type = item_data.get("item_type", "unknown")
                su_quantity = item_data.get("quantity", 0)
                quantity = self._from_su_quantity(
                    su_quantity,
                    item_data.get("original_unit")
                )
                if item_type not in inventory_by_type:
                    inventory_by_type[item_type] = {
                        "total_items": 0,
                        "total_quantity": 0,
                        "total_quantity_su": 0,
                        "total_value": 0
                    }
                inventory_by_type[item_type]["total_items"] += 1
                inventory_by_type[item_type]["total_quantity"] += su_quantity
                inventory_by_type[item_type]["total_quantity_su"] += su_quantity
                inventory_by_type[item_type]["total_value"] += item_data.get("total_value", 0)

            # Analysis of the utilization of warehouse capacity
            utilization = self.used_capacity / self.total_capacity if self.total_capacity > 0 else 0
            remaining_capacity = self.total_capacity - self.used_capacity

            # Early warning analysis of stockpiles
            low_stock_items = []
            reorder_items = []
            for item_id, item_data in self.inventory.items():
                su_quantity = item_data.get("quantity", 0)
                original_unit = item_data.get("original_unit")
                quantity = self._from_su_quantity(su_quantity, original_unit)
                safety_stock = self.safety_stocks.get(item_id, 0)
                reorder_point = self.reorder_points.get(item_id, 0)
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit)
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit)

                if su_quantity < safety_stock:
                    low_stock_items.append({
                        "item_id": item_id,
                        "current_quantity": quantity,
                        "safety_stock": display_safety_stock,
                        "shortfall": display_safety_stock - quantity,
                        "unit": original_unit or "SU"
                    })
                
                if su_quantity < reorder_point:
                    reorder_items.append({
                        "item_id": item_id,
                        "current_quantity": quantity,
                        "reorder_point": display_reorder_point,
                        "shortfall": display_reorder_point - quantity,
                        "unit": original_unit or "SU"
                    })

            # Analysis of trends in inventory movements
            inventory_history_summary = {}
            for item_id, history in self.inventory_history.items():
                if history:
                    inventory_history_summary[item_id] = {
                        "total_transactions": len(history),
                        "recent_transactions": history[-5:] if len(history) > 5 else history
                    }

            # Inventory turnover analysis
            turnover = self.inventory_metrics.get("inventory_turnover", 0)

            # Cost analysis of maintenance
            maintenance_cost_summary = {
                "total_maintenance_cost": self.total_maintenance_cost,
                "maintenance_cost_rate": self.maintenance_cost_rate,
                "history_count": len(self.maintenance_cost_history),
                "average_cost_per_step": self.total_maintenance_cost / len(self.maintenance_cost_history) if len(self.maintenance_cost_history) > 0 else 0
            }

            # Get Current Time
            try:
                timestamp = self.enterprise.time_manager.get_day() if hasattr(self.enterprise, 'time_manager') else 0
            except Exception:
                timestamp = 0

            # Build AnalysisJSON
            analysis_json = {
                "analysis_type": "Analysis of inventory changes",
                "timestamp": timestamp,
                "metrics": self.inventory_metrics,
                "inventory_levels": inventory_levels,
                "inventory_summary": {
                    "total_items": len(self.inventory),
                    "total_quantity": total_quantity,
                    "total_quantity_su": total_quantity,
                    "total_value": total_value
                },
                "inventory_by_type": inventory_by_type,
                "warehouse_analysis": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "remaining_capacity": remaining_capacity,
                    "utilization": utilization,
                    "utilization_level": (
                        "low"
                        if utilization < self.config.CAPACITY_LOW_THRESHOLD
                        else "normal"
                        if utilization < self.config.CAPACITY_WARNING_THRESHOLD
                        else "warning"
                        if utilization < self.config.CAPACITY_CRITICAL_THRESHOLD
                        else "critical"
                    )
                },
                "inventory_alerts": {
                    "low_stock_items": low_stock_items,
                    "reorder_items": reorder_items,
                    "low_stock_count": len(low_stock_items),
                    "reorder_count": len(reorder_items)
                },
                "inventory_history": inventory_history_summary,
                "turnover_analysis": {
                    "inventory_turnover": turnover,
                    "stockout_rate": self.inventory_metrics.get("stockout_rate", 0),
                    # "shrinkage_rate": self.inventory_metrics.get("shrinkage_rate", 0)
                },
                "maintenance_cost_analysis": maintenance_cost_summary,
                "insights": [
                    f"Total inventory items: {len(self.inventory)}",
                    f"Total inventory value: {total_value:,.2f}",
                    f"Warehouse utilization: {utilization:.2f}",
                    f"Inventory turnover: {turnover:.2f}",
                    f"Stockout rate: {self.inventory_metrics.get('stockout_rate', 0):.2f}",
                    # f "Shrink rate: {self.inventory_metrics.get('shrinkage_rate', 0):.2f}",
                    f"Low-stock items: {len(low_stock_items)}",
                    f"Items requiring reorder: {len(reorder_items)}"
                ]
            }

            return self.success_response(
                response,
                "Successful production of inventory change analysis",
                {
                    "analysis": analysis_json
                }
            )
        except Exception as e:
            return self.error_response(
                response,
                "ANALYSIS_ERROR",
                f"Failed to generate inventory-change analysis: {e}"
            )

    def _initialize_default_unit_mappings(self):
        """
        Initialize the default unit map
                
        **Code achieved**:
        - Set the default unit conversion ratio
        - 100 Malt = 1 SU, 10 Hops = 1 SU, 5 Yeast = 1 SU, 1 Beer = 1 SU
                """
        self.unit_conversion_table = {
            "malt": {"to_su": 0.01, "from_su": 100},
            "hops": {"to_su": 0.1, "from_su": 10},
            "yeast": {"to_su": 0.2, "from_su": 5},
            "beer": {"to_su": 1.0, "from_su": 1}
        }

    def _get_item_original_unit(self, item_id: str) -> Optional[str]:
        """Priority is given to reading units in the inventory records, followed by extrapolation by material ID."""
        resolved_item_id = self._resolve_item_id(item_id)
        inventory_item = self.inventory.get(resolved_item_id) if resolved_item_id else None
        if inventory_item and inventory_item.get("original_unit"):
            return inventory_item["original_unit"]
        return self._detect_unit_from_item_id(item_id)

    def _resolve_item_id(self, item_id: str) -> Optional[str]:
        """The real material ID is deciphered in the existing inventory, compatible with case differences."""
        if not item_id:
            return None
        if item_id in self.inventory:
            return item_id

        normalized_item_id = item_id.strip().lower()
        for existing_item_id in self.inventory.keys():
            if existing_item_id.lower() == normalized_item_id:
                return existing_item_id
        return None

    def _to_su_quantity(self, quantity: float, original_unit: Optional[str]) -> float:
        """Converts the original external unit number to the internal SU number."""
        if original_unit and original_unit in self.unit_conversion_table:
            return quantity * self.unit_conversion_table[original_unit]["to_su"]
        return quantity

    def _from_su_quantity(self, su_quantity: float, original_unit: Optional[str]) -> float:
        """Converts the internal amount of SU to the external original unit."""
        if original_unit and original_unit in self.unit_conversion_table:
            return su_quantity * self.unit_conversion_table[original_unit]["from_su"]
        return su_quantity

    def _to_pricing_quantity(self, su_quantity: float, original_unit: Optional[str]) -> float:
        """Convert an SU quantity to the source unit used for pricing."""
        return self._from_su_quantity(su_quantity, original_unit)

    def _normalize_item_type(
        self,
        item_id: str,
        item_type: Optional[str],
        existing_item_type: Optional[str] = None
    ) -> str:
        """`raw_material` or `product`."""
        if existing_item_type in {"raw_material", "product"}:
            return existing_item_type

        normalized = (item_type or "").strip().lower()
        if normalized in {"raw_material", "raw", "material", "procurement", "purchase"}:
            return "raw_material"
        if normalized in {"product", "produce_daily", "produce_completed", "finished_good", "finished_product"}:
            return "product"

        inferred_unit = self._get_item_original_unit(item_id)
        if inferred_unit == "beer":
            return "product"
        if inferred_unit in {"malt", "hops", "yeast"}:
            return "raw_material"

        return "product"

    @with_response("convert_to_su")
    def convert_to_su(self, quantity: float, unit: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Conversion of external units to standard units SU
                
        Args:
            Number (external)
            unit: unit name (e.g. "malt", "hops", "yesst", "beer")
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Harmonized response objects that contain the number of SUs after conversion
                        
        **Code achieved**:
        - Check if the unit is on the conversion table.
        - Convert with parameter ratio
        - Number of SUs returned after conversion
                """
        unit_lower = unit.lower()
        
        if unit_lower not in self.unit_conversion_table:
            return self.error_response(
                response,
                "UNIT_NOT_FOUND",
                f"Unit '{unit}' is not configured. Available units: {list(self.unit_conversion_table.keys())}"
            )
        
        conversion_ratio = self.unit_conversion_table[unit_lower]["to_su"]
        su_quantity = quantity * conversion_ratio
        
        return self.success_response(
            response,
            f"Converted {quantity} {unit} to SU",
            {
                "original_quantity": quantity,
                "original_unit": unit,
                "su_quantity": su_quantity,
                "conversion_ratio": conversion_ratio
            }
        )

    @with_response("convert_from_su")
    def convert_from_su(self, su_quantity: float, unit: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Convert SU to an external unit
                
        Args:
            su_quantity: Number of SUs
            unit: target unit name (e.g. "malt", "hops", "yesst", "beer")
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Harmonized response objects that include the number of external units after conversion
                        
        **Code achieved**:
        - Check if the unit is on the conversion table.
        - Convert with parameter ratio
        - Number of external units returned after conversion
                """
        unit_lower = unit.lower()
        
        if unit_lower not in self.unit_conversion_table:
            return self.error_response(
                response,
                "UNIT_NOT_FOUND",
                f"Unit '{unit}' is not configured. Available units: {list(self.unit_conversion_table.keys())}"
            )
        
        conversion_ratio = self.unit_conversion_table[unit_lower]["from_su"]
        original_quantity = su_quantity * conversion_ratio
        
        return self.success_response(
            response,
            f"Converted {su_quantity} SU to {unit}",
            {
                "su_quantity": su_quantity,
                "target_unit": unit,
                "quantity": original_quantity,
                "conversion_ratio": conversion_ratio
            }
        )

    def _detect_unit_from_item_id(self, item_id: str) -> str:
        """
        Automatic detection unit from material ID
                
        Args:
            item_id: Material ID (e.g. malt_1, hops_batch, beer_final)
                        
        Returns:
            str: Detected units (e. g. "malt", "hops", "beer") and returns None if not detected
                        
        **Code achieved**:
        - Walk through all units in the conversion table
        - Check if the unit is in the material ID.
        - Return to the first matching unit
                """
        if not item_id:
            return None
        
        item_id_lower = item_id.lower()
        
        for unit in self.unit_conversion_table.keys():
            if unit in item_id_lower:
                return unit
        
        return None


def _parse_item_data(item_id: str, item_data) -> tuple:
    """
    Parsing material data (simplified version without unit parameters)
        
    Args:
        item_id: Material ID
        item_data: Material data, which may be:
            - Brief number: 100
            - Dictionary: {"quantity": 100, "unit_price": 10.5}
        
    Returns:
        tuple: (quantity, unit_price, error)
            Number
            - unit_price: unit price
            - error information (if any)
        """
    try:
        quantity = 0
        unit_price = 0.0
        
        if isinstance(item_data, (int, float)):
            quantity = float(item_data)
            unit_price = 0.0
        elif isinstance(item_data, dict):
            quantity = item_data.get("quantity", 0)
            unit_price = item_data.get("unit_price", 0.0)
            
            if quantity is None:
                quantity = 0
            if unit_price is None:
                unit_price = 0.0
        else:
            return 0, 0.0, f"Invalid data type: {type(item_data)}"
        
        if not isinstance(quantity, (int, float)) or quantity < 0:
            return 0, 0.0, f"Quantity must be non-negative: {quantity}"
        
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            return 0, 0.0, f"Unit price must be non-negative: {unit_price}"
        
        return float(quantity), float(unit_price), None
        
    except Exception as e:
        return 0, 0.0, f"Parse error: {str(e)}"


def _parse_item_data_with_unit(item_id: str, item_data) -> tuple:
    """
    Parsing material data, supporting unit parameters (reserved for backward compatibility)
        
    Args:
        item_id: Material ID
        item_data: Material data, which may be:
            - Brief number: 100
            - Dictionary: {"quantity": 100, "unit_price": 10.5}
            - Full dictionary: {"quantity": 100, "unit_price": 10.5, "unit": "malt"}
        
    Returns:
        tuple: (quantity, unit_price, unit, error)
            Number
            - unit_price: unit price
            - unit: units (optional)
            - error information (if any)
        """
    try:
        quantity = 0
        unit_price = 0.0
        unit = None
        
        if isinstance(item_data, (int, float)):
            quantity = float(item_data)
            unit_price = 0.0
        elif isinstance(item_data, dict):
            quantity = item_data.get("quantity", 0)
            unit_price = item_data.get("unit_price", 0.0)
            unit = item_data.get("unit", None)
            
            if quantity is None:
                quantity = 0
            if unit_price is None:
                unit_price = 0.0
        else:
            return 0, 0.0, None, f"Invalid data type: {type(item_data)}"
        
        if not isinstance(quantity, (int, float)) or quantity < 0:
            return 0, 0.0, None, f"Quantity must be non-negative: {quantity}"
        
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            return 0, 0.0, None, f"Unit price must be non-negative: {unit_price}"
        
        if unit is not None and not isinstance(unit, str):
            return 0, 0.0, None, f"Unit must be a string: {unit}"
        
        return float(quantity), float(unit_price), unit, None
        
    except Exception as e:
        return 0, 0.0, None, f"Parse error: {str(e)}"
