# Resume Extraction: Proposed Scope and Specification

> This specification began as a proposal. Several items below have since been
> implemented, including Gemini extraction, deterministic matching against the
> Market catalog in the host Backend, anonymous confirmed-profile persistence
> when database settings are present, and partial-page reporting. For the
> current implementation and ownership boundaries, see
> [resume-pipeline-flow.md](resume-pipeline-flow.md). Items labeled proposed or
> remaining are design context, not a claim that the flow is still unbuilt.

## 1. Goal

Turn an uploaded resume into a faithful, editable candidate profile. The
extractor should preserve what the document says, make uncertainty visible, and
provide enough evidence for a person to correct the result.

This is a resume-specific extraction pipeline. Its input is a candidate's
CV/resume, not a job description. Extraction must not depend on market
ingestion, job-skill extraction, or market prompts. A separate catalog
resolution step compares extracted skills with the same canonical skill
catalog used by Market; that comparison does not change what the CV extractor
reads or claims.

## 2. Domain boundaries

### Resume extraction package (`data-pipeline/src/resume/`)

Owns:

- supported-file validation and document preprocessing;
- resume-specific model settings, prompts, provider adapters, and extraction
  schema;
- deterministic validation and normalization of extracted profile facts;
- source evidence and quality warnings in the extraction result;
- a database-free CLI for inspecting one extraction.
- raw skill labels that can be passed to a catalog resolver after extraction.

Must not:

- read or write `core.skills`, `core.skill_aliases`, or job-posting tables;
- create catalog skills or decide that an extracted string has a database
  `skill_id` inside the extraction package;
- own HTTP authentication, user identity, durable jobs, upload retention, or
  profile persistence.

### Backend (`backend/app/features/resume/`)

Owns API and user/session boundaries, file storage, job execution and durable
state, user review/confirmation, catalog loading/resolution adapters, and
profile persistence. It runs the catalog resolver after extraction so the
Review Profile UI can show the matching canonical skill, then runs it again
when saving a confirmed/edited profile. An unmatched or ambiguous skill stays
visible for user review; it must not be silently dropped or inserted into the
shared catalog by resume ingestion.

### Market (`data-pipeline/src/market/`)

Continues to own job-posting extraction and catalog resolution. Resume work may
reuse a small, pure shared utility only when its behavior is domain-neutral and
does not force market prompt, provider, schema, or database semantics onto
resume processing.

## 3. Target flow

```text
Upload and access checks (backend)
  → verify actual file type, size, page count, and configured limits
  → classify pages as text-readable, scanned/image, or mixed
  → prepare all in-scope pages as text and/or page images, with page references
  → call the resume-configured Gemini provider with its own prompt and schema
  → validate structured output and semantic invariants
  → attach source evidence; flag unsupported or uncertain claims
  → preserve raw skill wording and apply safe, deterministic resume normalization
  → backend resolver compares skills with core.skills + core.skill_aliases
    using the same deterministic matching rules as Market
  → return a versioned candidate profile with match status for user review
  → user edits/confirms (backend); rerun matching for edits and new skills
  → persist matched skill_id or retain an unmatched/needs-review raw skill
```

The extractor returns candidate assertions; it does not claim those assertions
are verified facts or canonical database skills.

## 4. Input and document handling

### Initial supported formats

- PDF, JPEG, PNG, and WEBP.
- DOC and DOCX are out of scope for the first implementation unless the product
  owner explicitly adds them. They must fail with a stable unsupported-type
  error rather than be guessed from their filename.

### Required behavior

- Determine format from file bytes, not only the supplied filename or MIME type.
- Enforce byte, page-count, image-dimension, and decompression limits before
  model calls.
- Detect readable text per page, not only by the average text volume of the
  entire PDF. The current implementation sends text and scanned pages together
  in document order and reports omitted scanned page numbers when the image
  page limit is exceeded.
- Preserve page order and page identity through preprocessing.
- If configured limits require dropping pages, set `meta.isPartial=true` and
  include the omitted page numbers in warnings. Prefer a clear error
  or an explicitly partial result over presenting an incomplete extraction as
  complete.
- Treat CV content as untrusted document data. The model must ignore
  instructions embedded in the CV that attempt to change the extraction task.
- Do not log CV text, images, contact details, or model prompts containing CV
  content.

