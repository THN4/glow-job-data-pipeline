# Resume domain

`src.resume` owns reusable CV/resume-processing code shared with the Glow Job
backend. The current implementation contains file preprocessing, extraction
contracts and prompts, validated schemas, and post-processing/derived facts.
The backend remains responsible for HTTP endpoints, upload/job lifecycle, and
profile persistence.

| Package | Planned responsibility |
|---|---|
| `parsing` | Validate PDF/image inputs and prepare text or page images for a model. |
| `extraction` | Define the model contract and prompt for structured profile extraction. |
| `normalization` | Build the profile, deduplicate skill names, attach evidence, and derive profile facts. |
| `schemas` | Define validated extraction and profile contracts. |

Keep resume-specific prompts, parsing rules, and output schemas in this domain.
The skill alias list is currently carried over from the backend and is a
temporary resume-specific normalizer; aligning it with the reviewed shared
catalog is a separate follow-up. Do not import private market pipeline code to
process a resume.

The backend imports this domain from the sibling submodule. Initialize
`data-pipeline` from the `glow-job` root before running the backend.
