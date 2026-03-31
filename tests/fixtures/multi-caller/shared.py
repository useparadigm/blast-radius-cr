def validate(data):
    """Called from many different files/functions."""
    if not isinstance(data, dict):
        raise TypeError("Expected dict")
    if "id" not in data:
        raise ValueError("Missing id")
    return True


def format_response(data, status=200):
    return {"status": status, "body": data}


def log_event(event_type, payload):
    print(f"[{event_type}] {payload}")
