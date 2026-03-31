from service import create_order, get_order_summary


def handle_create_order(request):
    """API handler for creating orders."""
    user_id = request["user_id"]
    order_data = request["body"]
    try:
        order = create_order(user_id, order_data)
        return {"status": 201, "body": order}
    except ValueError as e:
        return {"status": 400, "body": {"error": str(e)}}


def handle_get_order(request):
    """API handler for getting order details."""
    order_id = request["params"]["order_id"]
    try:
        summary = get_order_summary(order_id)
        return {"status": 200, "body": summary}
    except ValueError as e:
        return {"status": 404, "body": {"error": str(e)}}
