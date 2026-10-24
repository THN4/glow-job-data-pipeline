-- Store Nova embeddings alongside existing Gemini vectors during migration.
-- The 1024 dimensions are supported by Amazon Nova Multimodal Embeddings.
ALTER TABLE knowledge.knowledge_chunks
    ADD COLUMN embedding_nova_model text,
    ADD COLUMN embedding_nova vector(1024);
