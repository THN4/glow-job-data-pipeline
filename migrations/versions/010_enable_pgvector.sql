-- Enable pgvector in the application database.
-- The PostgreSQL server image must include the pgvector extension files.
CREATE EXTENSION IF NOT EXISTS vector;
