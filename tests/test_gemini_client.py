"""Check the Gemini API boundary without making network requests."""

from unittest.mock import MagicMock, Mock

import pytest
from google.genai import errors

from src.skills import gemini_client


def test_gemini_generate_sends_prompt_and_returns_response(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.__enter__.return_value.models.generate_content.return_value.text = (
        '{"skills": []}'
    )
    client_constructor = Mock(return_value=fake_client)
    monkeypatch.setattr(gemini_client.genai, "Client", client_constructor)

    result = gemini_client.gemini_generate("Extract skills from this job")

    assert result == '{"skills": []}'
    client_constructor.assert_called_once_with(api_key="test-key")
    fake_client.__enter__.return_value.models.generate_content.assert_called_once_with(
        model="gemini-3.5-flash-lite",
        contents="Extract skills from this job",
        config={"response_mime_type": "application/json"},
    )


def test_gemini_generate_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini_client, "load_dotenv", lambda _path: None)

    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        gemini_client.gemini_generate("Extract skills")


def test_gemini_generate_rejects_empty_response(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.__enter__.return_value.models.generate_content.return_value.text = None
    monkeypatch.setattr(gemini_client.genai, "Client", Mock(return_value=fake_client))

    with pytest.raises(ValueError, match="Gemini returned no text"):
        gemini_client.gemini_generate("Extract skills")


def test_gemini_generate_hides_provider_error_details(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.__enter__.return_value.models.generate_content.side_effect = RuntimeError(
        "sensitive request details"
    )
    monkeypatch.setattr(gemini_client.genai, "Client", Mock(return_value=fake_client))

    with pytest.raises(RuntimeError, match=r"Gemini request failed \(RuntimeError\)") as error:
        gemini_client.gemini_generate("Extract skills")

    assert "sensitive request details" not in str(error.value)


def test_gemini_generate_identifies_rate_limit_without_exposing_provider_details(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.__enter__.return_value.models.generate_content.side_effect = (
        errors.ClientError(429, {"error": {"message": "sensitive quota details"}})
    )
    monkeypatch.setattr(gemini_client.genai, "Client", Mock(return_value=fake_client))

    with pytest.raises(gemini_client.GeminiRateLimitError, match="HTTP 429") as error:
        gemini_client.gemini_generate("Extract skills")

    assert "sensitive quota details" not in str(error.value)
