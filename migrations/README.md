# Database migrations

Migration files are applied in filename order by `python -m scripts.database.migrate`. Each successful file is recorded in `system.schema_migrations`, so running the command again skips already-applied migrations.

The first migration creates the database objects needed to load JSearch market postings and their ingestion/query provenance. Migrations `002` through `004` add the skill catalog, job-skill links, and career aggregates. Migration `005` adds a date-quality label, a stable `first_seen_at`, and a date basis to career statistics. Migration `006` adds provisional catalog status and a legacy candidate-review queue. Migration `007` adds the `split_applied` candidate status used when a reviewed compound extraction is expanded into multiple job skills. Migrations are applied in filename order and are recorded in `system.schema_migrations`.
