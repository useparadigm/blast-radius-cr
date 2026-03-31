from shared import validate, format_response, log_event


def create_order(data):
    validate(data)
    total = sum(item["price"] for item in data.get("items", []))
    log_event("order_created", {"id": data["id"], "total": total})
    return format_response({"id": data["id"], "total": total}, status=201)


def cancel_order(data):
    validate(data)
    log_event("order_cancelled", data)
    return format_response({"cancelled": True})
