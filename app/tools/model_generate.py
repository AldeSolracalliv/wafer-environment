from typing import Any

from app.models import ModelClient, ModelError, ModelMessage, ModelRequest, ModelResponse, ModelUsage
from app.security.permissions import Permission
from app.tools.registry import Tool


MODEL_GENERATE_TOOL = "model.generate"
_ROLES = {"system", "user", "assistant"}
_MAX_MESSAGES = 20
_MAX_MESSAGE_CHARS = 16_000
_MAX_TOTAL_INPUT_CHARS = 16_000
_MAX_RESPONSE_CHARS = 8_000


def create_model_generation_tool(client: ModelClient) -> Tool:
    """Wrap one configured model client in Wafer's permission-checked tool API."""

    def generate(parameters: dict[str, Any]) -> dict[str, Any]:
        request = _parse_request(parameters)
        try:
            response = client.generate(request)
        except Exception as error:
            raise ModelError("Model generation failed.") from error
        if not isinstance(response, ModelResponse):
            raise ValueError("ModelClient returned an invalid response.")
        if not isinstance(response.text, str) or len(response.text) > _MAX_RESPONSE_CHARS:
            raise ValueError("ModelClient response text is invalid or exceeds the size limit.")
        if response.model is not None and (
            not isinstance(response.model, str) or len(response.model) > 128
        ):
            raise ValueError("ModelClient response model must be a string.")
        result: dict[str, Any] = {"text": response.text}
        if response.model is not None:
            result["model"] = response.model
        if response.usage is not None:
            result["usage"] = _usage_mapping(response.usage)
        return result

    return Tool(
        name=MODEL_GENERATE_TOOL,
        description="Generate one text response using the host-configured model client.",
        parameter_schema={
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": sorted(_ROLES)},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["messages"],
            "additionalProperties": False,
        },
        required_permission=Permission.EXECUTE,
        implementation=generate,
    )


def _parse_request(parameters: Any) -> ModelRequest:
    if not isinstance(parameters, dict) or set(parameters) != {"messages"}:
        raise ValueError("model.generate requires only a messages array.")
    messages = parameters["messages"]
    if not isinstance(messages, list) or not messages or len(messages) > _MAX_MESSAGES:
        raise ValueError(f"messages must contain between 1 and {_MAX_MESSAGES} entries.")

    parsed: list[ModelMessage] = []
    total_content_chars = 0
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError("each model message must contain only role and content.")
        role = message["role"]
        content = message["content"]
        if not isinstance(role, str) or role not in _ROLES:
            raise ValueError("model message role is invalid.")
        if not isinstance(content, str) or len(content) > _MAX_MESSAGE_CHARS:
            raise ValueError("model message content must be text within the size limit.")
        total_content_chars += len(content)
        if total_content_chars > _MAX_TOTAL_INPUT_CHARS:
            raise ValueError("combined model message content exceeds the size limit.")
        parsed.append(ModelMessage(role=role, content=content))
    return ModelRequest(messages=tuple(parsed))


def _usage_mapping(usage: ModelUsage) -> dict[str, int | None]:
    if not isinstance(usage, ModelUsage):
        raise ValueError("ModelClient returned invalid usage information.")
    counts = (usage.input_tokens, usage.output_tokens)
    if any(value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0)
           for value in counts):
        raise ValueError("ModelClient usage counts must be non-negative integers.")
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
