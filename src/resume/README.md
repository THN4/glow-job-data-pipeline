# Resume domain

`src.resume` is the planned CV/resume-processing boundary. It is currently a
package scaffold; it does not yet parse files, call an extractor, or write
resume records.

| Package | Planned responsibility |
|---|---|
| `parsing` | Read supported resume files and produce clean text with source/page metadata. |
| `extraction` | Identify structured profile fields such as experience, education, and stated skills. |
| `normalization` | Normalize extracted fields and map skill names through `src.shared.skill_normalization`. |
| `schemas` | Define validated input, intermediate, and output contracts for resume processing. |

Keep resume-specific prompts, parsing rules, output schemas, and persistence
inside this domain. Reuse generic LLM and database adapters from `src.shared`;
do not import private market pipeline code to process a resume.

The exact supported file types, retention policy, extracted fields, and
confidence/review behavior must be specified before implementing parsers or
database writes.
