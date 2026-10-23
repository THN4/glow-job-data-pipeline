"""Bedrock transport failures are bounded and never expose provider payloads."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError, ReadTimeoutError

from src.shared.llm import bedrock_client as bedrock


@pytest.mark.parametrize("error", [
    ClientError({"Error": {"Code": "AccessDeniedException", "Message": "private response"}}, "Converse"),
    NoCredentialsError(), PermissionError("private path"),
])
def test_provider_failures_are_safe(error):
    client = Mock()
    client.converse.side_effect = error
    with pytest.raises(bedrock.BedrockRequestError) as failure:
        bedrock.converse_text(client, model_id="test", content=[{"text": "private CV"}])
    assert "private" not in str(failure.value)


def test_read_timeout():
    client = Mock()
    client.converse.side_effect = ReadTimeoutError(endpoint_url="private")
    with pytest.raises(bedrock.BedrockRequestError) as failure:
        bedrock.converse_text(client, model_id="test", content=[{"text": "data"}])
    assert failure.value.timeout


def test_empty_text_rejected():
    client = Mock()
    client.converse.return_value = {"stopReason": "end_turn", "output": {"message": {"content": []}}}
    with pytest.raises(bedrock.BedrockRequestError, match="no text"):
        bedrock.converse_text(client, model_id="test", content=[{"text": "data"}])


def test_rag_model_and_unchanged_prompt(monkeypatch):
    monkeypatch.setattr(bedrock, "BedrockTextSettings", lambda: Mock(
        AWS_DEFAULT_REGION="us-east-1", AWS_REGION=None, BEDROCK_RAG_MODEL="amazon.nova-pro-v1:0"))
    client = Mock()
    client.converse.return_value = {"stopReason": "end_turn", "output": {"message": {"content": [{"text": "{}"}]}}}
    factory = Mock(return_value=client)
    monkeypatch.setattr(bedrock, "create_bedrock_client", factory)
    assert bedrock.bedrock_generate("Original evidence prompt") == "{}"
    factory.assert_called_once_with(region="us-east-1")
    request = client.converse.call_args.kwargs
    assert request["modelId"] == "amazon.nova-pro-v1:0"
    assert request["messages"][0]["content"] == [{"text": "Original evidence prompt"}]
    client.close.assert_called_once()


def test_client_has_bounded_retries_and_timeout(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(bedrock.boto3, "client", factory)
    bedrock.create_bedrock_client(region="us-east-1", timeout_ms=120000)
    cfg = factory.call_args.kwargs["config"]
    assert cfg.retries == {"total_max_attempts": 3, "mode": "adaptive"}
    assert cfg.read_timeout == 120
