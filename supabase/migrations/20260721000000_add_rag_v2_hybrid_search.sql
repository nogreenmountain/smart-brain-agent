-- RAG v2 keeps the original public.document_chunks vector(384) table intact.
-- This table stores BGE-M3 dense vectors plus PostgreSQL FTS material.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.document_chunks_v2 (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    content text NOT NULL,
    token_count integer NOT NULL CHECK (token_count > 0),
    source_page integer,
    source_line integer,
    heading_path text,
    fts_text text NOT NULL DEFAULT '',
    content_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple'::regconfig, coalesce(fts_text, ''))
    ) STORED,
    embedding_model text NOT NULL,
    embedding_version text NOT NULL,
    embedding vector(1024) NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT uq_doc_chunk_v2_index UNIQUE (document_id, embedding_version, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_v2_document_id
    ON public.document_chunks_v2 USING btree (document_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_v2_project_id
    ON public.document_chunks_v2 USING btree (project_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_v2_model_version
    ON public.document_chunks_v2 USING btree (embedding_model, embedding_version);

CREATE INDEX IF NOT EXISTS idx_document_chunks_v2_content_tsv
    ON public.document_chunks_v2 USING gin (content_tsv);

CREATE INDEX IF NOT EXISTS idx_document_chunks_v2_embedding
    ON public.document_chunks_v2
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = '16', ef_construction = '64');
