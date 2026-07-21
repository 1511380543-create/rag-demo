from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ExtractRequest(BaseModel):
    documents: list[IndexDocument] = Field(min_length=1)


class ExtractReportItem(BaseModel):
    doc_id: str
    dropped_elements: int
    dropped_fragments: int = 0
    dropped_garbled: int = 0
    table_count: int
    table_quality_failed: int = 0
    merged_continuations: int
    paragraph_block_count: int = 0
    title_count: int = 0
    paragraph_count: int = 0
    list_item_count: int = 0


class ExtractResponse(BaseModel):
    extracted_doc_count: int
    total_page_count: int
    total_char_count: int
    reports: list[ExtractReportItem] | None = None


class ChunkRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1)

    @field_validator("doc_ids")
    @classmethod
    def validate_doc_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("doc_ids 中不允许出现空字符串")
            normalized.append(cleaned)
        return normalized


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
    extracted_docs: int
    indexed_docs: int
    indexed_chunks: int


class ErrorResponse(BaseModel):
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    detail: dict[str, Any] | None = None


class MetricsResponse(BaseModel):
    window_minutes: int | None = None
    total_queries: int
    empty_recall_count: int
    empty_recall_rate: float
    avg_total_ms: float
    p95_total_ms: float
    avg_embed_ms: float
    avg_retrieve_ms: float
    avg_top_score: float


class EvalCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    query_text: str = Field(min_length=1)
    relevant_chunk_ids: list[str] | None = None
    expected_keywords: list[str] | None = None
    keyword_match_mode: Literal["any", "all"] = "any"
    top_k: int | None = Field(default=None, ge=1, le=20)
    enabled: bool = True

    @field_validator("case_id", "query_text")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空白")
        return cleaned

    @field_validator("relevant_chunk_ids", "expected_keywords")
    @classmethod
    def validate_str_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("标注列表中不允许出现空字符串")
            normalized.append(cleaned)
        return normalized

    @model_validator(mode="after")
    def validate_ground_truth(self) -> "EvalCase":
        # 两类标注至少提供其一，否则无法判定命中。
        if not self.relevant_chunk_ids and not self.expected_keywords:
            raise ValueError("relevant_chunk_ids 与 expected_keywords 至少提供其一")
        return self


class EvalDatasetUpsertRequest(BaseModel):
    cases: list[EvalCase] = Field(min_length=1)


class EvalDatasetUpsertResponse(BaseModel):
    upserted_count: int


class EvalDatasetListResponse(BaseModel):
    cases: list[EvalCase]
    total: int


class EvalRunRequest(BaseModel):
    case_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    note: str | None = None

    @field_validator("case_ids")
    @classmethod
    def validate_case_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("case_ids 中不允许出现空字符串")
            normalized.append(cleaned)
        return normalized


class EvalMetricItem(BaseModel):
    case_id: str
    query_text: str
    hit: int
    recall: float
    mrr: float
    latency_ms: int
    retrieved_chunk_ids: list[str]


class EvalRunResponse(BaseModel):
    run_id: int
    dataset_size: int
    top_k: int
    avg_hit: float
    avg_recall: float
    avg_mrr: float
    avg_latency_ms: float
    items: list[EvalMetricItem]


class EvalRunSummary(BaseModel):
    run_id: int
    dataset_size: int
    top_k: int
    avg_hit: float
    avg_recall: float
    avg_mrr: float
    avg_latency_ms: float
    note: str | None = None
    created_at: str


class EvalRunListResponse(BaseModel):
    runs: list[EvalRunSummary]
    total: int
