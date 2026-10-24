# Resume Extraction: Current-State Review

> **Baseline and progress:** Findings below record the initial code review;
> resolved rows and follow-up notes describe changes since that baseline.
> Follow-up work now preserves each skill's `rawName`, scopes cache entries to
> provider/configuration/version identity, shares the Gemini client, and keeps
> proficiency unknown unless inspectable CV text explicitly states a level.
> PDF pages are processed individually, and prompt version 2 treats CV content
> as untrusted data and requests atomic skill names.

> **Current-flow note (2026-10-13):** This review began before catalog matching
> and confirmed-profile database persistence were integrated in the host
> Backend. For the current end-to-end behavior, see
> [resume-pipeline-flow.md](resume-pipeline-flow.md). Findings below that refer
> to the original baseline are historical unless marked resolved/updated.

## Purpose

This document records how resume extraction works today, the gaps found during
the code review, and the risks those gaps create. It describes the implementation
as it exists; it is not a proposal to reuse the market job-posting pipeline.

The review covered `src/resume/`, its CLI scripts and tests, and the backend
adapter in `backend/app/features/resume/`. Related API and database design notes
are in [`docs/cv-extraction/`](../../../docs/cv-extraction/).

## Current flow

```text
Backend upload endpoint
  → temporary local upload store
  → in-process job queue (DB-backed job/result when configured)
  → cache lookup by file hash plus provider/configuration/version identity
  → PDF/image preprocessing
  → one model request for the whole document
  → Pydantic schema validation (one format-repair attempt)
  → deterministic post-processing, selected text grounding, skill aliases
  → API result for the user to review
  → Backend matches technical skills/tools against the shared core catalog
  → user reviews/edits and confirms
  → anonymous confirmed profile saved to app schema when DB is configured,
    otherwise local JSON in development
```

The reusable parsing, provider, schema, and post-processing code lives in
`src/resume/`. The backend owns HTTP routes, uploads, job state, cache, and local
profile persistence. The direct CLI runs the same preprocessing, provider, and
post-processing stages without going through the API.

## Findings

