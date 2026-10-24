# Data Structures Across the Market Pipeline

This document describes how a JSearch posting changes from the provider response to PostgreSQL. Each stage keeps the job data separate from provenance about where and when the pipeline found it.

## End-to-end flow

```text
JSearch response
      ↓
raw JSON file per query
      ↓
load or replay saved query results
      ↓
validate each posting and retain rejection reasons
      ↓
clean posting fields and parse publication-date quality
      ↓
deduplicate by provider ID or normalized publisher-aware URL
      ↓
normalize company names and collect review candidates
      ↓
map job titles to configured career profiles
      ↓
optionally extract skills and save per-job checkpoints
      ↓
load postings and matched skills to PostgreSQL
      ↓
aggregate career skill demand
```

The examples omit unrelated fields. JSearch returns additional response and posting fields.

## 1. JSearch API response

`extract_single_query()` returns the provider JSON response without converting it to a database-shaped record first. Current responses commonly contain `data.jobs` and may include a pagination `cursor`:

```json
{
  "status": "OK",
  "parameters": {"query": "Data Engineer", "country": "th"},
  "data": {
    "jobs": [
      {
        "job_id": "provider-job-123",
        "job_title": "Senior Data Engineer",
        "employer_name": "Example Co., Ltd.",
        "job_country": "",
        "job_location": "Thailand · via LinkedIn",
        "job_posted_at": "10 days ago",
        "job_description": "...",
        "job_publisher": "LinkedIn",
        "job_apply_link": "https://example.com/jobs/123",
        "apply_options": [
          {"publisher": "LinkedIn", "apply_link": "https://example.com/jobs/123", "is_direct": false}
        ]
      }
    ],
    "cursor": "..."
  }
}
```

The response retains response-level fields such as `status`, `parameters`, and `cursor`. The validator supports both the current `response.data.jobs` shape and a legacy shape where `response.data` is itself a list.

## 2. Query metadata and raw storage

`extract_jobs()` wraps each API response with metadata about the query:

```python
{
    "run_id": "20260927T172453146903Z",
    "query_number": 1,
    "collected_at": "2026-09-27T17:24:53+00:00",
    "career_slug": "data_engineer",
    "career_name": "Data Engineer",
    "query": "Data Engineer",
    "response": {...}
}
```

- `run_id` identifies a pipeline run.
- `query_number` identifies the query order and helps check raw-run completeness.
- `collected_at` records when the response was collected and provides a reference time for relative posting dates.
- `career_slug`, `career_name`, and `query` describe the search context.
- `response` preserves the complete provider payload for replay and inspection.

Raw files are grouped by date and run, for example:

```text
data/raw/2026/09/27/<run_id>/001_data_engineer.json
```

One file stores one query result. `load_raw_result()` reads the run's files in `query_number` order and returns a list of query-result records while preserving metadata and the original response. Replay therefore avoids another API request and does not overwrite raw data during validation or cleaning.

## 3. Validation: separate usable and rejected postings

The validator opens `response.data.jobs` (or the legacy list shape) and validates each posting individually. A valid item has a `job` object and its query `metadata`:

```python
{
    "job": {
        "job_id": "provider-job-123",
        "job_title": "Senior Data Engineer",
        "employer_name": "Example Co., Ltd.",
        "job_location": "Thailand · via LinkedIn",
        "job_posted_at": "10 days ago",
        "job_description": "...",
        "apply_options": [...]
    },
    "metadata": {
        "run_id": "...",
        "query_number": 1,
        "collected_at": "...",
        "career_slug": "data_engineer",
        "career_name": "Data Engineer",
        "query": "Data Engineer"
    }
}
```

The validator checks the title, description and its minimum length, country, and a stable job identifier. Invalid records are returned separately with an `errors` list. A posting with no usable publication date is retained; a supplied but invalid date or a date older than the configured window is rejected. Rejection does not delete the raw response.

If `job_country` is missing, a country code may be inferred from an explicit country name or code in `job_location`. A city name alone is not enough to infer a country.

## 4. Cleaning: copy and normalize fields for downstream use

`clean_jobs()` copies each entry and its `job` object, then cleans configured text and URL fields. It removes HTML markup from text, trims whitespace and URLs, normalizes supported country values, and parses publication dates.

Cleaned jobs keep the provider's original `job_posted_at` value and add:

- `posted_at`: a Python UTC `datetime`, or `None` if no usable date exists.
- `posted_at_is_estimated`: whether the date was derived from relative text.
- `posted_at_status`: `exact`, `estimated`, or `unknown`.

If cleaning leaves the title empty or the description below the configured minimum length, the record is returned in `cleaning_rejections` and is not sent to later stages.

## 5. Deduplication: collapse repeated postings and retain query provenance

`deduplicate_jobs()` prefers the provider `job_id`; normalized posting/application URLs provide fallback identity keys and are publisher-aware. Similar job titles alone do not make two records duplicates.

When records match, the first record remains the primary job. The pipeline retains its original metadata, combines query provenance into `matches`, and merges distinct `apply_options`. Duplicate inputs are also returned with `duplicate_of` and `dedupe_reason`; the orchestrator uses their count for logging.

