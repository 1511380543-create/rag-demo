import logging
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import QueryBundle, TextNode

from app.config import Settings
from app.eval_metrics import compute_eval_metrics
from app.eval_store import EvalCaseRow, EvalRunItemRow, EvalStore
from app.local_pdf_reader import read_pdf_text
from app.models import (
    BuildIndexRequest,
    EvalCase,
    EvalDatasetListResponse,
    EvalMetricItem,
    EvalRunListResponse,
    EvalRunRequest,
    EvalRunResponse,
    EvalRunSummary,
    HealthResponse,
    IndexDocument,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
    RetrievedContext,
)
from app.monitoring_store import MonitoringStore, QueryLogItem
from app.mysql_chunk_store import ChunkWriteItem, MySQLChunkStore
from app.qwen_embedding import QwenEmbedding

logger = logging.getLogger(__name__)


class IndexNotReadyError(RuntimeError):
    """索引未就绪异常。"""


class NoChunksAvailableError(RuntimeError):
    """没有可用于构建索引的 chunk。"""


class EvalDatasetEmptyError(RuntimeError):
    """评测集为空，无法执行评测。"""


@dataclass
class _RetrievalResult:
    """内部检索结果，供查询与评测复用。"""

    contexts: list[RetrievedContext]
    embed_ms: int
    retrieve_ms: int
    retrieved_before_filter: int