Page limits, maximum file size, and whether partial extraction is allowed are
deployment/product decisions; they must be explicit configuration and API
contract values rather than hidden parser behavior.

## 5. LLM and provider configuration

Resume can use the same Gemini API/provider as market. The current market code
pins `GEMINI_MODEL` to `gemini-3.5-flash-lite`; use that exact model as the first
resume baseline unless the evaluation shows a reason to choose another model.
This does **not** mean sharing market's extraction prompt, schema, or task
wrapper. Resume shares the market model and credential for now, while retaining
a separate prompt, response schema, preprocessing, and error handling.

### Proposed settings

Use a resume-prefixed namespace (exact names may be finalized during
implementation), for example:

```text
RESUME_EXTRACTOR=mock|gemini
GEMINI_API_KEY=...               # shared with market
RESUME_GEMINI_TIMEOUT_MS=180000
```

The model/provider factory remains resume-owned. The resume Gemini adapter uses
the shared Gemini client factory, API key, and pinned model, while keeping the CV
prompt and schema independent from market. The market's `gemini_generate()`
helper is text-only; resume uses the shared client factory directly so it can
send page images and request its own structured output schema.

Use the same explicit model ID pinned in the shared market Gemini client. Model
availability and extraction quality should be re-evaluated before changing that
shared selection.

The extraction result must record provider, model identifier, prompt version,
schema version, and processing version. Credentials must never be returned or
logged.

## 6. Extraction contract

The model returns structured candidate data for:

- personal/contact details and summary;
- education;
- work experience and internships;
- projects;
- technical skills and tools;
- soft skills and languages;
- certifications, awards, competitions, workshops, and activities.

### Required extraction rules

- Extract only claims supported by the CV. Use null/empty collections when the
  document does not state a value. Do not fill gaps from common knowledge.
- Return one atomic skill/tool per list item. Never put a sentence, a list of
  technologies, or a conjunction-delimited group into one skill name.
- Keep technical skills, software tools, soft skills, and human languages in
  their defined sections. A technology mentioned in an experience/project may
  also be referenced in the profile skill list, but must be deduplicated safely.
- Keep original spelling and language, including Thai names and labels.
- Do not infer proficiency from job title, years in a role, project duration,
  certificates, or list order. Set proficiency to `unknown` unless the CV
  explicitly states a level. Any future inference rule requires separate
  evidence, calibration, and product approval.
- Dates must preserve their original precision. Normalize only unambiguous
  values; flag ambiguous, invalid, or contradictory ranges for review.
- Distinguish model confidence from evidence. A high confidence score alone
  must not substitute for a source reference.
- Reject non-resume documents with a stable `NOT_A_CV` outcome. For ambiguous
  or low-quality inputs, return a warning/review flag or a stable failure,
  rather than inventing profile data.

### Evidence and review

Every extracted item that can affect a user's profile should carry source
evidence where technically available:

- page number;
- a short exact source quote or a source-span reference for text PDFs;
- for image pages, page number and a short transcribed quote (bounding boxes are
  optional for the first version).

The output should distinguish `not found`, `not verifiable from this input`,
and `verified in source`. Image-only and mixed inputs must not be treated as
grounded just because the model returned high confidence. The current
implementation caps extracted item confidence at medium, marks those items for
review, and adds a warning. Review flags should also account for missing/weak
evidence, ambiguity, invalid dates, partial page processing, and low model
confidence. Users still review the candidate profile before confirmation;
`needsReview=false` is not equivalent to database approval.

## 7. Skill representation and Market catalog matching

The resume result must preserve at least:

```text
rawName       exact wording returned from the CV/model
displayName   safe resume-level formatting/normalization, if applicable
catalogMatch  nullable result from the backend catalog resolver; never guessed by extraction
```

Requirements:

- Deduplicate only clear, lossless equivalents (Unicode normalization,
  surrounding/internal whitespace, and case-insensitive duplicate spellings).
- Do not reorder words, infer acronyms, merge near-synonyms, or use fuzzy
  similarity to collapse distinct skills during extraction.
- The backend resolver must compare against the same `core.skills` canonical
  names and confirmed `core.skill_aliases` used by Market. Reuse or factor the
  pure matching rules so the two domains cannot silently drift; keep database
  reads in the backend adapter and do not make the extraction package
  database-dependent.
