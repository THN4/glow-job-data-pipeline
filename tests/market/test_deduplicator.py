from src.market.normalization.deduplicator import deduplicate_jobs


def _entry(job: dict[str, object], query_number: int) -> dict[str, object]:
    return {
        "job": job,
        "metadata": {
            "run_id": "run-001",
            "query_number": query_number,
            "query": f"query {query_number}",
        },
    }


def test_deduplicate_jobs_by_provider_id_and_keep_all_query_matches() -> None:
    first = _entry({"job_id": "provider-001", "job_title": "Data Engineer"}, 1)
    second = _entry({"job_id": "provider-001", "job_title": "Data Engineer"}, 2)

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 1
    assert len(duplicates) == 1
    assert duplicates[0]["duplicate_of"] == 0
    assert duplicates[0]["dedupe_reason"] == "provider_job_id"
    assert unique_jobs[0]["metadata"] == first["metadata"]
    assert unique_jobs[0]["matches"] == [first["metadata"], second["metadata"]]


def test_deduplicate_jobs_normalizes_source_urls() -> None:
    first = _entry(
        {"job_apply_link": "https://EXAMPLE.com/jobs/123/?b=2&a=1#apply"}, 1
    )
    second = _entry(
        {"job_url": "https://example.com/jobs/123?a=1&b=2"}, 2
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 1
    assert duplicates[0]["dedupe_reason"] == "source_url"
    assert len(unique_jobs[0]["matches"]) == 2


def test_deduplicate_jobs_merges_apply_options_for_same_provider_job() -> None:
    first = _entry(
        {
            "job_id": "provider-001",
            "apply_options": [
                {
                    "publisher": "Board A",
                    "apply_link": "https://board-a.example/jobs/1",
                    "is_direct": False,
                }
            ],
        },
        1,
    )
    second = _entry(
        {
            "job_id": "provider-001",
            "apply_options": [
                {
                    "publisher": "Board A",
                    "apply_link": "https://BOARD-A.example/jobs/1/#apply",
                    "is_direct": False,
                },
                {
                    "publisher": "Company site",
                    "apply_link": "https://company.example/careers/role-1",
                    "is_direct": True,
                },
            ],
        },
        2,
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 1
    assert len(duplicates) == 1
    assert unique_jobs[0]["job"]["apply_options"] == [
        {
            "publisher": "Board A",
            "apply_link": "https://board-a.example/jobs/1",
            "is_direct": False,
        },
        {
            "publisher": "Company site",
            "apply_link": "https://company.example/careers/role-1",
            "is_direct": True,
        },
    ]


def test_deduplicate_jobs_does_not_merge_same_company_and_title_alone() -> None:
    first = _entry(
        {
            "employer_name": "Example Co",
            "job_title": "Data Engineer",
            "job_location": "Bangkok, Thailand",
        },
        1,
    )
    second = _entry(
        {
            "employer_name": " example   co ",
            "job_title": "DATA ENGINEER",
            "job_location": " bangkok, thailand ",
        },
        2,
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 2
    assert duplicates == []


def test_deduplicate_jobs_does_not_use_incomplete_fallback_identity() -> None:
    first = _entry(
        {"employer_name": "Example Co", "job_title": "Data Engineer"}, 1
    )
    second = _entry(
        {"employer_name": "Example Co", "job_title": "Data Engineer"}, 2
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 2
    assert duplicates == []


def test_deduplicate_jobs_respects_different_provider_ids() -> None:
    common_fields = {
        "employer_name": "Example Co",
        "job_title": "Data Engineer",
        "job_location": "Bangkok, Thailand",
    }
    first = _entry({**common_fields, "job_id": "provider-001"}, 1)
    second = _entry({**common_fields, "job_id": "provider-002"}, 2)

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 2
    assert duplicates == []


def test_deduplicate_jobs_respects_different_provider_ids_even_with_same_url() -> None:
    first = _entry(
        {"job_id": "provider-001", "job_apply_link": "https://example.com/jobs"},
        1,
    )
    second = _entry(
        {"job_id": "provider-002", "job_apply_link": "https://example.com/jobs"},
        2,
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 2
    assert duplicates == []


def test_deduplicate_jobs_keeps_same_url_for_different_publishers() -> None:
    first = _entry(
        {
            "job_apply_link": "https://example.com/apply/role",
            "job_publisher": "Board A",
        },
        1,
    )
    second = _entry(
        {
            "job_apply_link": "https://example.com/apply/role",
            "job_publisher": "Board B",
        },
        2,
    )

    unique_jobs, duplicates = deduplicate_jobs([first, second])

    assert len(unique_jobs) == 2
    assert duplicates == []


def test_deduplicate_jobs_does_not_mutate_input_entries() -> None:
    entry = _entry({"job_id": "provider-001"}, 1)

    deduplicate_jobs([entry])

    assert "matches" not in entry
