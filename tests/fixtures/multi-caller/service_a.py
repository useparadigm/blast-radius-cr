from shared import validate, format_response, log_event


def create_user(data):
    validate(data)
    log_event("user_created", data)
    return format_response({"id": data["id"]}, status=201)


def update_user(data):
    validate(data)
    log_event("user_updated", data)
    return format_response(data)
