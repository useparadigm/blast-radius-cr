def step_one(data):
    return data.strip()


def step_two(data):
    return data.lower()


def step_three(data):
    return data.replace(" ", "_")


def full_pipeline(data):
    """Chains multiple steps — all are callees."""
    a = step_one(data)
    b = step_two(a)
    c = step_three(b)
    return c


def partial_pipeline(data):
    """Only uses some steps."""
    a = step_one(data)
    return step_three(a)


class Builder:
    def build(self, raw):
        cleaned = step_one(raw)
        normalized = step_two(cleaned)
        return self.finalize(normalized)

    def finalize(self, data):
        return {"built": data}
