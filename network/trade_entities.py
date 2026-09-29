from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

@dataclass
class BuyRequest:
    request_id: str
    buyer_company_id: str
    product_id: str
    quantity: float
    created_round: int
    max_price: Optional[float] = None
    expected_due_round: Optional[int] = None

    open_quantity: float = field(init=False)
    active: bool = field(default=True, init=False)
    lifecycle_status: str = field(default="open", init=False)
    expires_round: Optional[int] = None
    closed_round: Optional[int] = None
    superseded_by_request_id: Optional[str] = None
    last_proposal_round: Optional[int] = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("BuyRequest.quantity must be > 0")
        self.open_quantity = self.quantity


@dataclass
class SellRequest:
    request_id: str
    seller_company_id: str
    product_id: str
    quantity: float
    created_round: int
    min_price: Optional[float] = None
    lead_time: int = 1

    open_quantity: float = field(init=False)
    active: bool = field(default=True, init=False)
    lifecycle_status: str = field(default="open", init=False)
    expires_round: Optional[int] = None
    closed_round: Optional[int] = None
    superseded_by_request_id: Optional[str] = None
    last_proposal_round: Optional[int] = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("SellRequest.quantity must be > 0")
        self.open_quantity = self.quantity


@dataclass
class OrderProposal:
    proposal_id: str
    buy_request_id: str
    sell_request_id: str
    buyer_company_id: str
    seller_company_id: str
    product_id: str
    quantity: float
    proposed_price: Optional[float]
    proposed_delivery_round: int
    created_round: int

    status: str = "pending"  # pending / accepted / rejected / confirmed
    dispatched: bool = False
    buyer_response: Optional[str] = None
    seller_response: Optional[str] = None
    route: str = "explicit"
    expires_round: Optional[int] = None
    closed_round: Optional[int] = None
    source_request_created_round: Optional[int] = None
    due_date_source: str = "default_plus_one"
    original_proposed_delivery_round: Optional[int] = None
    delivery_round_rebased: bool = False


@dataclass
class Order:
    order_id: str
    proposal_id: str
    buyer_company_id: str
    seller_company_id: str
    product_id: str
    quantity: float
    agreed_price: Optional[float]
    created_round: int
    planned_delivery_round: int

    status: str = "confirmed"  # confirmed / delivered
    buyer_processed: bool = False
    seller_processed: bool = False
    due_date_source: str = "default_plus_one"
    original_planned_delivery_round: Optional[int] = None
    delivery_round_rebased: bool = False


@dataclass
class DeliveryReceipt:
    order_id: str
    buyer_company_id: str
    seller_company_id: str
    product_id: str
    quantity: float
    delivered_round: int
