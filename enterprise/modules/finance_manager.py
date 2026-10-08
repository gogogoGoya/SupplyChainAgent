"""
Financial management module

Responsible for enterprise financial-related business logic, including cash flow management, revenue records, cost records, financial indicator calculations, etc.
"""

import time
import datetime
from typing import Dict, List, Optional
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.decorators import (
    with_response, 
    validate_positive, 
    validate_choice,
    validate_date_range,
    performance_monitor
)
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from config.module_config import FinanceConfig


class FinanceManager(EnhancedBaseModule):
    """
    Processing all business logic related to enterprise finance
        
        """
    
    def __init__(self, enterprise, initial_cash: float = 0, 
                 module_id: str = None, config: FinanceConfig = None):
        """
        Initialize Financial Manager
                
        Args:
            Enterprise: Examples of enterprise
            initial_cash: Initial cash balance
            parameter: Only identification of modules (optional)
            Config: Financial Configuration Object (optional, default FinanceConfig())
                """
        # Use configuration or default configuration
        self.config = config or FinanceConfig()
        
        # Call Parent Initialization
        super().__init__(
            enterprise, 
            module_id or f"finance_{enterprise.id}",
            self.config
        )
        
        # Cash account management
        self.cash = initial_cash
        self.initial_cash = initial_cash
        
        # Transaction records
        self.transactions = []
        
        # Use configuration initialised data structure
        self.revenue = self.config.get_initial_revenue_dict()
        self.costs = self.config.get_initial_cost_dict()
        self.assets = self.config.get_initial_assets_dict(initial_cash)
        self.liabilities = self.config.get_initial_liabilities_dict()
        self.financial_metrics = self.config.get_initial_financial_metrics_dict()
        
        # Early Warning List
        self.warnings = []
        
        # Initial check
        self._check_cash_warning()

        self.module_type="FinanceManager"
    
    
    @with_response("add_revenue")
    @validate_positive("amount")
    @validate_choice("source", "REVENUE_SOURCES")
    def add_revenue(self, amount: float, source: str, description: str = "", 
                   order_id: str = None, buyer_enterprise_id: str = None,
                   dry_run: bool = False,
                   response: ModuleResponse = None) -> ModuleResponse:
        """
        Recording income - cash inflows
                
        Decorator description:
        - parameter : Automatic creation of response objects, anomalies
        - parameter: Autovalidationmount > 0
        - parameter : Autovalid source in valid option Medium
                
        Args:
            amount: the amount of the income must be >0 (validated by decorator)
            Source of income (validated by decorator)
            description:
            parameter: Order ID
            buyer_enterprise_id: BuyerenterpriseID
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "amount": amount,
                    "source": source,
                    "cash_after": self.cash + amount
                }
            )
        # Business logic - parameters have been validated by decorator
        old_cash = self.cash
        self.cash += amount
        
        # Update of income records
        self.revenue[source] += amount
        self.revenue["total_revenue"] += amount
        
        # Create transaction log (using assistive methods)
        transaction = self._create_transaction(
            tx_type="income",
            amount=amount,
            source=source,
            description=description,
            order_id=order_id,
            buyer_enterprise_id=buyer_enterprise_id,
            cash_before=old_cash,
            cash_after=self.cash
        )
        
        # Updated financial status (harmonized methodology)
        self._update_financial_state()
        
        # Returns successful response (the decorator automatically handles warnings)
        return self.success_response(
            response,
            f"Revenue of ¥{amount:.2f} recorded from {source}",
            {
                "transaction_id": transaction["id"],
                "transaction_length": len(self.transactions),
                "cash_after": self.cash,
                "total_revenue": self.revenue["total_revenue"],
                "financial": {
                    "cash_before": old_cash,
                    "cash_after": self.cash,
                    "amount": amount
                },
                "transaction": {
                    "id": transaction["id"],
                    "type": transaction["type"],
                    "source": transaction["source"]
                },
                "metrics": {
                    "total_revenue": self.revenue["total_revenue"]
                }
            }
        )
    
    @with_response("add_cost")
    @validate_positive("amount")
    @validate_choice("category", "COST_CATEGORIES")
    def add_cost(self, amount: float, category: str, description: str = "", 
                accounts_payable: bool = False,
                dry_run: bool = False,
                response: ModuleResponse = None) -> ModuleResponse:
        """
        Record costs/expenditures - cash outflows or accounts payable
                
        Decorator description:
        - parameter : Automatic creation of response, abnormal treatment
        - parameter : Verifymount > 0
        - parameter :validation of category
                
        Args:
            amount: cost amount (certified by decorator)
            Category: Cost category (certified by decorator)
            description:
            accounts_payable: Recording as accounts payable
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        if dry_run:
            projected_cash = self.cash if accounts_payable else self.cash - amount
            projected_payable = self.liabilities["accounts_payable"] + (amount if accounts_payable else 0)
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "amount": amount,
                    "category": category,
                    "cash_after": projected_cash,
                    "accounts_payable_balance": projected_payable
                }
            )
        # Business logic
        old_cash = self.cash
        
        if accounts_payable:
            # Accounts payable are not payable immediately
            self.liabilities["accounts_payable"] += amount
            self.liabilities["total_liabilities"] += amount
            transaction_type = "payable"
            cash_after = self.cash
        else:
            # Immediate payment (permissible overdraft)
            self.cash -= amount
            cash_after = self.cash
            transaction_type = "expense"
        
        # Update cost records
        self.costs[category] += amount
        self.costs["total_cost"] += amount
        
        # Create transaction log
        transaction = self._create_transaction(
            tx_type=transaction_type,
            amount=amount,
            category=category,
            description=description,
            accounts_payable=accounts_payable,
            cash_before=old_cash,
            cash_after=cash_after
        )
        
        # Update Financial Status
        self._update_financial_state()
        
        # Returns Successful Response
        return self.success_response(
            response,
            f"Cost of ¥{amount:.2f} recorded for {category}",
            {
                "transaction_id": transaction["id"],
                "transaction_length": len(self.transactions),
                "cash_after": cash_after,
                "total_cost": self.costs["total_cost"],
                "accounts_payable_balance": self.liabilities["accounts_payable"],
                "financial": {
                    "cash_before": old_cash,
                    "cash_after": cash_after,
                    "amount": amount,
                    "accounts_payable": accounts_payable
                },
                "transaction": {
                    "id": transaction["id"],
                    "type": transaction["type"],
                    "category": transaction["category"]
                },
                "metrics": {
                    "total_cost": self.costs["total_cost"]
                }
            }
        )
    
    @with_response("pay_accounts_payable")
    @validate_positive("amount")
    def pay_accounts_payable(self, amount: float, description: str = "",
                            dry_run: bool = False,
                            response: ModuleResponse = None) -> ModuleResponse:
        """
        Payments payable
                
        Args:
            amount: Payments (validated by decorator > 0)
            description:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        # Validation of accounts payable balances
        if amount > self.liabilities["accounts_payable"]:
            return self.error_response(
                response,
                "INSUFFICIENT_ACCOUNTS_PAYABLE",
                f"应付账款余额不足。需要: ¥{amount:.2f}, 当前: ¥{self.liabilities['accounts_payable']:.2f}"
            )
        
        # Verification of cash balances
        if amount > self.cash:
            return self.error_response(
                response,
                "INSUFFICIENT_CASH",
                f"现金余额不足。需要: ¥{amount:.2f}, 当前: ¥{self.cash:.2f}"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "amount_paid": amount,
                    "remaining_payable": self.liabilities["accounts_payable"] - amount,
                    "cash_after": self.cash - amount
                }
            )
        
        # Business logic
        old_cash = self.cash
        self.cash -= amount
        self.liabilities["accounts_payable"] -= amount
        self.liabilities["total_liabilities"] = (
            self.liabilities["accounts_payable"] + 
            self.liabilities["other_liabilities"]
        )
        
        # Create transaction log
        transaction = self._create_transaction(
            tx_type="payable_payment",
            amount=amount,
            description=description,
            cash_before=old_cash,
            cash_after=self.cash
        )
        
        # Updated assets and early warning
        self.assets["cash"] = self.cash
        self._update_total_assets()
        self._check_cash_warning()
        
        # Returns Successful Response
        return self.success_response(
            response,
            f"Paid ¥{amount:.2f} towards accounts payable",
            {
                "transaction_id": transaction["id"],
                "amount_paid": amount,
                "remaining_payable": self.liabilities["accounts_payable"],
                "cash_after": self.cash,
                "financial": {
                    "cash_before": old_cash,
                    "cash_after": self.cash,
                    "amount_paid": amount,
                    "remaining_payable": self.liabilities["accounts_payable"]
                },
                "transaction": {
                    "id": transaction["id"],
                    "type": transaction["type"]
                }
            }
        )
    
    
    @with_response("record_asset_addition")
    @validate_positive("amount")
    @validate_choice("asset_type", "ASSET_TYPES")
    def record_asset_addition(self, asset_type: str, amount: float, 
                             description: str = "", depreciable: bool = False,
                             dry_run: bool = False,
                             response: ModuleResponse = None) -> ModuleResponse:
        """
        Increase in recorded assets
                
        Args:
            asset_type: Asset type (validated by decorator)
            amount: Amount (validated by decorator > 0)
            description:
            Depreciable: Depreciable
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "asset_type": asset_type,
                    "old_value": self.assets[asset_type],
                    "new_value": self.assets[asset_type] + amount
                }
            )
        old_value = self.assets[asset_type]
        self.assets[asset_type] += amount
        
        self._update_total_assets()
        self._calculate_financial_metrics()
        
        return self.success_response(
            response,
            f"Asset {asset_type} increased by ¥{amount:.2f}",
            {
                "asset_type": asset_type,
                "old_value": old_value,
                "new_value": self.assets[asset_type],
                "total_assets": self.assets["total_assets"],
                "depreciable": depreciable,
                "financial": {
                    "old_value": old_value,
                    "new_value": self.assets[asset_type],
                    "amount_added": amount,
                    "total_assets": self.assets["total_assets"]
                },
                "asset": {
                    "type": asset_type,
                    "depreciable": depreciable
                }
            }
        )
    
    @with_response("record_asset_depreciation")
    def record_asset_depreciation(self, annual_depreciation_rate: float = None,
                                 dry_run: bool = False,
                                 response: ModuleResponse = None) -> ModuleResponse:
        """
        Record depreciation of fixed assets
                
        Args:
            annual_depreciation_rate: Annual depreciation rate (optional, default configuration value)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        # Use the default depreciation rate of the configuration
        if annual_depreciation_rate is None:
            annual_depreciation_rate = self.config.DEFAULT_DEPRECIATION_RATE
        
        # Validate depreciation range
        if not self.config.is_valid_depreciation_rate(annual_depreciation_rate):
            return self.error_response(
                response,
                "INVALID_RATE",
                f"Depreciation rate must be between {self.config.MIN_DEPRECIATION_RATE} and {self.config.MAX_DEPRECIATION_RATE}"
            )
        
        # Calculated depreciation
        depreciation_amount = self.assets["fixed_assets"] * annual_depreciation_rate
        
        # Without fixed assets
        if depreciation_amount <= 0:
            return self.success_response(
                response,
                "No fixed assets to depreciate",
                {
                    "depreciation_amount": 0.0,
                    "accumulated_depreciation": self.assets["accumulated_depreciation"],
                    "fixed_assets_book_value": self.assets["fixed_assets"] - self.assets["accumulated_depreciation"],
                    "financial": {
                        "depreciation_amount": 0.0,
                        "accumulated_depreciation": self.assets["accumulated_depreciation"],
                        "fixed_assets_book_value": self.assets["fixed_assets"] - self.assets["accumulated_depreciation"]
                    }
                }
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "depreciation_amount": depreciation_amount,
                    "annual_depreciation_rate": annual_depreciation_rate
                }
            )
        
        # Record depreciation cost
        cost_result = self.add_cost(
            depreciation_amount,
            "depreciation",
            f"Annual depreciation at {annual_depreciation_rate*100:.1f}% rate"
        )
        
        if not cost_result.success:
            error_message = (
                cost_result.errors[0]["message"]
                if getattr(cost_result, "errors", None)
                else "折旧成本记录失败"
            )
            return self.error_response(
                response,
                "DEPRECIATION_COST_RECORD_FAILED",
                error_message,
                "Failed to record depreciation cost"
            )
        
        # Cumulative depreciation recorded
        self.assets["accumulated_depreciation"] += depreciation_amount
        self._update_total_assets()
        
        book_value = self.assets["fixed_assets"] - self.assets["accumulated_depreciation"]
        
        return self.success_response(
            response,
            f"Depreciation of ¥{depreciation_amount:.2f} recorded",
            {
                "depreciation_amount": depreciation_amount,
                "accumulated_depreciation": self.assets["accumulated_depreciation"],
                "fixed_assets_book_value": book_value,
                "annual_depreciation_rate": annual_depreciation_rate,
                "financial": {
                    "depreciation_amount": depreciation_amount,
                    "accumulated_depreciation": self.assets["accumulated_depreciation"],
                    "fixed_assets_book_value": book_value,
                    "annual_depreciation_rate": annual_depreciation_rate
                }
            }
        )
    
    @with_response("record_asset_disposal")
    @validate_positive("amount")
    @validate_positive("sale_price")
    @validate_choice("asset_type", "ASSET_TYPES")
    def record_asset_disposal(self, asset_type: str, amount: float, 
                             sale_price: float, description: str = "",
                             dry_run: bool = False,
                             response: ModuleResponse = None) -> ModuleResponse:
        """
        Record disposal of assets (sale of assets)
                
        Args:
            asset_type: Asset type (validated by decorator)
            amount: disposal amount (validated by decorator > 0)
            < x17/ >: Sales price (certified by decorator > 0)
            description:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Unified response object
                """
        # Validation of asset balances
        if amount > self.assets[asset_type]:
            return self.error_response(
                response,
                "INSUFFICIENT_ASSET_BALANCE",
                f"{asset_type} 资产余额不足。需要: ¥{amount:.2f}, 当前: ¥{self.assets[asset_type]:.2f}"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "asset_type": asset_type,
                    "asset_sold": amount,
                    "sale_price": sale_price,
                    "gain_loss": sale_price - amount
                }
            )
        
        # Reduction of assets
        old_asset_value = self.assets[asset_type]
        self.assets[asset_type] -= amount
        
        # Increase in cash (recording of income)
        revenue_result = self.add_revenue(
            sale_price,
            "asset_disposal",
            f"Sold {asset_type}: {description}"
        )
        
        if not revenue_result.success:
            # Restoration of assets
            self.assets[asset_type] += amount
            error_message = (
                revenue_result.errors[0]["message"]
                if getattr(revenue_result, "errors", None)
                else "资产处置收入记录失败"
            )
            return self.error_response(
                response,
                "ASSET_DISPOSAL_REVENUE_FAILED",
                error_message,
                "Failed to record asset disposal revenue"
            )
        
        self._update_total_assets()
        
        # Calculation of gains or losses
        gain_loss = sale_price - amount
        
        return self.success_response(
            response,
            f"Asset of ¥{amount:.2f} sold for ¥{sale_price:.2f}",
            {
                "transaction_id": revenue_result.data["transaction_id"],
                "asset_sold": amount,
                "sale_price": sale_price,
                "gain_loss": gain_loss,
                "remaining_asset": self.assets[asset_type],
                "old_asset_value": old_asset_value,
                "financial": {
                    "asset_sold": amount,
                    "sale_price": sale_price,
                    "gain_loss": gain_loss,
                    "remaining_asset": self.assets[asset_type]
                },
                "transaction": {
                    "id": revenue_result.data["transaction_id"],
                    "type": "asset_disposal"
                }
            }
        )
    
    
    @with_response("calculate_profit")
    @performance_monitor(log_slow_threshold=0.5)
    def calculate_profit(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculation of profit indicators
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include profit calculations
                """
        total_revenue = self.revenue["total_revenue"]
        total_cost = self.costs["total_cost"]
        
        # Gross profit = total income - direct cost
        direct_cost = (
            self.costs["raw_materials"] + 
            self.costs["production_cost"]
        )
        gross_profit = total_revenue - direct_cost
        
        # Net profit = total income - total cost
        net_profit = total_revenue - total_cost
        
        # Profit margin
        gross_profit_rate = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
        net_profit_rate = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # Balance of gains and losses analysis
        fixed_cost = (
            self.costs["labor_cost"] + 
            self.costs["market_cost"]
        )
        
        # Marginal Contribution Rate
        margin_contribution_rate = ((total_revenue - direct_cost) / total_revenue) if total_revenue > 0 else 0
        break_even_revenue = fixed_cost / margin_contribution_rate if margin_contribution_rate > 0 else float('inf')
        
        calculation_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        return self.success_response(
            response,
            "Profit calculation completed successfully",
            {
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "gross_profit": gross_profit,
                "net_profit": net_profit,
                "gross_profit_rate": gross_profit_rate,
                "net_profit_rate": net_profit_rate,
                "break_even_revenue": break_even_revenue,
                "is_profitable": net_profit > 0,
                "calculation_date": calculation_date,
                "financial": {
                    "total_revenue": total_revenue,
                    "total_cost": total_cost,
                    "gross_profit": gross_profit,
                    "net_profit": net_profit
                },
                "metrics": {
                    "gross_profit_rate": gross_profit_rate,
                    "net_profit_rate": net_profit_rate,
                    "break_even_revenue": break_even_revenue,
                    "is_profitable": net_profit > 0
                },
                "analysis": {
                    "direct_cost": direct_cost,
                    "fixed_cost": fixed_cost,
                    "margin_contribution_rate": margin_contribution_rate
                }
            }
        )
    
    
    @with_response("calculate_financial_indicators")
    def calculate_financial_indicators(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculate all financial indicators
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Include financial indicators and explanations
                """
        total_assets = self.assets["total_assets"]
        total_liabilities = self.liabilities["total_liabilities"]
        net_equity = total_assets - total_liabilities
        
        total_revenue = self.revenue["total_revenue"]
        total_cost = self.costs["total_cost"]
        net_profit = total_revenue - total_cost
        
        # Rate of return on investment (ROI)
        roi = ((net_equity - self.initial_cash) / self.initial_cash * 100) if self.initial_cash > 0 else 0
        
        # Net asset rate of return (ROE)
        roe = (net_profit / net_equity * 100) if net_equity > 0 else 0
        
        # Mobility ratio
        current_liabilities = self.liabilities["accounts_payable"]
        current_ratio = (self.cash / current_liabilities) if current_liabilities > 0 else 0
        
        # Asset turnover rate
        asset_turnover = (total_revenue / total_assets) if total_assets > 0 else 0
        
        indicators = {
            "roi": roi,
            "roe": roe,
            "current_ratio": current_ratio,
            "asset_turnover": asset_turnover,
            "net_equity": net_equity,
            "calculation_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }
        
        self.financial_metrics.update(indicators)
        interpretation = self._interpret_indicators(indicators)
        
        return self.success_response(
            response,
            "Financial indicators calculated successfully",
            {
                "indicators": indicators,
                "interpretation": interpretation,
                "financial": {
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "net_equity": net_equity
                },
                "metrics": {
                    "roi": roi,
                    "roe": roe,
                    "current_ratio": current_ratio,
                    "asset_turnover": asset_turnover
                },
                "analysis": {
                    "interpretation": interpretation
                }
            }
        )
    
    
    @with_response("generate_balance_sheet")
    def generate_balance_sheet(self, as_of_date: str = None,
                              response: ModuleResponse = None) -> ModuleResponse:
        """
        Generate balance sheet
                
        Args:
            as_of_date: Report due date (optional, default current date)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Includes balance sheet data
                """
        if not as_of_date:
            as_of_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Calculate book value
        fixed_assets_book_value = (
            self.assets["fixed_assets"] - self.assets["accumulated_depreciation"]
        )
        
        total_assets = (
            self.assets["cash"] +
            self.assets["inventory_value"] +
            fixed_assets_book_value
        )
        
        total_liabilities = self.liabilities["total_liabilities"]
        total_equity = total_assets - total_liabilities
        
        balance_sheet = {
            "as_of_date": as_of_date,
            "assets": {
                "current_assets": {
                    "cash": self.assets["cash"],
                    "inventory_value": self.assets["inventory_value"],
                    "total_current_assets": self.assets["cash"] + self.assets["inventory_value"]
                },
                "fixed_assets": {
                    "gross_value": self.assets["fixed_assets"],
                    "accumulated_depreciation": self.assets["accumulated_depreciation"],
                    "book_value": fixed_assets_book_value,
                    "total_fixed_assets": fixed_assets_book_value
                },
                "total_assets": total_assets
            },
            "liabilities": {
                "current_liabilities": {
                    "accounts_payable": self.liabilities["accounts_payable"],
                    "other_liabilities": self.liabilities["other_liabilities"],
                    "total_current_liabilities": self.liabilities["accounts_payable"] + self.liabilities["other_liabilities"]
                },
                "total_liabilities": total_liabilities
            },
            "equity": {
                "shareholders_equity": self.initial_cash,
                "retained_earnings": total_equity - self.initial_cash,
                "total_equity": total_equity
            },
            "is_balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.01,
            "generation_date": self.enterprise.time_manager.get_day(),
        }
        
        return self.success_response(
            response,
            f"Balance sheet generated as of {as_of_date}",
            {
                "balance_sheet": balance_sheet,
                "financial": {
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity
                },
                "report": {
                    "type": "balance_sheet",
                    "as_of_date": as_of_date,
                    "is_balanced": balance_sheet["is_balanced"]
                }
            }
        )
    
    @with_response("generate_income_statement")
    @validate_date_range()
    def generate_income_statement(self, start_date: str, end_date: str,
                                 response: ModuleResponse = None) -> ModuleResponse:
        """
        Generate income statement
                
        Decorator description:
        - parameter : Autovalidation of date range
                
        Args:
            start_date: Start date (YYYY-MM-DD, certified by decorator)
            end_date: End date (YYYY-MM-DD, certified by decorator)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include income statement data
                """
        # Transactions during the selection period
        period_transactions = [
            tx for tx in self.transactions
            if start_date <= tx["date"] <= end_date
        ]
        
        # Income and cost for the calculation period
        period_revenue = self.config.get_initial_revenue_dict()
        period_cost = self.config.get_initial_cost_dict()
        
        for tx in period_transactions:
            if tx["type"] == "income":
                source = tx.get("source", "other_income")
                if source in period_revenue:
                    period_revenue[source] += tx["amount"]
            elif tx["type"] in ["expense", "payable"]:
                category = tx.get("category", "other_cost")
                if category in period_cost:
                    period_cost[category] += tx["amount"]
        
        period_revenue["total_revenue"] = sum(
            v for k, v in period_revenue.items() if k != "total_revenue"
        )
        period_cost["total_cost"] = sum(
            v for k, v in period_cost.items() if k != "total_cost"
        )
        
        # Calculation of profit indicators
        direct_cost = period_cost["raw_materials"] + period_cost["production_cost"]
        gross_profit = period_revenue["total_revenue"] - direct_cost
        net_profit = period_revenue["total_revenue"] - period_cost["total_cost"]
        
        gross_margin = (gross_profit / period_revenue["total_revenue"] * 100) \
            if period_revenue["total_revenue"] > 0 else 0
        net_margin = (net_profit / period_revenue["total_revenue"] * 100) \
            if period_revenue["total_revenue"] > 0 else 0
        
        income_statement = {
            "period": {"start_date": start_date, "end_date": end_date},
            "revenue": period_revenue,
            "cost": period_cost,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "transaction_count": len(period_transactions),
            "generation_date": self.enterprise.time_manager.get_day(),
        }
        
        return self.success_response(
            response,
            f"Income statement generated for period {start_date} to {end_date}",
            {
                "income_statement": income_statement,
                "financial": {
                    "total_revenue": period_revenue["total_revenue"],
                    "total_cost": period_cost["total_cost"],
                    "gross_profit": gross_profit,
                    "net_profit": net_profit
                },
                "metrics": {
                    "gross_margin": gross_margin,
                    "net_margin": net_margin
                },
                "report": {
                    "type": "income_statement",
                    "period": {"start_date": start_date, "end_date": end_date},
                    "transaction_count": len(period_transactions)
                }
            }
        )
    
    @with_response("generate_cash_flow_statement")
    @validate_date_range()
    def generate_cash_flow_statement(self, start_date: str, end_date: str,
                                    response: ModuleResponse = None) -> ModuleResponse:
        """
        Statement of cash flows generated
                
        Args:
            parameter: Start date (validated by decorator)
            parameter: End date (validated by decorator)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Includes cash flow statement data
                """
        # Transactions during the selection period
        period_transactions = [
            tx for tx in self.transactions
            if start_date <= tx["date"] <= end_date
        ]
        
        # Calculate cash flow
        operating_cash_flow = 0.0
        investing_cash_flow = 0.0
        financing_cash_flow = 0.0
        
        for tx in period_transactions:
            if tx["type"] == "income":
                operating_cash_flow += tx["amount"]
            elif tx["type"] in ["expense", "payable"]:
                category = tx.get("category", "")
                if category in ["raw_materials", "production_cost", "labor_cost", "market_cost", "depreciation"]:
                    operating_cash_flow -= tx["amount"]
                else:
                    investing_cash_flow -= tx["amount"]
            elif tx["type"] == "payable_payment":
                operating_cash_flow -= tx["amount"]
        
        total_cash_flow = operating_cash_flow + investing_cash_flow + financing_cash_flow
        
        cash_flow_statement = {
            "period": {"start_date": start_date, "end_date": end_date},
            "operating_activities": {
                "description": "Cash from operations",
                "amount": operating_cash_flow
            },
            "investing_activities": {
                "description": "Cash from investments",
                "amount": investing_cash_flow
            },
            "financing_activities": {
                "description": "Cash from financing",
                "amount": financing_cash_flow
            },
            "total_cash_flow": total_cash_flow,
            "transaction_count": len(period_transactions),
            "generation_date":self.enterprise.time_manager.get_day(),
        }
        
        return self.success_response(
            response,
            f"Cash flow statement generated for period {start_date} to {end_date}",
            {
                "cash_flow_statement": cash_flow_statement,
                "financial": {
                    "operating_cash_flow": operating_cash_flow,
                    "investing_cash_flow": investing_cash_flow,
                    "financing_cash_flow": financing_cash_flow,
                    "total_cash_flow": total_cash_flow
                },
                "report": {
                    "type": "cash_flow_statement",
                    "period": {"start_date": start_date, "end_date": end_date},
                    "transaction_count": len(period_transactions)
                }
            }
        )
    
    
    @with_response("get_cash_warnings")
    def get_cash_warnings(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to early warning of cash flows
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModuleResponse: Include early warning information on cash flows
                """
        # Determine status (using configuration thresholds)
        status = (
            "critical" if self.cash < self.config.CASH_CRITICAL_THRESHOLD
            else "warning" if (self.cash < self.config.CASH_WARNING_THRESHOLD or len(self.warnings) > 0)
            else "normal"
        )
        
        return self.success_response(
            response,
            f"Cash warning check completed, status: {status}",
            {
                "warnings": self.warnings,
                "warning_count": len(self.warnings),
                "cash_balance": self.cash,
                "status": status,
                "financial": {
                    "cash_balance": self.cash
                },
                "alert": {
                    "status": status,
                    "warning_count": len(self.warnings),
                    "warnings": self.warnings
                }
            }
        )
    
    
    @with_response("get_financial_summary")
    def get_financial_summary(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to financial summary
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include financial summary information
                """
        profit_info = self.calculate_profit()
        indicators_info = self.calculate_financial_indicators()
        
        # Recent transactions
        recent_transactions = sorted(
            self.transactions[-10:],
            key=lambda x: x["timestamp"],
            reverse=True
        )
        
        return self.success_response(
            response,
            "Financial summary generated successfully",
            {
                "cash": self.cash,
                "total_revenue": self.revenue["total_revenue"],
                "total_cost": self.costs["total_cost"],
                "profit": profit_info.data.get("net_profit", 0),
                "profit_margin": profit_info.data.get("net_profit_rate", 0),
                "key_indicators": {
                    "roi": indicators_info.data["indicators"].get("roi", 0),
                    "roe": indicators_info.data["indicators"].get("roe", 0),
                    "current_ratio": indicators_info.data["indicators"].get("current_ratio", 0)
                },
                "total_assets": self.assets["total_assets"],
                "total_liabilities": self.liabilities["total_liabilities"],
                "recent_transactions": recent_transactions,
                "transaction_count": len(self.transactions),
                "warnings": self.warnings,
                "summary_date": self.enterprise.time_manager.get_day(),
                "financial": {
                    "cash": self.cash,
                    "total_revenue": self.revenue["total_revenue"],
                    "total_cost": self.costs["total_cost"],
                    "profit": profit_info.data.get("net_profit", 0),
                    "total_assets": self.assets["total_assets"],
                    "total_liabilities": self.liabilities["total_liabilities"]
                },
                "metrics": {
                    "profit_margin": profit_info.data.get("net_profit_rate", 0),
                    "key_indicators": {
                        "roi": indicators_info.data["indicators"].get("roi", 0),
                        "roe": indicators_info.data["indicators"].get("roe", 0),
                        "current_ratio": indicators_info.data["indicators"].get("current_ratio", 0)
                    }
                },
                "transactions": {
                    "recent": recent_transactions,
                    "count": len(self.transactions)
                }
            }
        )
    
    @with_response("get_transaction_history")
    def get_transaction_history(self, start_date: str = None, end_date: str = None, 
                               transaction_type: str = None,
                               response: ModuleResponse = None) -> ModuleResponse:
        """
        Access transaction history
                
        Args:
            start_date: Start date (optional)
            end_date: End date (optional)
            transaction_type: Transaction type (optional)
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include transaction history
                """
        result = self.transactions.copy()
        
        # Filter by Date
        if start_date:
            result = [tx for tx in result if tx["date"] >= start_date]
        if end_date:
            result = [tx for tx in result if tx["date"] <= end_date]
        
        # Filter by Type
        if transaction_type:
            result = [tx for tx in result if tx["type"] == transaction_type]
        
        # Sort in reverse order of time
        result.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return self.success_response(
            response,
            "Transaction history retrieved successfully",
            {
                "transactions": result,
                "total_count": len(result),
                "summary_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "filter": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "transaction_type": transaction_type
                },
                "transactions_data": {
                    "total_count": len(result),
                    "transactions": result
                }
            }
        )
    
    @with_response("get_balance")
    def get_balance(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Obtain current cash balance
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include balance information
                """
        return self.success_response(
            response,
            f"当前现金余额为 ¥{self.cash:.2f}",
            {"balance": self.cash}
        )
    
    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get Current Module Status
                
        Args:
            Response: Respond objects (injected by decorator)
                        
        Returns:
            ModeuleResponse: Include module status information
                """
        self._update_financial_state()
        self.get_financial_summary()
        state = {
            # "module_id": self.module_id,
            "module_type": self.module_type,
            # "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_revenue": self.revenue["total_revenue"],
            "total_cost": self.costs["total_cost"],
            "financial_indicators": self._get_financial_metrics(),
            "cash_summary": self._build_cash_summary(),
            # "cash_warnings": self.get_cash_warnings().data,
            # "balance_sheet": self.generate_balance_sheet().data,
        }
        
        return self.success_response(
            response,
            "Module state retrieved successfully",
            state
        )
    
    def _get_financial_metrics(self) -> Dict:
        """Obtain current financial indicators"""
        return {
            "net_profit": self.financial_metrics["net_profit"],
            "gross_profit": self.financial_metrics["gross_profit"],
            "net_profit_rate": self.financial_metrics["net_profit_rate"],
            "gross_profit_rate": self.financial_metrics["gross_profit_rate"],
            # "roi": self.financial_metrics["roi"],
            # "roe": self.financial_metrics["roe"],
            # "current_ratio": self.financial_metrics["current_ratio"],
            # "asset_turnover": self.financial_metrics["asset_turnover"]
        }

    def _build_cash_summary(self) -> Dict:
        """Generates a summary of cash constraints for business department."""
        warning_threshold = float(self.config.CASH_WARNING_THRESHOLD)
        critical_threshold = float(self.config.CASH_CRITICAL_THRESHOLD)
        available_after_warning = max(0.0, self.cash - warning_threshold)
        accounts_payable_balance = float(self.liabilities.get("accounts_payable", 0) or 0)
        if self.cash <= critical_threshold:
            cash_level = "critical"
        elif self.cash <= warning_threshold:
            cash_level = "warning"
        else:
            cash_level = "healthy"

        return {
            "current_cash": self.cash,
            "warning_threshold": warning_threshold,
            "critical_threshold": critical_threshold,
            "available_after_warning_buffer": available_after_warning,
            "cash_level": cash_level,
            "has_warning_buffer": self.cash > warning_threshold,
            "accounts_payable_balance": accounts_payable_balance,
        }

    
    def _create_transaction(self, tx_type: str, amount: float, **kwargs) -> Dict:
        """
        Unified creation of transaction records
                
        Args:
            parameter: Transaction type
            amount: Amount
            **kwargs: Other transaction properties
                        
        Returns:
            Dict: Transaction log
                """
        transaction = {
            "id": f"txn_{tx_type}_{self.enterprise.time_manager.get_day()}",
            "type": tx_type,
            "amount": amount,
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "enterprise_id": self.enterprise.id if hasattr(self.enterprise, "id") else "unknown",
            **kwargs
        }
        self.transactions.append(transaction)
        return transaction
    
    def _update_financial_state(self):
        """Harmonized update of financial status"""
        self.assets["cash"] = self.cash
        self._update_total_assets()
        self._calculate_financial_metrics()
        self._check_cash_warning()
        self.calculate_financial_indicators()
    
    def _update_total_assets(self):
        """Update total assets"""
        fixed_assets_book_value = (
            self.assets["fixed_assets"] - 
            self.assets["accumulated_depreciation"]
        )
        self.assets["total_assets"] = (
            self.assets["cash"] +
            self.assets["inventory_value"] +
            fixed_assets_book_value
        )
    
    def _calculate_financial_metrics(self):
        """Updated financial indicators"""
        self.financial_metrics["net_profit"] = (
            self.revenue["total_revenue"] - self.costs["total_cost"]
        )
        self.financial_metrics["gross_profit"] = (
            self.revenue["total_revenue"] - 
            (self.costs["raw_materials"] + self.costs["production_cost"])
        )
        
        if self.revenue["total_revenue"] > 0:
            self.financial_metrics["net_profit_rate"] = (
                self.financial_metrics["net_profit"] / 
                self.revenue["total_revenue"] * 100
            )
            self.financial_metrics["gross_profit_rate"] = (
                self.financial_metrics["gross_profit"] / 
                self.revenue["total_revenue"] * 100
            )
    
    def _check_cash_warning(self):
        """
        Check for cash flow early warning (using configuration thresholds)
                """
        self.warnings.clear()
        
        # Early warning of cash balances (using configuration thresholds)
        if self.cash < self.config.CASH_CRITICAL_THRESHOLD:
            self.warnings.append({
                "level": "CRITICAL",
                "message": "Negative cash balance - Enterprise overdraft",
                "amount": self.cash
            })
        elif self.cash < self.config.CASH_WARNING_THRESHOLD:
            self.warnings.append({
                "level": "WARNING",
                "message": f"Cash balance below ¥{self.config.CASH_WARNING_THRESHOLD:,.0f} threshold",
                "amount": self.cash
            })
        
        # Movement ratio early warning (using configuration thresholds)
        if self.liabilities["accounts_payable"] > 0:
            current_ratio = self.cash / self.liabilities["accounts_payable"]
            if current_ratio < self.config.CURRENT_RATIO_WARNING:
                self.warnings.append({
                    "level": "WARNING",
                    "message": f"Current ratio below {self.config.CURRENT_RATIO_WARNING} ({current_ratio:.2f}) - Potential liquidity issue",
                    "current_ratio": current_ratio
                })
    
    def _set_balance(self, balance_amount: float, reason: str = "Balance adjustment"):
        """
        Set financial balance (no old decorative method, keep backward compatibility)
                
        Args:
            balance_amount: Balance to set
            Reason for adjustment of balance
                        
        Returns:
            Dict: Operation Results
                """
        old_balance = self.cash
        self.cash = balance_amount
        self.assets["cash"] = balance_amount
        self._update_total_assets()
        
        self.transactions.append({
            "id": f"balance_{len(self.transactions)}_{self.enterprise.time_manager.get_day()}",
            "type": "income" if balance_amount > old_balance else "expense",
            "amount": abs(balance_amount - old_balance),
            "category": "balance_adjustment",
            "description": reason,
            "date": datetime.datetime.now().strftime("%Y-%m-%d")
        })
        
        return {
            "success": True,
            "old_balance": old_balance,
            "new_balance": balance_amount,
            "message": f"财务余额已设置为 {balance_amount}，原因: {reason}"
        }

    def _interpret_indicators(self, indicators: Dict) -> str:
        """
        Explanation of financial indicators (using the threshold of the configuration)
                
        Args:
            Indicators: Dictionary of Financial Indicators
                        
        Returns:
            st: Explanatory text
                """
        roi = indicators.get("roi", 0)
        roe = indicators.get("roe", 0)
        current_ratio = indicators.get("current_ratio", 0)
        
        # Use the configuration threshold for judgement
        if (roi > self.config.EXCELLENT_ROI and 
            roe > self.config.EXCELLENT_ROE and 
            current_ratio > self.config.EXCELLENT_CURRENT_RATIO):
            return "Excellent financial health. Strong profitability and liquidity."
        
        elif (roi > self.config.GOOD_ROI and 
              roe > self.config.GOOD_ROE and 
              current_ratio > self.config.GOOD_CURRENT_RATIO):
            return "Good financial health. Solid profitability and liquidity."
        
        elif (roi > self.config.ACCEPTABLE_ROI and 
              roe > self.config.ACCEPTABLE_ROE and 
              current_ratio > self.config.ACCEPTABLE_CURRENT_RATIO):
            return "Acceptable financial health. Room for improvement."
        
        elif current_ratio < self.config.ACCEPTABLE_CURRENT_RATIO:
            return "Warning: Poor liquidity. Difficulty meeting short-term obligations."
        
        else:
            return "Critical: Financial health needs improvement."
