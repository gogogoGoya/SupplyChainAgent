"""
消息系统模块

负责企业间的通信和信息传递
"""

from .message_manager import MessageManager, MESSAGE_TYPES
from .message_handlers import (
    MessageHandler,
    OrderHandler,
    PaymentHandler,
    InventoryHandler,
    PriceChangeHandler,
    SupplyChainEventHandler,
    BusinessDevelopmentHandler,
    FinancialReportHandler,
    create_message_handler,
    MessageBus
)

__all__ = [
    "MessageManager",
    "MESSAGE_TYPES",
    "MessageHandler",
    "OrderHandler",
    "PaymentHandler",
    "InventoryHandler",
    "PriceChangeHandler",
    "SupplyChainEventHandler",
    "BusinessDevelopmentHandler",
    "FinancialReportHandler",
    "create_message_handler",
    "MessageBus"
]