class RagService:
    """RAG 检索服务：负责入库、检索与健康信息。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = RLock()
        self._index: VectorStoreIndex | None = None
        self._indexed_doc_count = 0
        self._indexed_chunk_count = 0

        self._splitter = SentenceSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self._chunk_store = MySQLChunkStore(settings=settings)
        self._monitoring_store = MonitoringStore(settings=settings)
        self._eval_store = EvalStore(settings=settings)
        self._embed_model = QwenEmbedding(
            api_key=settings.api_key_ali,
            model_name=settings.embedding_model,
            api_base=settings.dashscope_base_url,
        )
        LlamaSettings.embed_model = self._embed_model

    def ingest_documents(self, documents: list[IndexDocument]) -> tuple[int, int]:
        """从本地读取 PDF，切分后写入 MySQL。"""
        stored_doc_count = 0
        stored_chunk_count = 0
        with self._lock:
            for item in documents:
                content = self._read_local_document(item.file_path)
                chunks = self._split_to_chunks(
                    doc_id=item.doc_id,
                    file_path=item.file_path,
                    content=content,
                    metadata=item.metadata,
                )
                stored_count = self._chunk_store.replace_document_chunks(item.doc_id, chunks)
                stored_doc_count += 1
                stored_chunk_count += stored_count
        return stored_doc_count, stored_chunk_count

    def build_index(self, request: BuildIndexRequest) -> tuple[int, int, str]:
        """从 MySQL 读取 chunk 数据并构建索引。"""
        with self._lock:
            chunk_rows = self._chunk_store.fetch_chunks(request.doc_ids)
            if not chunk_rows:
                self._index = None
                self._indexed_doc_count = 0
                self._indexed_chunk_count = 0
                raise NoChunksAvailableError("MySQL 中没有可用于构建索引的 chunk，请先调用 /rag/chunks")

            nodes: list[TextNode] = []
            doc_ids: set[str] = set()
            for row in chunk_rows:
                metadata = dict(row.metadata or {})
                metadata["doc_id"] = row.doc_id
                metadata["chunk_index"] = row.chunk_index
                metadata["chunk_id"] = str(row.id)
                metadata["source"] = "mysql"
                doc_ids.add(row.doc_id)

                nodes.append(TextNode(text=row.chunk_text, metadata=metadata, id_=str(row.id)))

            self._index = VectorStoreIndex(nodes, embed_model=self._embed_model)
            self._indexed_doc_count = len(doc_ids)
            self._indexed_chunk_count = len(nodes)
            return self._indexed_doc_count, self._indexed_chunk_count, self._settings.index_name

    def query(self, request: QueryRequest) -> QueryResponse:
        total_start = perf_counter()
        with self._lock:
            if self._index is None:
                total_ms = int((perf_counter() - total_start) * 1000)
                self._record_query_trace(
                    request=request,
                    embed_ms=0,
                    retrieve_ms=0,
                    retrieved_before_filter=0,
                    retrieved_after_filter=0,
                    contexts=[],
                    total_ms=total_ms,
                    error_code="INDEX_NOT_READY",
                )
                raise IndexNotReadyError("索引尚未初始化，请先调用 /rag/index/build")

            try:
                retrieval = self._retrieve(
                    query=request.query,
                    top_k=request.top_k,
                    filters=request.filters,
                )
                total_ms = int((perf_counter() - total_start) * 1000)
                score_stats = self._score_stats(retrieval.contexts)
                response = QueryResponse(
                    query=request.query,
                    top_k=request.top_k,
                    contexts=retrieval.contexts,
                    trace={
                        "retrieved_before_filter": retrieval.retrieved_before_filter,
                        "retrieved_after_filter": len(retrieval.contexts),
                        "filters_applied": bool(request.filters),
                        "embed_ms": retrieval.embed_ms,
                        "retrieve_ms": retrieval.retrieve_ms,
                        "total_ms": total_ms,
                        "top_score": score_stats["top_score"],
                        "avg_score": score_stats["avg_score"],
                    },
                )
                self._record_query_trace(
                    request=request,
                    embed_ms=retrieval.embed_ms,
                    retrieve_ms=retrieval.retrieve_ms,
                    retrieved_before_filter=retrieval.retrieved_before_filter,
                    retrieved_after_filter=len(retrieval.contexts),
                    contexts=retrieval.contexts,
                    total_ms=total_ms,
                    error_code=None,
                )
                return response
            except Exception:
                total_ms = int((perf_counter() - total_start) * 1000)
                self._record_query_trace(
                    request=request,
                    embed_ms=0,
                    retrieve_ms=0,
                    retrieved_before_filter=0,
                    retrieved_after_filter=0,
                    contexts=[],
                    total_ms=total_ms,
                    error_code="QUERY_EXECUTION_ERROR",
                )
                raise

    def get_metrics(self, window_minutes: int | None) -> MetricsResponse:
        result = self._monitoring_store.aggregate_metrics(window_minutes)
        return MetricsResponse(
            window_minutes=result.window_minutes,
            total_queries=result.total_queries,
            empty_recall_count=result.empty_recall_count,
            empty_recall_rate=result.empty_recall_rate,
            avg_total_ms=result.avg_total_ms,
            p95_total_ms=result.p95_total_ms,
            avg_embed_ms=result.avg_embed_ms,
            avg_retrieve_ms=result.avg_retrieve_ms,
            avg_top_score=result.avg_top_score,
        )

    def upsert_eval_dataset(self, cases: list[EvalCase]) -> int:
        rows = [
            EvalCaseRow(
                case_id=case.case_id,
                query_text=case.query_text,
                relevant_chunk_ids=case.relevant_chunk_ids,
                expected_keywords=case.expected_keywords,
                keyword_match_mode=case.keyword_match_mode,
                top_k=case.top_k,
                enabled=case.enabled,
            )
            for case in cases
        ]
        return self._eval_store.upsert_cases(rows)

    def list_eval_dataset(self) -> EvalDatasetListResponse:
        rows = self._eval_store.list_cases()
        cases = [self._to_eval_case(row) for row in rows]
        return EvalDatasetListResponse(cases=cases, total=len(cases))

    def run_eval(self, request: EvalRunRequest) -> EvalRunResponse:
        with self._lock:
            if self._index is None:
                raise IndexNotReadyError("索引尚未初始化，请先调用 /rag/index/build")

            cases = self._eval_store.fetch_cases(request.case_ids)
            if not cases:
                raise EvalDatasetEmptyError("评测集为空，请先调用 /rag/eval/dataset 写入样本")

            items: list[EvalMetricItem] = []
            for case in cases:
                top_k = self._resolve_eval_top_k(request.top_k, case.top_k)
                latency_start = perf_counter()
                retrieval = self._retrieve(
                    query=case.query_text,
                    top_k=top_k,
                    filters=None,
                )
                latency_ms = int((perf_counter() - latency_start) * 1000)
                retrieved_chunk_ids = [item.chunk_id for item in retrieval.contexts]
                retrieved_texts = [item.chunk_text for item in retrieval.contexts]
                metrics = compute_eval_metrics(
                    case=case,
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    retrieved_texts=retrieved_texts,
                )
                items.append(
                    EvalMetricItem(
                        case_id=case.case_id,
                        query_text=case.query_text,
                        hit=metrics.hit,
                        recall=metrics.recall,
                        mrr=metrics.mrr,
                        latency_ms=latency_ms,
                        retrieved_chunk_ids=retrieved_chunk_ids,
                    )
                )

            dataset_size = len(items)
            avg_hit = sum(item.hit for item in items) / dataset_size
            avg_recall = sum(item.recall for item in items) / dataset_size
            avg_mrr = sum(item.mrr for item in items) / dataset_size
            avg_latency_ms = sum(item.latency_ms for item in items) / dataset_size
            run_top_k = request.top_k if request.top_k is not None else 3

            run_id = self._eval_store.insert_run(
                dataset_size=dataset_size,
                top_k=run_top_k,
                avg_hit=avg_hit,
                avg_recall=avg_recall,
                avg_mrr=avg_mrr,
                avg_latency_ms=avg_latency_ms,
                note=request.note,
            )
            self._eval_store.insert_run_items(
                run_id,
                [
                    EvalRunItemRow(
                        case_id=item.case_id,
                        query_text=item.query_text,
                        hit=item.hit,
                        recall=item.recall,
                        mrr=item.mrr,
                        latency_ms=item.latency_ms,
                        retrieved_chunk_ids=item.retrieved_chunk_ids,
                    )
                    for item in items
                ],
            )
            return EvalRunResponse(
                run_id=run_id,
                dataset_size=dataset_size,
                top_k=run_top_k,
                avg_hit=avg_hit,
                avg_recall=avg_recall,
                avg_mrr=avg_mrr,
                avg_latency_ms=avg_latency_ms,
                items=items,
            )

    def list_eval_runs(self, limit: int) -> EvalRunListResponse:
        rows = self._eval_store.list_runs(limit)
        total = self._eval_store.count_runs()
        runs = [
            EvalRunSummary(
                run_id=row.run_id,
                dataset_size=row.dataset_size,
                top_k=row.top_k,
                avg_hit=row.avg_hit,
                avg_recall=row.avg_recall,
                avg_mrr=row.avg_mrr,
                avg_latency_ms=row.avg_latency_ms,
                note=row.note,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return EvalRunListResponse(runs=runs, total=total)

    def health(self) -> HealthResponse:
        with self._lock:
            indexed_docs = self._chunk_store.count_distinct_docs()
            indexed_chunks = self._chunk_store.count_chunks()
            return HealthResponse(
                status="ok",
                index_ready=self._index is not None,
                indexed_docs=indexed_docs,
                indexed_chunks=indexed_chunks,
            )

    def _retrieve(self, query: str, top_k: int, filters: dict[str, Any] | None) -> _RetrievalResult:
        embed_start = perf_counter()
        query_embedding = self._embed_model.get_query_embedding(query)
        embed_ms = int((perf_counter() - embed_start) * 1000)

        retrieve_start = perf_counter()
        retriever = self._index.as_retriever(similarity_top_k=max(top_k * 3, top_k))
        query_bundle = QueryBundle(query_str=query, embedding=query_embedding)
        raw_results = retriever.retrieve(query_bundle)
        retrieve_ms = int((perf_counter() - retrieve_start) * 1000)

        contexts: list[RetrievedContext] = []
        for node_with_score in raw_results:
            metadata = dict(node_with_score.node.metadata or {})
            if not self._match_filters(metadata, filters):
                continue

            doc_id = str(metadata.get("doc_id", "")).strip()
            chunk_id = str(metadata.get("chunk_id", node_with_score.node.node_id)).strip()
            chunk_text = node_with_score.node.get_content().strip()
            if not doc_id or not chunk_id or not chunk_text:
                continue

            contexts.append(
                RetrievedContext(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    chunk_text=chunk_text,
                    score=float(node_with_score.score or 0.0),
                    metadata=metadata,
                )
            )
            if len(contexts) >= top_k:
                break

        return _RetrievalResult(
            contexts=contexts,
            embed_ms=embed_ms,
            retrieve_ms=retrieve_ms,
            retrieved_before_filter=len(raw_results),
        )

    def _record_query_trace(
        self,
        request: QueryRequest,
        embed_ms: int,
        retrieve_ms: int,
        retrieved_before_filter: int,
        retrieved_after_filter: int,
        contexts: list[RetrievedContext],
        total_ms: int,
        error_code: str | None,
    ) -> None:
        # 监控写库异常不得影响查询主流程，仅记录日志。
        score_stats = self._score_stats(contexts)
        item = QueryLogItem(
            query_text=request.query,
            top_k=request.top_k,
            filters_applied=bool(request.filters),
            embed_ms=embed_ms,
            retrieve_ms=retrieve_ms,
            total_ms=total_ms,
            retrieved_before_filter=retrieved_before_filter,
            retrieved_after_filter=retrieved_after_filter,
            is_empty_recall=retrieved_after_filter == 0,
            top_score=score_stats["top_score"],
            min_score_value=score_stats["min_score_value"],
            avg_score=score_stats["avg_score"],
            error_code=error_code,
        )
        try:
            self._monitoring_store.insert_query_log(item)
        except Exception:
            logger.exception("写入查询监控日志失败")

    @staticmethod
    def _score_stats(contexts: list[RetrievedContext]) -> dict[str, float | None]:
        if not contexts:
            return {"top_score": None, "min_score_value": None, "avg_score": None}
        scores = [item.score for item in contexts]
        return {
            "top_score": max(scores),
            "min_score_value": min(scores),
            "avg_score": sum(scores) / len(scores),
        }

    @staticmethod
    def _resolve_eval_top_k(request_top_k: int | None, case_top_k: int | None) -> int:
        if request_top_k is not None:
            return request_top_k
        if case_top_k is not None:
            return case_top_k
        return 3

    @staticmethod
    def _to_eval_case(row: EvalCaseRow) -> EvalCase:
        return EvalCase(
            case_id=row.case_id,
            query_text=row.query_text,
            relevant_chunk_ids=row.relevant_chunk_ids,
            expected_keywords=row.expected_keywords,
            keyword_match_mode=row.keyword_match_mode,
            top_k=row.top_k,
            enabled=row.enabled,
        )

    @staticmethod
    def _match_filters(metadata: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        for key, value in filters.items():
            if metadata.get(key) != value:
                return False
        return True

    @staticmethod
    def _read_local_document(file_path: str) -> str:
        # 当前阶段仅支持本地 PDF 入库，避免混入未定义格式。
        normalized = file_path.strip()
        if not normalized.lower().endswith(".pdf"):
            raise ValueError("仅支持 PDF 文档入库，请传入 .pdf 文件路径")

        content = read_pdf_text(normalized)
        if not content:
            raise ValueError(f"文档内容为空，无法入库: {normalized}")
        return content

    def _split_to_chunks(
        self,
        doc_id: str,
        file_path: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> list[ChunkWriteItem]:
        base_metadata = dict(metadata or {})
        base_metadata["doc_id"] = doc_id
        base_metadata["file_path"] = file_path

        doc = Document(text=content, metadata=base_metadata, id_=doc_id)
        nodes = self._splitter.get_nodes_from_documents([doc])

        chunks: list[ChunkWriteItem] = []
        for index, node in enumerate(nodes):
            chunk_text = node.get_content().strip()
            if not chunk_text:
                continue

            chunk_metadata = dict(node.metadata or {})
            chunk_metadata["doc_id"] = doc_id
            chunk_metadata["file_path"] = file_path
            chunk_metadata["chunk_index"] = index
            chunks.append(
                ChunkWriteItem(
                    chunk_index=index,
                    chunk_text=chunk_text,
                    metadata=chunk_metadata,
                )
            )
        return chunks
