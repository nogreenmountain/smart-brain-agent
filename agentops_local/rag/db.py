"""
SQLAlchemy ORM models for the RAG knowledge base.

Schema mirrors public.documents / public.document_chunks from P1.

We deliberately avoid:
  - ForeignKey() declarations: would require projects/users/documents to be
    registered in the same metadata. We share a DB with the rest of the
    AgentOps app; those models are not loaded here.
  - relationship() joins: same reason.

This keeps the models a thin CRUD layer. Joins at the SQL level are fine
when needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


DOCUMENT_FORMATS = (
    "bat",
    "c",
    "conf",
    "cpp",
    "cs",
    "css",
    "csv",
    "docx",
    "go",
    "h",
    "hpp",
    "html",
    "java",
    "js",
    "json",
    "jsx",
    "log",
    "md",
    "pdf",
    "pptx",
    "ps1",
    "py",
    "rs",
    "scss",
    "sh",
    "sql",
    "ts",
    "tsx",
    "txt",
    "vue",
    "xml",
    "yaml",
    "yml",
)
DOCUMENT_FORMAT_CHECK = "format IN (" + ", ".join(f"'{fmt}'" for fmt in DOCUMENT_FORMATS) + ")"


class _Base(DeclarativeBase):
    pass


class Document(_Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(DOCUMENT_FORMAT_CHECK),
        CheckConstraint("size_bytes > 0"),
        CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DocumentChunk(_Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk_index"),
        CheckConstraint("chunk_index >= 0"),
        CheckConstraint("token_count > 0"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_line: Mapped[int | None] = mapped_column(Integer)
    embedding = Column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentChunkV2(_Base):
    __tablename__ = "document_chunks_v2"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "embedding_version",
            "chunk_index",
            name="uq_doc_chunk_v2_index",
        ),
        CheckConstraint("chunk_index >= 0"),
        CheckConstraint("token_count > 0"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_line: Mapped[int | None] = mapped_column(Integer)
    heading_path: Mapped[str | None] = mapped_column(Text)
    fts_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_tsv = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, coalesce(fts_text, ''))",
            persisted=True,
        ),
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
