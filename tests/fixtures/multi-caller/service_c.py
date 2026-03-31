from shared import validate, log_event


def process_webhook(payload):
    validate(payload)
    log_event("webhook_received", payload)
    return handle_event(payload)


def handle_event(payload):
    event_type = payload.get("type", "unknown")
    log_event("event_handled", {"type": event_type})
    return {"processed": True}
