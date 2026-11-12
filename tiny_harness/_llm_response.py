class ResponseAdapter:
    def __init__(self, data: dict):
        self.content = [BlockAdapter(block) for block in data.get("content", [])]
        self.usage = UsageAdapter(data.get("usage", {}))
        self.model = data.get("model", "")
        self.stop_reason = data.get("stop_reason", "stop")


class BlockAdapter:
    def __init__(self, data: dict):
        self.type = data.get("type", "")
        self.text = data.get("text", "")
        self.name = data.get("name", "")
        self.input = data.get("input", {})
        self.id = data.get("id", "")


class UsageAdapter:
    def __init__(self, data: dict):
        self.input_tokens = data.get("input_tokens", 0)
        self.output_tokens = data.get("output_tokens", 0)
