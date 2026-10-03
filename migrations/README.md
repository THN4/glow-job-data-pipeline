# Database migrations

Migration files are applied in filename order by `python -m scripts.migrate`. Each successful file is recorded in `system.schema_migrations`, so running the command again skips already-applied migrations.

The first migration creates the database objects needed to load JSearch market postings and their ingestion/query provenance. Later pipeline tables such as skills and career aggregates should be added in their own migration when those stages are implemented.
