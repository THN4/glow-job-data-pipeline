# Resume domain

`src.resume` owns reusable CV/resume-processing code shared with the Glow Job
backend. The current implementation contains file preprocessing, Gemini
extraction contracts and prompts, validated schemas, and post-processing and
derived facts. The host backend remains responsible for HTTP endpoints,
upload/job lifecycle, catalog lookup, user confirmation, and profile
persistence. See the [end-to-end flow](../../docs/resume/resume-pipeline-flow.md).

| Package | Responsibility |
|---|---|
| `parsing` | Validate PDF/image inputs and prepare text or page images for a model. |
| `extraction` | Define the model contract and prompt for structured profile extraction. |
| `normalization` | Build the profile, deduplicate skill names, attach evidence, and derive profile facts. |
| `schemas` | Define validated extraction and profile contracts. |

Keep resume-specific prompts, parsing rules, and output schemas in this domain.
Profile skills preserve the model's label in `rawName`; the user-facing `name`
only receives Unicode and whitespace cleanup. It is not a canonical catalog
match. The result metadata records provider, model, prompt, profile/extraction
schema, and processing versions. Backend cache identity includes the file hash,
those versions, provider settings, and page limits. The legacy alias helper
still supports grounding and technology-list formatting, but it must not
replace the profile skill's observed label. Do not import private market
pipeline code to process a resume.

The backend imports this domain from the sibling submodule. Initialize
`data-pipeline` from the `glow-job` root before running the backend.

Resume model-backed extraction uses `src.resume.extraction.providers.gemini`,
which calls the shared Gemini model and reads `GEMINI_API_KEY`. Set
`RESUME_EXTRACTOR=gemini` to enable it; `RESUME_EXTRACTOR=mock` keeps local
development and API integration independent from external model calls. The
resume adapter handles CV images and structured JSON output; it does not use
the market skill-extraction prompt.
