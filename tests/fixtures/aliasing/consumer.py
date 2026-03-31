from utils import compute_score, calc_score, normalize, norm


def report_direct(values):
    """Calls the original name."""
    score = compute_score(values)
    return f"Score: {score}"


def report_alias(values):
    """Calls the alias name."""
    score = calc_score(values)
    return f"Score: {score}"


def pipeline_direct(data):
    normed = normalize(data)
    return compute_score(normed)


def pipeline_alias(data):
    normed = norm(data)
    return calc_score(normed)
