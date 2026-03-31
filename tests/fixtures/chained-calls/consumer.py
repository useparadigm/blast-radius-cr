from chain import full_pipeline, partial_pipeline, step_one, Builder


def process_input(raw_text):
    return full_pipeline(raw_text)


def quick_process(raw_text):
    return partial_pipeline(raw_text)


def custom_process(raw_text):
    first = step_one(raw_text)
    return first.upper()


def build_something(raw):
    b = Builder()
    return b.build(raw)
