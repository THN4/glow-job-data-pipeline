"""Provider contract tests; no AWS credentials or model calls required."""

import asyncio
import base64
import json
from unittest.mock import Mock

import pytest

from src.resume.config import ResumeModelSettings
from src.resume.errors import ResumeProcessingError
from src.resume.extraction.contracts import PageImage, PreparedCv, PreparedPage
from src.resume.extraction.prompt import SYSTEM_PROMPT, USER_INSTRUCTIONS
from src.resume.extraction.providers import create_extractor
from src.resume.extraction.providers import bedrock
from src.resume.extraction.providers.mock import mock_extraction


def response(text, stop="end_turn"):
    return {"stopReason": stop, "output": {"message": {"content": [{"text": text}]}},
            "usage": {"inputTokens": 11, "outputTokens": 7}}


def setup_client(monkeypatch, *responses):
    client = Mock()
    client.converse.side_effect = responses
    monkeypatch.setattr(bedrock, "create_bedrock_client", Mock(return_value=client))
    return client


def run(extractor=None, prepared=None):
    return asyncio.run((extractor or bedrock.BedrockExtractor()).extract(
        prepared or PreparedCv(kind="text", page_count=1, text="Synthetic CV")))


def test_factory_uses_nova_without_gemini_key(monkeypatch):
    cfg = ResumeModelSettings(_env_file=None, RESUME_EXTRACTOR="bedrock_converse",
                              BEDROCK_EXTRACTION_MODEL="us.amazon.nova-pro-v1:0")
    extractor = create_extractor(cfg)
    assert extractor.provider == "bedrock_converse"
    assert extractor.name == "us.amazon.nova-pro-v1:0"
    assert extractor.groundable


def test_text_contract_prompt_usage_and_cache(monkeypatch):
    expected = mock_extraction()
    client = setup_client(monkeypatch, response(expected.model_dump_json(by_alias=True)))
    extractor = bedrock.BedrockExtractor()
    result = run(extractor)
    assert result.extraction == expected
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 7)
    request = client.converse.call_args.kwargs
    assert request["modelId"] == "amazon.nova-pro-v1:0"
    assert request["system"][0]["text"].startswith(SYSTEM_PROMPT)
    assert json.dumps(expected.model_json_schema(by_alias=True)) in request["system"][0]["text"]
    assert request["messages"][0]["content"] == [{"text": f"<cv>\nSynthetic CV\n</cv>\n\n{USER_INSTRUCTIONS}"}]
    assert extractor.cache_identity["maxOutputTokens"] == request["inferenceConfig"]["maxTokens"]
    client.close.assert_called_once()


def test_schema_repair_preserves_input_and_accumulates_usage(monkeypatch):
    client = setup_client(monkeypatch, response("{}"), response(mock_extraction().model_dump_json(by_alias=True)))
    result = run()
    assert result.usage.input_tokens == 22
    assert result.usage.output_tokens == 14
    first, second = [call.kwargs for call in client.converse.call_args_list]
    assert first["messages"][0]["content"][0] == second["messages"][0]["content"][0]
    assert "Previous response:\n{}" in second["messages"][0]["content"][1]["text"]
    assert len(second["messages"][0]["content"]) == 3


def test_repeated_schema_failure_is_not_accepted(monkeypatch):
    client = setup_client(monkeypatch, response("{}"), response("{}"))
    with pytest.raises(ResumeProcessingError) as error:
        run()
    assert error.value.code == "EXTRACTION_FAILED"
    assert client.converse.call_count == 2
    client.close.assert_called_once()


def test_mixed_pages_keep_order_images_and_omission_notice(monkeypatch):
    client = setup_client(monkeypatch, response(mock_extraction().model_dump_json(by_alias=True)))
    image = PageImage(base64.b64encode(b"synthetic-image").decode(), "image/png")
    run(prepared=PreparedCv(kind="mixed", page_count=3,
        pages=[PreparedPage(1, text="page one"), PreparedPage(2, image=image)], omitted_pages=[3]))
    content = client.converse.call_args.kwargs["messages"][0]["content"]
    assert content[1] == {"text": "--- page 1 (text) ---\npage one\n"}
    assert content[2] == {"text": "--- page 2 (scanned image) ---"}
    assert content[3] == {"image": {"format": "png", "source": {"bytes": b"synthetic-image"}}}
    assert content[4]["text"].startswith("Omitted scanned PDF pages: 3.")


def test_image_only_cv(monkeypatch):
    client = setup_client(monkeypatch, response(mock_extraction().model_dump_json(by_alias=True)))
    run(prepared=PreparedCv(kind="images", page_count=1,
        images=[PageImage(base64.b64encode(b"jpeg").decode())]))
    assert client.converse.call_args.kwargs["messages"][0]["content"] == [
        {"image": {"format": "jpeg", "source": {"bytes": b"jpeg"}}}, {"text": USER_INSTRUCTIONS}]


@pytest.mark.parametrize("stop", ["max_tokens", "content_filtered", "guardrail_intervened", "tool_use"])
def test_incomplete_output_rejected(monkeypatch, stop):
    client = setup_client(monkeypatch, response(mock_extraction().model_dump_json(), stop))
    with pytest.raises(ResumeProcessingError):
        run()
    client.close.assert_called_once()


def test_timeout_uses_existing_domain_error(monkeypatch):
    setup_client(monkeypatch, TimeoutError("private input"))
    with pytest.raises(ResumeProcessingError) as error:
        run()
    assert error.value.code == "EXTRACTION_TIMEOUT"
    assert "private input" not in str(error.value)
