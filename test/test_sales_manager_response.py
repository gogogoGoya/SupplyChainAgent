from enterprise.modules.response_model import ModuleResponse
from enterprise.modules.sales_manager import SalesManager
from types import SimpleNamespace


def test_sales_manager_extracts_error_text_from_module_response():
    response = ModuleResponse(success=False, message="库存扣减失败")

    assert SalesManager._response_error_text(response) == "库存扣减失败"


def test_sales_manager_extracts_error_text_from_response_errors():
    response = ModuleResponse(success=False)
    response.errors = [{"code": "NO_STOCK", "message": "库存不足"}]

    assert SalesManager._response_error_text(response) == "库存不足"


def test_sales_manager_expires_unselected_fixed_offer_after_expiry_day():
    manager = SalesManager.__new__(SalesManager)
    manager.module_id = "sales_Manufacturer"
    manager.module_type = "SalesManager"
    manager.enterprise = SimpleNamespace(
        time_manager=SimpleNamespace(get_day=lambda: 11)
    )
    manager.sales_orders = [
        {
            "order_id": "SALE_ORDER_1",
            "product_id": "PRODUCT_1",
            "quantity": 180,
            "status": "available",
            "offer_expiry_day": 10,
            "delivery_deadline": 12,
        }
    ]
    manager.sales_metrics = {"expired_orders": 0}
    manager._record_downstream_demand = lambda *args, **kwargs: None
    manager._log_event = lambda *args, **kwargs: None
    manager._refresh_service_level_metrics = lambda: None

    response = manager.check_deliverable_orders()

    assert response.success is True
    assert manager.sales_orders[0]["status"] == "expired"
    assert manager.sales_metrics["expired_orders"] == 1
