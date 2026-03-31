from engine import outer_process, aggregate, make_processor, Executor


def run_batch(batches):
    results = []
    for batch in batches:
        result = outer_process(batch)
        results.append(result)
    return aggregate(results)


def run_custom(data, multiplier=3):
    proc = make_processor(multiplier)
    processed = proc(data)
    return aggregate(processed)


def run_executor(items):
    ex = Executor()
    return ex.run(items)
