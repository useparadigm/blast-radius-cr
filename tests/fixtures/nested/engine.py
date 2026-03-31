def outer_process(data):
    def inner_helper(x):
        return x * 2

    results = [inner_helper(item) for item in data]
    return aggregate(results)


def aggregate(values):
    return sum(values)


def make_processor(multiplier):
    def processor(data):
        return [x * multiplier for x in data]
    return processor


class Executor:
    def run(self, items):
        def on_complete(result):
            return self.finalize(result)

        processed = outer_process(items)
        return on_complete(processed)

    def finalize(self, result):
        return {"result": result}
