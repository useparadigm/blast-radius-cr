from models import JSONProcessor, Pipeline, BaseProcessor


def create_pipeline():
    proc = JSONProcessor()
    return Pipeline(proc)


def handle_request(data):
    pipeline = create_pipeline()
    return pipeline.run(data)


def validate_input(data):
    """Standalone function that also calls validate on a processor."""
    proc = BaseProcessor()
    proc.validate(data)
    return True
