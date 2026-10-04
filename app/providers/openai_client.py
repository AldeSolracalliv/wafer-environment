from __future__ import annotations

import os
from typing import Any

from app.models import ModelClient, ModelError, ModelMessage, ModelRequest, ModelResponse, ModelUsage


_MAX_OUTPUT_TOKENS = 800
_TIMEOUT_SECONDS = 30.0


class OpenAIModelClient(ModelClient):
    """Synchronous OpenAI Responses API adapter for Wafer's text contract."""

    def __init__(self, model: str, *, client: Any | None = None):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("An OpenAI model name is required.")
        self.model = model
        if client is not None:
            self._client = client
            return

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key or not api_key.strip():
            raise ModelError("OpenAI requires the OPENAI_API_KEY environment variable.")
        try:
            from openai import OpenAI
        except ImportError:
            raise ModelError(
                "The OpenAI SDK is unavailable; install Wafer with the 'openai' extra."
            ) from None
        try:
            self._client = OpenAI(
                api_key=api_key,
                max_retries=0,
                timeout=_TIMEOUT_SECONDS,
            )
        except Exception:
            raise ModelError("OpenAI client initialization failed.") from None

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        provider_messages = [_message_payload(message) for message in request.messages]
        try:
            response = self._client.responses.create(
                model=self.model,
                input=provider_messages,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                store=False,
            )
        except Exception:
            raise ModelError("OpenAI generation failed.") from None

        text = getattr(response, "output_text", None)
        if not isinstance(text, str):
            raise ModelError("OpenAI returned no text response.")

        usage = getattr(response, "usage", None)
        model_usage = None
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            if not _valid_count(input_tokens) or not _valid_count(output_tokens):
                raise ModelError("OpenAI returned invalid usage metadata.")
            model_usage = ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)

        response_model = getattr(response, "model", None)
        if response_model is not None and not isinstance(response_model, str):
            raise ModelError("OpenAI returned an invalid model identifier.")
        return ModelResponse(text=text, usage=model_usage, model=response_model)


def _message_payload(message: ModelMessage) -> dict[str, str]:
    if not isinstance(message, ModelMessage):
        raise TypeError("ModelRequest messages must be ModelMessage values")
    if message.role not in ("system", "user", "assistant") or not isinstance(message.content, str):
        raise ValueError("ModelMessage has invalid role or content")
    return {"role": message.role, "content": message.content}


def _valid_count(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)