| Priority | Finding | Evidence in the current implementation | Effect |
|---|---|---|---|
| Resolved | Resume skills were not resolved against the database catalog. | The host Backend's `catalog.py` loads `core.skills` and `core.skill_aliases`, then uses the shared deterministic matcher for technical skills/tools on extraction responses and before profile saves. | Matched labels include catalog identity for comparison; unmatched labels remain visible and do not create catalog entries. The reusable resume extractor itself remains DB-free. |
| Resolved | The in-code skill normalizer could lose the original spelling. | `build_result()` now preserves `rawName` and only applies Unicode/whitespace cleanup to the display name. | Users and later matching can inspect the model's original wording; catalog matching remains outside resume extraction. |
| Improved | Extraction quality has not been measured across the full declared sample set with the current Gemini flow. | The evaluator reads the ten fictional CVs and their expected facts from `backend/test_cvs/manifest.json`, and reports expected-fact recall, model/version, warnings, review count, latency, and token usage. A Gemini run has completed for at least one sample; full-set and per-case review are still needed. | The sample run confirms the evaluation path works, but one case is not a quality baseline. Expected-fact recall does not measure precision; review outputs for unsupported claims and duplicates. |
| High | The whole resume is sent in one model request. | The Gemini adapter receives one `PreparedCv`; the prompt requests the full profile in one response. The output cap is 8,192 tokens and there is no page/section chunking or merge stage. A cut-off response is rejected instead of being saved as complete. | Long CVs can exceed context/output budgets or fail at the output cap. There is no chunk-and-merge recovery path yet. |
| Improved | Scanned and mixed-content PDFs can be only partially analyzed. | PDF pages are now classified individually. Text pages remain text, scanned/unreadable pages are rendered as images, and Gemini receives included pages in document order. If the image-page limit is exceeded, the warning lists omitted page numbers and `meta.isPartial` is true. Metadata identifies mixed inputs as `inputKind=mixed`. | Mixed PDFs no longer lose scanned pages merely because other pages contain readable text. Results can still be partial when scanned pages exceed the configured cap; the omitted pages are identified in structured metadata and the warning. |
| Improved | Evidence and grounding depend on the input mode. | Text inputs use deterministic text grounding. For image-only and mixed inputs, claims cannot be grounded against text, so extracted profile items are capped at medium confidence, marked for review, and accompanied by a warning. Experience/project evidence is retained, but page-level quotes are not yet part of the result schema. | Image claims are no longer presented as high-confidence verified facts solely because the model assigned high confidence. Reviewers still lack page-specific evidence references. |
| Resolved | Skill proficiency was inferred from exposure duration. | The initial implementation estimated levels from months in jobs/projects and raised a certified skill to at least intermediate. Post-processing now accepts only a level explicitly stated next to the skill in inspectable CV text. Image-only input without inspectable source text remains `unknown`. | Time in a job, project, or a certificate no longer becomes a proficiency claim. Experience/project links remain as evidence of where a skill was used. |
| Resolved | The cache key ignored extractor and processing versions. | The backend cache key now includes file hash, provider configuration, limits, prompt, schema, and processing versions. | Configuration changes produce a different cache entry instead of returning a stale result. |
| Resolved | Resume model configuration previously used generic `EXTRACTOR` and `LLM_*` settings and had no Gemini adapter. | Resume now uses `RESUME_EXTRACTOR=gemini`, the shared `GEMINI_API_KEY`, and the same pinned Gemini model as market; `mock` remains available for tests and local development. | The legacy Ollama and OpenAI-compatible adapters and their package dependency were removed. |
| Improved | Semantic validation is weaker than schema validation. | Pydantic enforces types/enums and rejects unknown output keys. Post-processing validates selected dates, email and URLs; it now lowers confidence when an item is marked current but also has an end date. Other cross-field checks remain limited. | That date contradiction is surfaced for review instead of silently disappearing; duplicated facts, unsupported detail, and incomplete CV classification still need stronger validation. |
| Medium | Text grounding is partial and heuristic. | `make_grounder()` checks selected key fields and uses token overlap for longer strings. Skills use aliases; most descriptions/highlights are not grounded field by field. | Some hallucinations may be missed; loose matching can also accept a value based on partial overlap. Image results have no equivalent check. |
| Resolved | The prompt did not explicitly require atomic skill entries or hostile-document handling. | The current resume prompt treats CV text/images as untrusted source content, directs the model to ignore embedded instructions, and requires separate atomic skill/tool/technology items. It also tells the model not to infer content from omitted pages. | This reduces prompt-injection risk and composite skill names. It does not replace output evaluation or deterministic validation. |
| Medium | Progress stages are simulated while a single model call runs. | The backend advances `skills`, `education`, and `experience` by timer rather than receiving model stage events. | The UI can imply that sections are actually complete when the model is still processing the whole document. |
| Resolved for profile and extraction persistence | The original persistence path was local-only for confirmed profiles and in-memory for extraction jobs. | With DB settings and migration `022_persist_resume_extraction_jobs.sql`, `DatabaseJobsRepo` stores anonymous job status, model/version metadata, and structured extraction JSON. The uploaded CV is deleted after the attempt. `DatabaseProfilesRepo` separately saves the confirmed profile; without DB settings, development uses an in-memory job store and local JSON profile file. | Extraction status/results survive Backend restarts, while the source CV remains temporary. A distributed queue, object storage for CVs, and authenticated accounts remain separate platform concerns. |
| Low | Supported file and layout behavior is implicit in code and scattered notes. | The parser supports PDF, JPEG, PNG, and WEBP. DOC/DOCX is not supported. Page limits and image behavior are configured through settings. | Callers can expect unsupported formats or assume all pages are analyzed unless the contract is stated in one place. |

## Conclusions

1. Resume extraction is already a separate domain package and uses its own
   prompt/schema while sharing the Gemini client factory and pinned model with
   market extraction.
2. The extraction package preserves observed skill wording. The host Backend
   separately resolves technical skills/tools against the shared database
   catalog; this is read-only and does not auto-create catalog rows.
3. The remaining largest risks are quality evidence, long/mixed-document
   handling, and model accuracy. Merely changing the model or prompt will not
   address these risks without a reviewed evaluation result and acceptance
   criteria. The Gemini evaluator is available at
   `scripts/resume/evaluate_samples.py`; running it requires an explicit
   `--run-model` flag and uses Gemini quota.
4. The extractor remains database-independent; the host Backend owns catalog
   access and confirmed-profile persistence. See the current
   [end-to-end flow](resume-pipeline-flow.md).

## Not changed by this review

The initial review itself changed no runtime code. Later implementation notes
and resolved findings are recorded above; database mapping remains outside the
resume extraction package and is performed by Backend adapters.