- Matching is deterministic: exact canonical name or alias first, then only
  the safe, explicitly supported normalization rules already used by Market
  (for example case/Unicode/whitespace normalization and verified acronym
  handling). Do not use fuzzy similarity or an LLM to auto-assign a
  `skill_id`. The current resolver returns `matched` or `unmatched`; catalog
  integrity conflicts fail the lookup as unavailable rather than being guessed.
  `needs_review` remains the database status for a future/manual ambiguous choice.
- `catalogMatch` should include the matched `skillId`, canonical name, match
  method, and status when matched. Preserve the raw CV/model label and its
  evidence regardless of match outcome. If several raw labels map to one
  `skill_id`, the profile may show one canonical skill while retaining each
  source spelling/evidence.
- Re-run matching after user edits/additions and immediately before saving,
  because the catalog can change between extraction and confirmation. The
  resolver only reads the catalog; it never creates or mutates `core.skills`
  or `core.skill_aliases`.
- Do not discard a skill solely because it has no catalog match. Unknown names
  remain in the candidate profile for the user and later resolver.
- Persist the nullable `skill_id`, `raw_skill_name`, normalized/display value,
  and `match_status` in `app.user_skills`; keep supporting evidence in
  `app.user_skill_evidence`. A match shown before confirmation is a suggestion
  from the catalog, not user confirmation of the overall profile.
- Keep category semantics explicit and consistent. A resume-extracted
  `category` is not automatically the category assigned to a market catalog
  skill.

Current implementation: the pure resolver is in
`src/resume/normalization/catalog.py`; it calls the shared Market matcher. The
backend loads the catalog through a read-only repository and annotates the
poll response before review, then resolves again before saving. Configure all
five `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` settings in
`backend/.env` to enable matching. Without them extraction continues, with
`catalogMatch: null`; with database settings present but the catalog unavailable,
the API returns `SKILL_CATALOG_UNAVAILABLE` instead of claiming there were no
matches.

## 8. Normalization and semantic validation

Deterministic post-processing should:

- validate dates, ranges, email, and URLs without fabricating replacements;
- normalize whitespace and Unicode safely while retaining raw values;
- deduplicate within sections using explicit identity rules and preserve the
  highest-quality evidence/confidence without losing alternate evidence;
- verify cross-field invariants (for example, current roles have no end date;
  start is not after end; one extracted item is not duplicated across
  experience/project/certification categories without explanation);
- validate skill mentions and confidence against the corresponding evidence;
- produce warnings and review reasons as structured data, not only prose;
- compute derived profile attributes only under explicit, explainable rules.

Derived years of experience should avoid counting overlapping jobs twice.
Skill proficiency should remain unknown absent explicit evidence; years in a
role should not be used as a proxy. The user's current employment/status choice
belongs to onboarding/profile confirmation rather than LLM inference.

## 9. Long documents and partial results

The implementation must define budgets for input context, page images, and
output tokens per selected model. If a resume exceeds a budget, use a documented
section/page chunking strategy with stable merge/deduplication and evidence
references, or return an explicit bounded/partial result. Do not silently
truncate the input or represent a first-pages-only extraction as complete.

If chunking is used:

- chunks retain original page numbers and text spans;
- each chunk uses the same prompt/schema version;
- merge logic deduplicates without conflating distinct roles or skills;
- conflicting values are surfaced for review, not resolved by arbitrary
  last-write-wins behavior;
- the result records which pages/chunks were processed and which were omitted.

## 10. Cache and provenance

The cache key must include more than file bytes. It must be invalidated when any
output-affecting input changes, including provider/model, prompt version, schema
version, parser/normalizer version, or relevant settings. Cache metadata must
identify the exact processing configuration used. Do not return a cached result
from a different model/config as if it were produced by the current one.

Retention for raw CV files, parsed text, cached extraction results, job records,
and confirmed profiles must be decided separately. The extraction package stays
free of storage/database code; backend adapters enforce the approved retention
policy.

## 11. Quality evaluation and acceptance

Provider contract tests are necessary but insufficient. Before selecting a
production/default model, evaluate it against a versioned gold set of fictional
CVs with expected field values and source evidence. Cover at minimum:

- English, Thai, and mixed-language CVs;
- text PDF, scanned PDF, photo, multiple columns, and mixed text/image pages;
- short, long, sparse, and dense resumes;
- missing dates/fields, Buddhist Era dates, ambiguous ranges, and overlapping
  experience;
