"""Opt-in live smoke test; excluded from the repository's normal pytest suite."""

import os

import pytest

from app.models import ModelMessage, ModelRequest
from app.providers.openai_client import OpenAIModelClient


def test_openai_model_client_generates_a_response():
    if os.environ.get("WAFER_RUN_OPENAI_SMOKE") != "1":
        pytest.skip("set WAFER_RUN_OPENAI_SMOKE=1 to opt into the live provider test")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    model = os.environ.get("WAFER_OPENAI_MODEL")
    if not model:
        pytest.skip("WAFER_OPENAI_MODEL is not configured")
    pytest.importorskip("openai", reason="install Wafer with the openai extra")

    client = OpenAIModelClient(model)
    result = client.generate(ModelRequest((ModelMessage(
        "user", "Reply with exactly this token and nothing else: WAFER_PROVIDER_SMOKE_OK"
    ),)))

    assert isinstance(result.text, str) and result.text.strip()
    assert "WAFER_PROVIDER_SMOKE_OK" in result.text
    assert result.model
