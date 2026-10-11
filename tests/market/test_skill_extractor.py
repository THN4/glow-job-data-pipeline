import json

import pytest

from src.market.skill_extraction.extractor import extract_job_skills, extract_skills_for_jobs
from src.shared.llm.gemini_client import GeminiRateLimitError


def test_extract_job_skills_parses_response_and_builds_context_prompt(monkeypatch) -> None:
    job_title = "Data Engineer"
    job_description = "Strong Python skills are required."
    llm_response = json.dumps(
        {
            "skills": [
                {
                    "raw_skill_name": "Python",
                    "requirement_type": "required",
                    "proficiency_level": "advanced",
                    "evidence_text": job_description,
                }
            ]
        }
    )
    prompts: list[str] = []

    def fake_llm_generate(prompt: str) -> str:
        prompts.append(prompt)
        return llm_response

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", fake_llm_generate)
    skills = extract_job_skills(
        job_title,
        job_description,
    )

    assert skills == [
        {
            "raw_skill_name": "Python",
            "requirement_type": "required",
            "proficiency_level": "advanced",
            "evidence_text": job_description,
        }
    ]
    assert len(prompts) == 1
    assert job_title in prompts[0]
    assert job_description in prompts[0]
    assert "candidate_hints" not in prompts[0]


def test_extract_job_skills_accepts_no_skills_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.market.skill_extraction.extractor.gemini_generate",
        lambda _prompt: '{"skills": []}',
    )
    skills = extract_job_skills(
        "Data Engineer",
        "We are hiring a data engineer.",
    )

    assert skills == []


def test_extract_job_skills_rejects_empty_job_title_before_calling_llm(monkeypatch) -> None:
    def unexpected_llm_call(_prompt: str) -> str:
        pytest.fail("LLM should not be called for invalid input")

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", unexpected_llm_call)
    with pytest.raises(ValueError, match="job_title must be a non-empty string"):
        extract_job_skills(
            "  ",
            "Python is required.",
        )


@pytest.mark.parametrize("job_description", ["", "   ", None, 123])
def test_extract_job_skills_rejects_invalid_description(
    job_description: object,
    monkeypatch,
) -> None:
    def unexpected_llm_call(_prompt: str) -> str:
        pytest.fail("LLM should not be called for invalid input")

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", unexpected_llm_call)
    with pytest.raises(
        ValueError,
        match="job_description must be a non-empty string",
    ):
        extract_job_skills(
            "Data Engineer",
            job_description,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("response_text", "error_message"),
    [
        ("not json", "LLM response must be valid JSON"),
        ('{"not_skills": []}', "LLM response must contain a skills list"),
        (
            '{"skills": [{"raw_skill_name": "Python"}]}',
            "Skill at index 0 must contain exactly",
        ),
        (
            '{"skills": [{"raw_skill_name": "Python", '
            '"requirement_type": "mandatory", '
            '"proficiency_level": "advanced", '
            '"evidence_text": "Python is required."}]}',
            "invalid requirement_type",
        ),
        (
            '{"skills": [{"raw_skill_name": "Python", '
            '"requirement_type": "required", '
            '"proficiency_level": "guru", '
            '"evidence_text": "Python is required."}]}',
            "invalid proficiency_level",
        ),
        (
            '{"skills": [{"raw_skill_name": "Python", '
            '"requirement_type": "required", '
            '"proficiency_level": "advanced", '
            '"evidence_text": "Python is essential."}]}',
            "evidence_text must be an exact quote",
        ),
    ],
)
def test_extract_job_skills_rejects_invalid_llm_response(
    response_text: str,
    error_message: str,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.market.skill_extraction.extractor.gemini_generate",
        lambda _prompt: response_text,
    )
    with pytest.raises(ValueError, match=error_message):
        extract_job_skills(
            "Data Engineer",
            "Python is required.",
        )


def test_extract_skills_for_jobs_keeps_metadata_and_marks_success(monkeypatch) -> None:
    entries = [
        {
            "job": {
                "job_id": "provider-1",
                "job_title": "Data Engineer",
                "job_description": "Python is required.",
            },
            "metadata": {"run_id": "run-1", "career_slug": "data_engineer"},
            "matches": [{"query": "Data Engineer"}],
        },
        {
            "job": {
                "job_id": "provider-2",
                "job_title": "Backend Engineer",
                "job_description": "Python is required.",
            },
            "metadata": {"run_id": "run-1", "career_slug": "backend_engineer"},
        },
    ]
    response = json.dumps(
        {
            "skills": [
                {
                    "raw_skill_name": "Python",
                    "requirement_type": "required",
                    "proficiency_level": "unknown",
                    "evidence_text": "Python is required.",
                }
            ]
        }
    )
    calls: list[str] = []

    def fake_llm_generate(prompt: str) -> str:
        calls.append(prompt)
        return response

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", fake_llm_generate)
    results = extract_skills_for_jobs(entries)

    assert len(calls) == 2
    assert results[0]["extraction_status"] == "completed"
    assert results[0]["skills"][0]["raw_skill_name"] == "Python"
    assert results[0]["metadata"] == entries[0]["metadata"]
    assert results[0]["matches"] == entries[0]["matches"]
    assert results[1]["extraction_status"] == "completed"
    assert results[1]["metadata"] == entries[1]["metadata"]
    assert "extraction_status" not in entries[0]


def test_extract_skills_for_jobs_keeps_processing_after_one_failure(monkeypatch) -> None:
    entries = [
        {
            "job": {
                "job_id": "provider-1",
                "job_title": "Data Engineer",
                "job_description": "Python is required.",
            }
        },
        {
            "job": {
                "job_id": "provider-2",
                "job_title": "Backend Engineer",
                "job_description": "No skill requirements are listed.",
            }
        },
    ]
    call_count = 0

    def flaky_llm_generate(_prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("provider unavailable")
        return '{"skills": []}'

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", flaky_llm_generate)
    results = extract_skills_for_jobs(entries)

    assert results[0]["extraction_status"] == "failed"
    assert results[0]["skills"] == []
    assert results[0]["extraction_error"] == "provider unavailable"
    assert results[1]["extraction_status"] == "completed"
    assert results[1]["skills"] == []


def test_extract_skills_for_jobs_marks_invalid_entry_failed_without_llm_call(monkeypatch) -> None:
    def unexpected_llm_call(_prompt: str) -> str:
        pytest.fail("LLM should not be called for an entry without a job")

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", unexpected_llm_call)
    results = extract_skills_for_jobs(
        [{"metadata": {"run_id": "run-1"}}],
    )

    assert results[0]["extraction_status"] == "failed"
    assert results[0]["skills"] == []
    assert results[0]["extraction_error"] == (
        "job entry does not contain a job object"
    )


def test_extract_skills_for_jobs_stops_on_rate_limit(monkeypatch) -> None:
    calls = []

    def rate_limited(_prompt: str) -> str:
        calls.append(1)
        raise GeminiRateLimitError("Gemini rate limit reached (HTTP 429)")

    monkeypatch.setattr("src.market.skill_extraction.extractor.gemini_generate", rate_limited)
    jobs = [
        {"job": {"job_title": "Data Engineer", "job_description": "Python required."}}
    ] * 2

    with pytest.raises(GeminiRateLimitError, match="HTTP 429"):
        extract_skills_for_jobs(jobs)

    assert len(calls) == 1
