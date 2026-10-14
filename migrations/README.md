# Database migrations

Migration files in this repository and the host repository's
`migrations/versions/` are applied in filename order by
`python -m scripts.database.migrate`. Each successful file is recorded in
`system.schema_migrations`, so running the command again skips already-applied
migrations. The root [migration guide](../../migrations/README.md) documents
the combined history.

The first migration creates the database objects needed to load JSearch market postings and their ingestion/query provenance. Migrations `002` through `004` add the skill catalog, job-skill links, and career aggregates. Migration `005` adds a date-quality label, a stable `first_seen_at`, and a date basis to career statistics. Migration `006` adds provisional catalog status and a legacy candidate-review queue. Migration `007` adds the `split_applied` candidate status used when a reviewed compound extraction is expanded into multiple job skills. Host migration `008` creates the application profile and roadmap schema. Migration `010` enables pgvector; migration `011` creates the MVP document source and chunk tables with 768-dimensional embeddings; migration `012` renames the canonical `airflow` skill to `Apache Airflow` and keeps the former label as an alias; migration `013` maps chunks to one or more skills through `knowledge.knowledge_chunk_skills`. The PostgreSQL image must include the extension files before migration `010` is applied.
