def compute_score(values):
    total = sum(values)
    return total / len(values) if values else 0


def normalize(data):
    max_val = max(data) if data else 1
    return [x / max_val for x in data]


# Alias
calc_score = compute_score
norm = normalize
