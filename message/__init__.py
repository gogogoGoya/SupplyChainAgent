"""
Message System Module

Responsible for communication and information transmission between enterprise
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
