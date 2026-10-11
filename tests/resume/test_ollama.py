"""Contract tests for the native Ollama client (httpx.MockTransport fakes the server)."""

import json

import httpx
import pytest

from src.resume.errors import ResumeProcessingError
from src.resume.extraction.contracts import PageImage, PreparedCv
from src.resume.extraction.providers.mock import MOCK_EXTRACTION_DATA
from src.resume.extraction.providers.ollama import OllamaExtractor

TEXT = PreparedCv(kind="text", page_count=1, text="Alex Example CV")
VALID = json.dumps(MOCK_EXTRACTION_DATA)


def reply(content: str, done_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={"message": {"role": "assistant", "content": content}, "done_reason": done_reason, "prompt_eval_count": 11, "eval_count": 22},
    )


def make(handler, vision=True, base_url="http://fake:11434", **kw) -> tuple[OllamaExtractor, list[dict]]:
    requests: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append({"url": str(request.url), **json.loads(request.content)})
        return handler(len(requests), request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return OllamaExtractor(base_url=base_url, model="qwen-test", vision=vision, http_client=client, **kw), requests


async def test_sends_context_size_thinking_flag_and_schema():
    ex, reqs = make(lambda n, r: reply(VALID), num_ctx=8192, think=False)
    out = await ex.extract(TEXT)
    assert out.extraction.personal.full_name == "Alex Example"
    assert (out.usage.input_tokens, out.usage.output_tokens) == (11, 22)
    body = reqs[0]
    assert body["url"] == "http://fake:11434/api/chat"
    assert body["think"] is False and body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 4096}
    assert "technicalSkills" in body["format"]["properties"]
    assert "<cv>" in body["messages"][1]["content"]


async def test_accepts_a_base_url_ending_in_v1():
    ex, reqs = make(lambda n, r: reply(VALID), base_url="http://fake:11434/v1/")
    await ex.extract(TEXT)
    assert reqs[0]["url"] == "http://fake:11434/api/chat"


async def test_images_go_in_the_images_field():
    ex, reqs = make(lambda n, r: reply(VALID))
    await ex.extract(PreparedCv(kind="images", page_count=1, images=[PageImage(b64="AAAA")]))
    assert reqs[0]["messages"][1]["images"] == ["AAAA"]


async def test_images_are_rejected_when_the_model_has_no_vision():
    ex, reqs = make(lambda n, r: reply(VALID), vision=False)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(PreparedCv(kind="images", page_count=1, images=[PageImage(b64="AA==")]))
    assert e.value.code == "UNREADABLE_DOCUMENT" and reqs == []


async def test_repairs_once_then_gives_up():
    ex, reqs = make(lambda n, r: reply('{"oops": true}') if n == 1 else reply(VALID))
    assert (await ex.extract(TEXT)).extraction.is_document_a_cv and len(reqs) == 2
    ex, _ = make(lambda n, r: reply("nope"))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_FAILED"


async def test_cut_off_output_fails():
    ex, _ = make(lambda n, r: reply('{"isDocumentACv": tr', "length"))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_FAILED"


async def test_missing_model_connection_refused_and_timeout():
    ex, _ = make(lambda n, r: httpx.Response(404, json={"error": "model 'x' not found"}))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "MODEL_UNAVAILABLE"

    def refuse(n, r):
        raise httpx.ConnectError("refused")

    ex, _ = make(refuse)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "MODEL_UNAVAILABLE"

    def slow(n, r):
        raise httpx.ReadTimeout("slow")

    ex, _ = make(slow)
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_TIMEOUT"


async def test_server_error_is_failure():
    ex, _ = make(lambda n, r: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(ResumeProcessingError) as e:
        await ex.extract(TEXT)
    assert e.value.code == "EXTRACTION_FAILED"
