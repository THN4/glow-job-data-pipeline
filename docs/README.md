# Documentation index

Documentation is grouped by the domain or work area it describes. The
`market`, `documents`, and `resume` folders map to packages under `src/`;
`architecture` describes repository boundaries, while `database` documents
pipeline-owned schema and migration status. The whole-system schema remains in
the host repository's `docs/schemas/`.

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
| [market](market/) | End-to-end job-market pipeline, skill extraction, review, and data structures. |
| [resume](resume/) | End-to-end CV extraction flow, reusable extraction contracts, and the host Backend boundary. |
| [documents](documents/) | Skill-learning document ingestion and learning-graph design. |
| [database](database/) | Pipeline-owned schema documentation and DBML/DBDiagram domain views. |

## Market

- [End-to-end Market pipeline flow](market/market-pipeline-flow.md)
- [Project specification](market/market-pipeline-spec.md)
- [Pipeline data structures](market/pipeline-data-structures.md)
- [Skill extraction specification](market/skill-extraction-spec.md)
- [Skill candidate review guide](market/skill-candidate-review-guide.md)

## Resume

- [End-to-end Resume pipeline flow](resume/resume-pipeline-flow.md)
- [Resume domain notes](resume/README.md)

The reusable extractor is in `src/resume`; upload/job orchestration, catalog
lookup, user confirmation, and profile storage are owned by the host Backend.
See [the package README](../src/resume/README.md) for implementation boundaries.

## Documents

- [Skill knowledge ingestion and RAG specification](documents/skill-knowledge-rag-spec.md)
- [Learning document and graph flow](documents/learning-graph-flow.md)

## Database and architecture

- [Database schema overview](database/database-schema-overview.md)
- [Pipeline DBML](database/schemas/pipeline-schema.dbml)
- [Planned knowledge DBML](database/schemas/knowledge-schema.dbml)
- [Consolidated Glow-Job DBML in the host repo](../../docs/schemas/glow-job.dbml)
- [Repository architecture and data flow](architecture/repository-architecture.md)
- [Git workflow](architecture/git-workflow.md)
