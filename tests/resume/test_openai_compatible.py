"""Contract tests for the Qwen client against a fake OpenAI-compatible server (httpx MockTransport)."""

import json

import httpx
import pytest

from src.resume.errors import ResumeProcessingError
from src.resume.extraction.contracts import PageImage, PreparedCv
from src.resume.extraction.providers.mock import MOCK_EXTRACTION_DATA
from src.resume.extraction.providers.openai_compatible import OpenAiCompatibleExtractor, parse_json_loose

TEXT = PreparedCv(kind="text", page_count=1, text="Alex Example CV")


def reply(content: str, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "qwen-test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        },
    )


def make(handler, vision=True) -> tuple[OpenAiCompatibleExtractor, list[dict]]:
    requests: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(len(requests), request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    ex = OpenAiCompatibleExtractor(
        base_url="http://fake/v1", model="qwen-test", api_key="x", timeout_ms=5000, vision=vision, http_client=client
    )
    return ex, requests


VALID = json.dumps(MOCK_EXTRACTION_DATA)


async def test_sends_structured_output_and_parses_the_reply():
    ex, reqs = make(lambda n, r: reply(VALID))
    out = await ex.extract(TEXT)
    assert out.extraction.personal.full_name == "Alex Example"
    assert (out.usage.input_tokens, out.usage.output_tokens) == (10, 20)
    body = reqs[0]
    assert body["temperature"] == 0 and body["max_tokens"] == 4096
    assert body["response_format"]["type"] == "json_schema"
    assert "technicalSkills" in body["response_format"]["json_schema"]["schema"]["properties"]
    assert "<cv>" in body["messages"][1]["content"][0]["text"]


async def test_repairs_once_when_output_does_not_match_the_schema():
    ex, reqs = make(lambda n, r: reply('{"oops": true}') if n == 1 else reply(VALID))
    out = await ex.extract(TEXT)
    assert out.extraction.is_document_a_cv
    assert len(reqs) == 2
    assert "did not match" in reqs[1]["messages"][-1]["content"]


async def test_fails_after_a_second_invalid_answer():
    ex, _ = make(lambda n, r: reply("nope"))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_FAILED"


async def test_fails_when_output_was_cut_off():
    ex, _ = make(lambda n, r: reply('{"isDocumentACv": tr', "length"))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_FAILED"


async def test_missing_model_maps_to_model_unavailable():
    ex, _ = make(lambda n, r: httpx.Response(404, json={"error": {"message": "model not found"}}))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "MODEL_UNAVAILABLE"


async def test_connection_refused_maps_to_model_unavailable():
    def refuse(n, r):
        raise httpx.ConnectError("refused")

    ex, _ = make(refuse)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "MODEL_UNAVAILABLE"


async def test_timeout_maps_to_extraction_timeout():
    def slow(n, r):
        raise httpx.ReadTimeout("slow")

    ex, _ = make(slow)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_TIMEOUT"


async def test_images_are_rejected_when_the_model_has_no_vision():
    ex, reqs = make(lambda n, r: reply(VALID), vision=False)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(PreparedCv(kind="images", page_count=1, images=[PageImage(b64="AA==")]))
    assert e.value.code == "UNREADABLE_DOCUMENT" and reqs == []


async def test_images_are_sent_as_data_urls():
    ex, reqs = make(lambda n, r: reply(VALID))
    await ex.extract(PreparedCv(kind="images", page_count=1, images=[PageImage(b64="AAAA")]))
    assert reqs[0]["messages"][1]["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"


def test_parse_json_loose():
    assert parse_json_loose('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_json_loose("nope") is None
