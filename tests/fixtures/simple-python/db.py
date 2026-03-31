_orders = {}
_next_id = 1


def save_order(order_data):
    """Save order to the database."""
    global _next_id
    order_data["id"] = _next_id
    order_data["status"] = "pending"
    _orders[_next_id] = order_data
    _next_id += 1
    return order_data


def get_order(order_id):
    """Get order by ID from the database."""
    return _orders.get(order_id)


def delete_order(order_id):
    """Delete order by ID."""
    if order_id in _orders:
        del _orders[order_id]
        return True
    return False