- not-a-CV, malformed/encrypted files, and unsupported types;
- composite skill lists, tools-versus-skills classification, duplicate aliases,
  and unsupported proficiency claims.

Report per-model and per-case precision/recall (or field accuracy), unsupported
claim/hallucination rate, omitted-field rate, review rate, latency, token usage,
and failures. Keep prompts, schema, model tag, settings, gold-set version, and
results together so comparisons are reproducible. Agree numerical release
thresholds before enabling a model as default; a green unit-test suite alone is
not an accuracy sign-off.

The current ten fictional samples are a useful starting point, not yet a
complete acceptance suite. Historical results used a local Qwen model and
included one invented soft skill; they are not a Gemini baseline. The repeatable
Gemini evaluator is `scripts/resume/evaluate_samples.py`, and writes a report
under `data/processed/resume_evaluation/`. It has not yet been run against
Gemini. Expand the gold set and review per-case outputs before using it as a
release gate.

## 12. Scope and implementation status

### In scope

1. [Implemented] Confirm the resume extraction contract and versioned result/provenance fields.
2. [Implemented] Separate resume provider selection from the market extraction prompt while sharing the Gemini client/model configuration.
3. [Implemented] Preserve raw skill wording and remove unsupported catalog-like assumptions
   from extraction.
4. [Implemented] Improve page-level and mixed-document preprocessing behavior and make
   partial coverage explicit.
5. [Implemented in part] Add semantic validation, evidence/review reasons, and safe handling of
   low-confidence output.
6. [Implemented] Fix cache-key/provenance invalidation for output-affecting configuration.
7. [Implemented] Backend-owned skill-catalog resolver compares resume skills
   and tools with `core.skills` and `core.skill_aliases` using the same
   deterministic matching rules as Market; the poll response exposes
   matches/unmatched states and save re-resolves. Never auto-create catalog
   entries.
8. [Partially complete] Establish and run a repeatable model-quality evaluation
   over a gold set. The evaluator and a Gemini sample run exist; run and review
   the full set before setting quality thresholds.
9. [In progress] Keep resume docs and the Backend integration contract aligned
   with current behavior.

### Out of scope for this phase

- job-posting/market extraction changes;
- automatic creation or mutation of `core.skills` / `core.skill_aliases`;
- choosing a provider solely to match market's provider;
- cloud database/S3/distributed-job-queue deployment, authentication, or
  production upload-retention decisions; local-configured PostgreSQL profile
  persistence and the anonymous session flow are implemented by the host
  Backend;
- DOC/DOCX parsing unless explicitly added to the product requirement;
- autonomous inference of seniority, employability, or skill proficiency from
  years of experience.

## 13. Remaining decisions

1. **Provider/model (implemented):** Uses the Gemini model currently pinned by
   market. Any model upgrade should be a deliberate shared change followed by
   resume quality evaluation.
2. **Skill matching boundary (resolved for the plan):** extraction preserves
   the source wording; the backend compares it with the shared Market catalog
   before Review Profile and rechecks before persistence. Matching is
   deterministic and read-only; unresolved/ambiguous names remain visible and
   no resume flow creates catalog entries.
3. **User confirmation policy:** A suggested catalog match is displayed for
   review. The user confirms/edits the profile; unresolved skills remain
   free-form in `app.user_skills` with a null `skill_id` and an explicit status.
4. **Partial processing (implemented for omitted scanned pages):** When scan
   pages exceed the configured image-page limit, the API returns an explicitly
   partial result with omitted page numbers and `meta.isPartial=true`. Long
   text documents that exceed Gemini's output limit currently fail; a chunking
   strategy remains a separate implementation decision.
5. **Proficiency (implemented):** Levels stay `unknown` unless the CV text
   explicitly states a level alongside the skill. Job/project duration and
   certifications are evidence of exposure, not proficiency. Image-only input
   without inspectable source text also remains `unknown`.
6. **Quality gates:** Agree acceptable field/skill accuracy, unsupported-claim
   rate, latency, and review-rate thresholds before a model is treated as
   production-ready.

The remaining decisions above are product choices; implemented behavior is
identified inline. The current state and concrete implementation risks are in
[`01-current-state-review.md`](01-current-state-review.md).
