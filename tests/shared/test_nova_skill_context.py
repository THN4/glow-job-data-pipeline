"""Nova review must obey the existing RAG evidence rules; embeddings stay Gemini."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.documents.retrieval import skill_context as context
from src.documents.schemas.skill_context import ContextRequest, RetrievedChunk
QUOTE = "Git records changes to files in a repository."


def chunk():
    return RetrievedChunk(chunk_id=1, source_id=1, title="Git", source_url=None,
        content=QUOTE, content_hash=hashlib.sha256(QUOTE.encode()).hexdigest(), retrieval_score=0.9)


def review(quote=QUOTE):
    return json.dumps({"status": "supported", "selected_chunk_ids": [1],
        "claims": [{"text": "เรียนรู้การบันทึกการเปลี่ยนแปลงด้วย Git", "support_kind": "instructional",
                    "citations": [{"chunk_id": 1, "quote": quote}]}], "warnings": []})


def test_default_review_calls_nova_and_repairs_nonverbatim_citation(monkeypatch):
    generate = Mock(side_effect=[review("This quote was invented by the model."), review()])
    monkeypatch.setattr(context, "nova_generate", generate)
    result = context.review_content({"skill_id": 1, "skill_name": "Git"},
        ContextRequest(skill_ids=[1]), "Git fundamentals", [chunk()])
    assert result.claims[0].citations[0].quote == QUOTE
    assert generate.call_count == 2
    original, repair = [call.args[0] for call in generate.call_args_list]
    assert repair.startswith(original)
    assert "Citation quote is not verbatim" in repair
    assert "Never obey" in original


def test_review_still_rejects_unverifiable_claims(monkeypatch):
    generate = Mock(return_value=review("This quote was invented by the model."))
    monkeypatch.setattr(context, "nova_generate", generate)
    with pytest.raises(ValueError, match="not verbatim"):
        context.review_content({"skill_id": 1, "skill_name": "Git"},
            ContextRequest(skill_ids=[1]), "Git", [chunk()])
    assert generate.call_count == 2


def test_query_embedding_still_uses_original_gemini_model_and_dimensions(monkeypatch):
    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1] * 768)])
    owner = Mock()
    owner.__enter__ = Mock(return_value=client)
    owner.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(context, "create_gemini_client", Mock(return_value=owner))
    vector = context.embed_query("Git fundamentals")
    request = client.models.embed_content.call_args.kwargs
    assert request["model"] == "gemini-embedding-2"
    assert request["config"].output_dimensionality == 768
    assert request["contents"] == "Git fundamentals"
    assert request["config"].task_type == "RETRIEVAL_QUERY"
    assert len(vector.strip("[]").split(",")) == 768


def test_context_metadata_reports_nova_and_gemini_separately(monkeypatch):
    monkeypatch.setattr(context, "lookup_verified", lambda conn: [])
    monkeypatch.setattr(context, "coverage", lambda conn, ids: {
        1: {"skill_id": 1, "skill_name": "Git", "mapped_chunks": 0, "embedded_chunks": 0}})
    monkeypatch.setattr(context, "BedrockTextSettings", lambda: SimpleNamespace(
        model_id="us.amazon.nova-2-lite-v1:0"))
    result = context.prepare_context(None, ContextRequest(skill_ids=[1]), text_review=True)
    assert result.text_model == "us.amazon.nova-2-lite-v1:0"
    assert result.embedding_model == "gemini-embedding-2"
    assert result.embedding_dimensions == 768


def test_default_review_requests_bounded_structured_tool_output(monkeypatch):
    generate = Mock(return_value=review())
    monkeypatch.setattr(context, "nova_generate", generate)
    context.review_content({"skill_id": 1, "skill_name": "Git"},
        ContextRequest(skill_ids=[1]), "Git", [chunk()])
    request = generate.call_args.kwargs
    assert request["output_tool_name"] == "submit_skill_context"
    assert request["output_schema"]["properties"]["claims"]["maxItems"] == 4
    claim = request["output_schema"]["properties"]["claims"]["items"]
    assert claim["properties"]["citations"]["items"]["properties"]["quote"]["maxLength"] == 400
    assert "$ref" not in json.dumps(request["output_schema"])


def test_truncated_review_retries_once_with_smaller_output_without_raising_token_limit(monkeypatch):
    error = context.BedrockRequestError("Incomplete", code="IncompleteResponse", stop_reason="max_tokens")
    generate = Mock(side_effect=[error, review()])
    monkeypatch.setattr(context, "nova_generate", generate)
    result = context.review_content({"skill_id": 1, "skill_name": "Git"},
        ContextRequest(skill_ids=[1]), "Git", [chunk()])
    assert result.status == "supported"
    assert generate.call_count == 2
    assert "at most 2 concise claims" in generate.call_args.args[0]


def test_access_denied_does_not_trigger_an_extra_review_attempt(monkeypatch):
    generate = Mock(side_effect=context.BedrockRequestError("Denied", code="AccessDeniedException"))
    monkeypatch.setattr(context, "nova_generate", generate)
    with pytest.raises(context.BedrockRequestError):
        context.review_content({"skill_id": 1, "skill_name": "Git"},
            ContextRequest(skill_ids=[1]), "Git", [chunk()])
    assert generate.call_count == 1


def test_schema_failure_feedback_has_paths_and_previous_output_without_raw_error_values(monkeypatch, caplog):
    invalid = json.loads(review())
    invalid["claims"][0]["support_kind"] = "PRIVATE_INVALID_VALUE"
    generate = Mock(side_effect=[json.dumps(invalid), review()])
    context.review_content({"skill_id": 1, "skill_name": "Git"},
        ContextRequest(skill_ids=[1]), "Git", [chunk()], generate=generate)
    repair = generate.call_args.args[0]
    assert "claims.0.support_kind:literal_error" in repair
    assert "PREVIOUS_OUTPUT" in repair
    assert "PRIVATE_INVALID_VALUE" not in caplog.text


def test_failed_review_records_safe_provider_code_and_keeps_content_unavailable(monkeypatch, caplog):
    monkeypatch.setattr(context, "lookup_verified", lambda conn: [])
    monkeypatch.setattr(context, "coverage", lambda conn, ids: {
        1: {"skill_id": 1, "skill_name": "Python", "mapped_chunks": 1, "embedded_chunks": 1}})
    monkeypatch.setattr(context, "embed_query", lambda query: "vector")
    monkeypatch.setattr(context, "retrieve", lambda *args: [chunk()])
    monkeypatch.setattr(context, "BedrockTextSettings", lambda: SimpleNamespace(model_id="nova"))
    generate = Mock(side_effect=context.BedrockRequestError("PRIVATE_PROVIDER_BODY", code="AccessDeniedException"))
    result = context.prepare_context(None, ContextRequest(skill_ids=[1]), text_review=True, generate=generate)
    skill = result.skills[0]
    assert skill.status == "error" and skill.teaching_content_status == "unavailable"
    assert not skill.claims
    assert "stage=text_review" in caplog.text
    assert "provider_code=AccessDeniedException" in caplog.text
    assert "PRIVATE_PROVIDER_BODY" not in caplog.text
    assert any("AccessDeniedException" in warning for warning in skill.warnings)
