class BaseProcessor:
    def validate(self, data):
        if not data:
            raise ValueError("Empty data")
        return True

    def process(self, data):
        self.validate(data)
        return self._transform(data)

    def _transform(self, data):
        return data


class JSONProcessor(BaseProcessor):
    def _transform(self, data):
        import json
        return json.dumps(data)

    def compress(self, data):
        processed = self.process(data)
        return processed.encode()


class XMLProcessor(BaseProcessor):
    def _transform(self, data):
        return f"<data>{data}</data>"


class Pipeline:
    def __init__(self, processor):
        self.processor = processor

    def run(self, data):
        self.processor.validate(data)
        result = self.processor.process(data)
        return self._finalize(result)

    def _finalize(self, result):
        return {"output": result, "status": "done"}
