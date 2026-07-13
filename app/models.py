from typing import Any

from pydantic import BaseModel, Field, field_validator


class IndexDocument(BaseModel):
    doc_id: str = Field(min_length=1, max_length=128)
    file_path: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None

    @field_validator("doc_id", "file_path")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        # 统一去除首尾空白，避免无效输入进入索引。
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空白")
        return cleaned


class IndexRequest(BaseModel):
    documents: list[IndexDocument] = Field(min_length=1)


class ChunkIngestResponse(BaseModel):
    stored_doc_count: int
    stored_chunk_count: int


class BuildIndexRequest(BaseModel):
    doc_ids: list[str] | None = None
    force_rebuild: bool = True

    @field_validator("doc_ids")
    @classmethod
    def validate_doc_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None

        normalized: list[str] = []
        for item in value:
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("doc_ids 中不允许出现空字符串")
            normalized.append(cleaned)
        return normalized


class BuildIndexResponse(BaseModel):
    indexed_doc_count: int
    indexed_chunk_count: int
    index_name: str


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=20)
    filters: dict[str, Any] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query 不能为空白")
        return cleaned


class RetrievedContext(BaseModel):
    doc_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    score: float
    metadata: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    query: str
    top_k: int
    contexts: list[RetrievedContext]
    trace: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    index_ready: bool
    indexed_docs: int
    indexed_chunks: int


class ErrorResponse(BaseModel):
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    detail: dict[str, Any] | None = None
