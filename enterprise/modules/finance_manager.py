"""
财务管理模块

负责企业财务相关的业务逻辑，包括现金流管理、收入记录、成本记录、财务指标计算等
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
    处理企业财务相关的所有业务逻辑
    
    """
    
    def __init__(self, enterprise, initial_cash: float = 0, 
                 module_id: str = None, config: FinanceConfig = None):
        """
        初始化财务管理器
        
        Args:
            enterprise: 所属企业实例
            initial_cash: 初始现金余额
            module_id: 模块唯一标识（可选）
            config: 财务配置对象（可选，默认使用FinanceConfig()）
        """
        # 使用配置或默认配置
        self.config = config or FinanceConfig()
        
        # 调用父类初始化
        super().__init__(
            enterprise, 
            module_id or f"finance_{enterprise.id}",
            self.config
        )
        
        # 现金账户管理
        self.cash = initial_cash
        self.initial_cash = initial_cash
        
        # 交易记录
        self.transactions = []
        
        # 使用配置初始化数据结构
        self.revenue = self.config.get_initial_revenue_dict()
        self.costs = self.config.get_initial_cost_dict()
        self.assets = self.config.get_initial_assets_dict(initial_cash)
        self.liabilities = self.config.get_initial_liabilities_dict()
        self.financial_metrics = self.config.get_initial_financial_metrics_dict()
        
        # 预警列表
        self.warnings = []
        
        # 初始检查
        self._check_cash_warning()

        self.module_type="FinanceManager"
    
    # ==================== 现金流管理 ====================
    
    @with_response("add_revenue")
    @validate_positive("amount")
    @validate_choice("source", "REVENUE_SOURCES")
    def add_revenue(self, amount: float, source: str, description: str = "", 
                   order_id: str = None, buyer_enterprise_id: str = None,
                   dry_run: bool = False,
                   response: ModuleResponse = None) -> ModuleResponse:
        """
        记录收入 - 现金流入
        
        装饰器说明：
        - @with_response: 自动创建响应对象、异常处理
        - @validate_positive: 自动验证amount > 0
        - @validate_choice: 自动验证source在有效选项中
        
        Args:
            amount: 收入金额，必须>0（由装饰器验证）
            source: 收入来源（由装饰器验证）
            description: 详细描述
            order_id: 订单ID
            buyer_enterprise_id: 买方企业ID
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
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
        # 业务逻辑 - 参数已经被装饰器验证过了
        old_cash = self.cash
        self.cash += amount
        
        # 更新收入记录
        self.revenue[source] += amount
        self.revenue["total_revenue"] += amount
        
        # 创建交易记录（使用辅助方法）
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
        
        # 更新财务状态（统一方法）
        self._update_financial_state()
        
        # 返回成功响应（装饰器会自动处理警告）
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
        记录成本/支出 - 现金流出或应付账款
        
        装饰器说明：
        - @with_response: 自动创建响应、异常处理
        - @validate_positive: 验证amount > 0
        - @validate_choice: 验证category有效性
        
        Args:
            amount: 成本金额（由装饰器验证）
            category: 成本类别（由装饰器验证）
            description: 详细描述
            accounts_payable: 是否记为应付账款
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
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
        # 业务逻辑
        old_cash = self.cash
        
        if accounts_payable:
            # 记为应付账款，不立即支付
            self.liabilities["accounts_payable"] += amount
            self.liabilities["total_liabilities"] += amount
            transaction_type = "payable"
            cash_after = self.cash
        else:
            # 立即支付（允许透支）
            self.cash -= amount
            cash_after = self.cash
            transaction_type = "expense"
        
        # 更新成本记录
        self.costs[category] += amount
        self.costs["total_cost"] += amount
        
        # 创建交易记录
        transaction = self._create_transaction(
            tx_type=transaction_type,
            amount=amount,
            category=category,
            description=description,
            accounts_payable=accounts_payable,
            cash_before=old_cash,
            cash_after=cash_after
        )
        
        # 更新财务状态
        self._update_financial_state()
        
        # 返回成功响应
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
        支付应付账款
        
        Args:
            amount: 支付金额（由装饰器验证 > 0）
            description: 描述
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
        """
        # 验证应付账款余额
        if amount > self.liabilities["accounts_payable"]:
            return self.error_response(
                response,
                "INSUFFICIENT_ACCOUNTS_PAYABLE",
                f"应付账款余额不足。需要: ¥{amount:.2f}, 当前: ¥{self.liabilities['accounts_payable']:.2f}"
            )
        
        # 验证现金余额
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
        
        # 业务逻辑
        old_cash = self.cash
        self.cash -= amount
        self.liabilities["accounts_payable"] -= amount
        self.liabilities["total_liabilities"] = (
            self.liabilities["accounts_payable"] + 
            self.liabilities["other_liabilities"]
        )
        
        # 创建交易记录
        transaction = self._create_transaction(
            tx_type="payable_payment",
            amount=amount,
            description=description,
            cash_before=old_cash,
            cash_after=self.cash
        )
        
        # 更新资产和预警
        self.assets["cash"] = self.cash
        self._update_total_assets()
        self._check_cash_warning()
        
        # 返回成功响应
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
    
    # ==================== 资产管理 ====================
    
    @with_response("record_asset_addition")
    @validate_positive("amount")
    @validate_choice("asset_type", "ASSET_TYPES")
    def record_asset_addition(self, asset_type: str, amount: float, 
                             description: str = "", depreciable: bool = False,
                             dry_run: bool = False,
                             response: ModuleResponse = None) -> ModuleResponse:
        """
        记录资产增加
        
        Args:
            asset_type: 资产类型（由装饰器验证）
            amount: 金额（由装饰器验证 > 0）
            description: 描述
            depreciable: 是否可折旧
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
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
        记录固定资产折旧
        
        Args:
            annual_depreciation_rate: 年折旧率（可选，默认使用配置值）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
        """
        # 使用配置的默认折旧率
        if annual_depreciation_rate is None:
            annual_depreciation_rate = self.config.DEFAULT_DEPRECIATION_RATE
        
        # 验证折旧率范围
        if not self.config.is_valid_depreciation_rate(annual_depreciation_rate):
            return self.error_response(
                response,
                "INVALID_RATE",
                f"Depreciation rate must be between {self.config.MIN_DEPRECIATION_RATE} and {self.config.MAX_DEPRECIATION_RATE}"
            )
        
        # 计算折旧额
        depreciation_amount = self.assets["fixed_assets"] * annual_depreciation_rate
        
        # 若无固定资产
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
        
        # 记录折旧成本
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
        
        # 记录累计折旧
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
        记录资产处置（出售资产）
        
        Args:
            asset_type: 资产类型（由装饰器验证）
            amount: 处置金额（由装饰器验证 > 0）
            sale_price: 销售价格（由装饰器验证 > 0）
            description: 描述
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 统一响应对象
        """
        # 验证资产余额
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
        
        # 减少资产
        old_asset_value = self.assets[asset_type]
        self.assets[asset_type] -= amount
        
        # 增加现金（记录收入）
        revenue_result = self.add_revenue(
            sale_price,
            "asset_disposal",
            f"Sold {asset_type}: {description}"
        )
        
        if not revenue_result.success:
            # 恢复资产
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
        
        # 计算收益或损失
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
    
    # ==================== 利润计算 ====================
    
    @with_response("calculate_profit")
    @performance_monitor(log_slow_threshold=0.5)
    def calculate_profit(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算利润指标
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含利润计算结果
        """
        total_revenue = self.revenue["total_revenue"]
        total_cost = self.costs["total_cost"]
        
        # 毛利润 = 总收入 - 直接成本
        direct_cost = (
            self.costs["raw_materials"] + 
            self.costs["production_cost"]
        )
        gross_profit = total_revenue - direct_cost
        
        # 净利润 = 总收入 - 总成本
        net_profit = total_revenue - total_cost
        
        # 利润率
        gross_profit_rate = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
        net_profit_rate = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # 盈亏平衡点分析
        fixed_cost = (
            self.costs["labor_cost"] + 
            self.costs["market_cost"]
        )
        
        # 边际贡献率
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
    
    # ==================== 财务指标 ====================
    
    @with_response("calculate_financial_indicators")
    def calculate_financial_indicators(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算所有财务指标
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含财务指标和解释
        """
        total_assets = self.assets["total_assets"]
        total_liabilities = self.liabilities["total_liabilities"]
        net_equity = total_assets - total_liabilities
        
        total_revenue = self.revenue["total_revenue"]
        total_cost = self.costs["total_cost"]
        net_profit = total_revenue - total_cost
        
        # 投资回报率(ROI)
        roi = ((net_equity - self.initial_cash) / self.initial_cash * 100) if self.initial_cash > 0 else 0
        
        # 净资产收益率(ROE)
        roe = (net_profit / net_equity * 100) if net_equity > 0 else 0
        
        # 流动比率
        current_liabilities = self.liabilities["accounts_payable"]
        current_ratio = (self.cash / current_liabilities) if current_liabilities > 0 else 0
        
        # 资产周转率
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
    
    # ==================== 财务报表 ====================
    
    @with_response("generate_balance_sheet")
    def generate_balance_sheet(self, as_of_date: str = None,
                              response: ModuleResponse = None) -> ModuleResponse:
        """
        生成资产负债表
        
        Args:
            as_of_date: 报表截至日期（可选，默认当前日期）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含资产负债表数据
        """
        if not as_of_date:
            as_of_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 计算账面价值
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
        生成损益表
        
        装饰器说明：
        - @validate_date_range: 自动验证日期范围有效性
        
        Args:
            start_date: 开始日期（YYYY-MM-DD，由装饰器验证）
            end_date: 结束日期（YYYY-MM-DD，由装饰器验证）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含损益表数据
        """
        # 筛选期间内的交易
        period_transactions = [
            tx for tx in self.transactions
            if start_date <= tx["date"] <= end_date
        ]
        
        # 计算期间收入和成本
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
        
        # 计算利润指标
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
        生成现金流量表
        
        Args:
            start_date: 开始日期（由装饰器验证）
            end_date: 结束日期（由装饰器验证）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含现金流量表数据
        """
        # 筛选期间内的交易
        period_transactions = [
            tx for tx in self.transactions
            if start_date <= tx["date"] <= end_date
        ]
        
        # 计算现金流
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
    
    # ==================== 现金流预警 ====================
    
    @with_response("get_cash_warnings")
    def get_cash_warnings(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取现金流预警
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含现金流预警信息
        """
        # 确定状态（使用配置的阈值）
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
    
    # ==================== 财务摘要 ====================
    
    @with_response("get_financial_summary")
    def get_financial_summary(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取财务摘要
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含财务摘要信息
        """
        profit_info = self.calculate_profit()
        indicators_info = self.calculate_financial_indicators()
        
        # 最近交易
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
        获取交易历史记录
        
        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            transaction_type: 交易类型（可选）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含交易历史记录
        """
        result = self.transactions.copy()
        
        # 按日期筛选
        if start_date:
            result = [tx for tx in result if tx["date"] >= start_date]
        if end_date:
            result = [tx for tx in result if tx["date"] <= end_date]
        
        # 按类型筛选
        if transaction_type:
            result = [tx for tx in result if tx["type"] == transaction_type]
        
        # 按时间倒序排列
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
        获取当前现金余额
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含余额信息
        """
        return self.success_response(
            response,
            f"当前现金余额为 ¥{self.cash:.2f}",
            {"balance": self.cash}
        )
    
    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取当前模块状态
        
        Args:
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含模块状态信息
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
        """获取当前财务指标"""
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
        """生成供业务部门读取的现金约束摘要。"""
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

    # ==================== 内部辅助方法 ====================
    
    def _create_transaction(self, tx_type: str, amount: float, **kwargs) -> Dict:
        """
        统一创建交易记录
        
        Args:
            tx_type: 交易类型
            amount: 金额
            **kwargs: 其他交易属性
            
        Returns:
            Dict: 交易记录
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
        """统一更新财务状态"""
        self.assets["cash"] = self.cash
        self._update_total_assets()
        self._calculate_financial_metrics()
        self._check_cash_warning()
        self.calculate_financial_indicators()
    
    def _update_total_assets(self):
        """更新总资产"""
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
        """更新财务指标"""
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
        检查现金流预警（使用配置的阈值）
        """
        self.warnings.clear()
        
        # 现金余额预警（使用配置的阈值）
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
        
        # 流动比率预警（使用配置的阈值）
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
        设置财务余额（不使用装饰器的旧方法，保持向后兼容）
        
        Args:
            balance_amount: 要设置的余额金额
            reason: 调整余额的原因
            
        Returns:
            Dict: 操作结果
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
        解释财务指标（使用配置的阈值）
        
        Args:
            indicators: 财务指标字典
            
        Returns:
            str: 解释文本
        """
        roi = indicators.get("roi", 0)
        roe = indicators.get("roe", 0)
        current_ratio = indicators.get("current_ratio", 0)
        
        # 使用配置的阈值进行判断
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
