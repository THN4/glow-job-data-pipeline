# Documentation index

Documentation is grouped by the domain or work area it describes. The
`market`, `documents`, and `resume` folders map to packages under `src/`;
`architecture` and `database` contain cross-domain references.

## File naming

Documentation filenames use lowercase kebab-case. Within a domain folder, use
`<subject>-<document-type>.md` so the name states both the topic and purpose:

- `market-pipeline-spec.md` — market-domain requirements and scope
- `skill-extraction-spec.md` — extraction rules and current behavior
- `skill-candidate-review-guide.md` — review steps and commands
- `database-schema-overview.md` — implemented schema and planned schema status

Use descriptive schema names such as `<system>-schema.dbml` and
`<system>-schema.dbdiagram` for paired database design files. Keep `README.md`
for a folder's landing page or index.

| Folder | Contents |
|---|---|
| [architecture](architecture/) | Repository layout and Git workflow. |
| [market](market/) | Job-market pipeline, skill extraction, review, and data structures. |
| [resume](resume/) | Reusable CV/resume parsing, extraction contracts, schemas, and post-processing. |
| [documents](documents/) | Skill-learning document ingestion and learning-graph design. |
| [database](database/) | Cross-domain database schema documentation and DBML/DBDiagram files. |

## Market

- [Project specification](market/market-pipeline-spec.md)
- [Pipeline data structures](market/pipeline-data-structures.md)
- [Skill extraction specification](market/skill-extraction-spec.md)
- [Skill candidate review guide](market/skill-candidate-review-guide.md)

## Resume

The resume domain currently provides reusable processing modules consumed by
the host backend. Its API orchestration, persistence, and CLI workflows remain
in the host backend or are planned follow-up work. See [resume domain notes](resume/README.md)
and [the package README](../src/resume/README.md) for the boundaries.

## Documents

- [Learning document and graph flow](documents/learning-graph-flow.md)

## Database and architecture

- [Database schema overview](database/database-schema-overview.md)
- [Repository architecture and data flow](architecture/repository-architecture.md)
- [Git workflow](architecture/git-workflow.md)
