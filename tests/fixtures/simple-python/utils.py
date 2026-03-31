def validate_order(order_data):
    """Validate order data before processing."""
    if not order_data.get("items"):
        raise ValueError("Order must have items")
    if order_data.get("total", 0) <= 0:
        raise ValueError("Order total must be positive")
    return True


def calculate_tax(amount, rate=0.1):
    """Calculate tax for a given amount."""
    return round(amount * rate, 2)


def format_currency(amount):
    """Format amount as currency string."""
    return f"${amount:.2f}"