```python
{
    "job": {...},
    "metadata": {"query_number": 1, "query": "Data Engineer", ...},
    "matches": [
        {"query_number": 1, "query": "Data Engineer", ...},
        {"query_number": 2, "query": "Junior Data Engineer", ...}
    ]
}
```

`matches` contains one metadata record per search context where the posting was found. It is not a copy of the entire posting and does not represent publisher links.

## 6. Company normalization: add comparison results without overwriting the source name

The source `employer_name` is preserved. The pipeline adds a `company_normalization` object to the job:

```python
{
    "job": {
        "employer_name": "Siam Commercial Ban",
        "company_normalization": {
            "normalized_name": "siam commercial ban",
            "canonical_name": None,
            "match_method": "candidate_review",
            "candidates": [
                {
                    "canonical_name": "Siam Commercial Bank",
                    "matched_alias": "siam commercial bank",
                    "score": 95.0,
                    "candidate_source": "configured_alias"
                }
            ]
        }
    },
    "metadata": {...},
    "matches": [...]
}
```

- `normalized_name` is the comparison key after formatting cleanup.
- `canonical_name` is populated only for a confirmed canonical name or alias; otherwise it is `None`.
- `match_method` indicates a result such as `confirmed_alias`, `candidate_review`, `unmatched`, or `missing`.
- `candidates` are suggestions, not confirmed company matches.
- `candidate_source` identifies where a suggestion came from, such as configured aliases or another name in the current batch.

RapidFuzz finds candidates from the configured registry or current batch. It does not add aliases or merge companies automatically. Confirmed aliases are maintained in `config/company_aliases.yaml`. Per-run candidate reports are written to `data/processed/company_match_candidates/<run_id>.csv`, with one row per job-candidate pair. The report includes the source name, publisher, URL, score, and query number; when there are no candidates, it contains only the header.

## 7. Career mapping: add a canonical title and career profile

Career mapping is implemented. It preserves `job_title` and adds normalized title and mapping fields:

```python
{
    "job_title": "Senior Data Engineer",
    "normalized_job_title": "Data Engineer",
    "career_slug": "data_engineer",
    "career_name": "Data Engineer",
    "career_profile_slug": "data_engineer_general",
    "career_mapping_status": "mapped",
    "career_mapping_method": "title_alias",
    "career_candidates": []
}
```

Canonical career names, slugs, and title aliases come from `config/careers.yaml`. Search `queries` are used to query the provider; they are separate from title-mapping aliases.

The mapper first uses the job title. If the title maps to one career, it selects that career. If the title is generic or unmatched, a unique career in the query provenance can provide a fallback. Conflicting evidence results in `ambiguous`; no usable evidence results in `unmapped`. The posting is retained in either case.

`career_profile_id` is generated by PostgreSQL. Before database loading, the pipeline uses the stable profile slug and resolves it to an ID during persistence.

## 8. Database loading: convert dictionaries into relational columns

The database does not store the whole Python dictionary in `market.job_postings`. `JobPostingRepository` writes individual values to columns such as:

```text
job_title               → market.job_postings.job_title
normalized_job_title    → market.job_postings.normalized_job_title
career_profile_id       → market.job_postings.career_profile_id
company_id              → market.job_postings.company_id
provider_job_id         → market.job_postings.provider_job_id
publisher               → market.job_postings.publisher
source_url              → market.job_postings.source_url
posted_at               → market.job_postings.posted_at
```

PostgreSQL generates the internal `job_id`; `provider_job_id` is supplied by JSearch. They identify the posting in different systems.

Search provenance is stored separately in `market.job_search_matches` by `record_search_match()`, linking the job, ingestion run, career profile, and search query.

The current schema and repository do not store `apply_options` in a separate table. The raw JSON remains the source for the complete provider response and its application links until a dedicated loading design is added.

## Summary

| Stage | Main shape | What changes | Why |
|---|---|---|---|
| Extraction | Full provider response | Add run and query metadata around the response | Enable traceability and replay. |
| Raw storage | One JSON file per query | No cleaning or field removal | Preserve the original response. |
| Validation | `job` plus `metadata`; split valid/invalid | Create one record per posting and attach errors to rejected records | Keep unusable data out of later transforms. |
| Cleaning | Copied, normalized `job` plus metadata | Add parsed date and date-quality fields | Provide consistent downstream values. |
| Deduplication | One posting per identity with `matches` | Merge query provenance and distinct application links | Avoid counting repeated search results as separate postings. |
| Company normalization | Job plus `company_normalization` | Add a comparison key and review candidates | Standardize company names without losing the source value. |
| Career mapping | Job plus title and query provenance | Add normalized title, career/profile slugs, and mapping status | Group postings for analysis while preserving the source title. |
| Database loading | Relational columns and foreign keys | Convert dictionary fields into repository arguments and columns | Enable relational queries and joins. |

In short, `job` describes the posting, `metadata` and `matches` explain where it was found, and `company_normalization` adds comparison results without replacing the provider's name.
