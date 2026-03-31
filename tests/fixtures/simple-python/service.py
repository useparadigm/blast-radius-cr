from utils import validate_order, calculate_tax
from db import save_order, get_order


def create_order(user_id, order_data):
    """Create a new order for a user."""
    validate_order(order_data)
    tax = calculate_tax(order_data["total"])
    order_data["tax"] = tax
    order_data["grand_total"] = order_data["total"] + tax
    order_data["user_id"] = user_id
    return save_order(order_data)


def get_order_summary(order_id):
    """Get a summary of an existing order."""
    order = get_order(order_id)
    if order is None:
        raise ValueError(f"Order {order_id} not found")
    return {
        "id": order["id"],
        "total": order["grand_total"],
        "status": order["status"],
    }
