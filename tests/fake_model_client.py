from app.models import ModelError, ModelRequest, ModelResponse


class FakeModelClient:
    """Deterministic test client that captures requests and can raise one safe error."""

    def __init__(self, response: ModelResponse | None = None, error: ModelError | None = None):
        if (response is None) == (error is None):
            raise ValueError("provide exactly one of response or error")
        self.response = response
        self.error = error
        self.requests: list[ModelRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response
