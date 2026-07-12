from dataclasses import dataclass
from threading import RLock
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from app.config import Settings
from app.local_pdf_reader import read_pdf_text
from app.models import HealthResponse, IndexDocument, QueryRequest, QueryResponse, RetrievedContext
from app.qwen_embedding import QwenEmbedding


class IndexNotReadyError(RuntimeError):
    """索引未就绪异常。"""


@dataclass
class StoredDocument:
    content: str
    file_path: str
    metadata: dict[str, Any] | None


class RagService:
    """RAG 检索服务：负责入库、检索与健康信息。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = RLock()
        self._doc_store: dict[str, StoredDocument] = {}
        self._chunk_count = 0
        self._index: VectorStoreIndex | None = None

        self._splitter = SentenceSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self._embed_model = QwenEmbedding(
            api_key=settings.api_key_ali,
            model_name=settings.embedding_model,
            api_base=settings.dashscope_base_url,
        )
        LlamaSettings.embed_model = self._embed_model

    def index_documents(self, documents: list[IndexDocument]) -> tuple[int, int, str]:
        """从本地文件读取并入库，按 doc_id 覆盖旧版本后重建索引。"""
        with self._lock:
            for item in documents:
                content = self._read_local_document(item.file_path)
                self._doc_store[item.doc_id] = StoredDocument(
                    content=content,
                    file_path=item.file_path,
                    metadata=item.metadata,
                )
            self._rebuild_index()
            return len(documents), self._chunk_count, self._settings.index_name

    def query(self, request: QueryRequest) -> QueryResponse:
        with self._lock:
            if self._index is None:
                raise IndexNotReadyError("索引尚未初始化，请先调用 /rag/index")

            retriever = self._index.as_retriever(similarity_top_k=max(request.top_k * 3, request.top_k))
            raw_results = retriever.retrieve(request.query)

            contexts: list[RetrievedContext] = []
            for node_with_score in raw_results:
                metadata = dict(node_with_score.node.metadata or {})
                if not self._match_filters(metadata, request.filters):
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
                if len(contexts) >= request.top_k:
                    break

            return QueryResponse(
                query=request.query,
                top_k=request.top_k,
                contexts=contexts,
                trace={
                    "retrieved_before_filter": len(raw_results),
                    "retrieved_after_filter": len(contexts),
                    "filters_applied": bool(request.filters),
                },
            )

    def health(self) -> HealthResponse:
        with self._lock:
            return HealthResponse(
                status="ok",
                index_ready=self._index is not None,
                indexed_docs=len(self._doc_store),
                indexed_chunks=self._chunk_count,
            )

    def _rebuild_index(self) -> None:
        """全量重建索引，确保同一 doc_id 语义为覆盖写入。"""
        documents: list[Document] = []
        for doc_id, item in self._doc_store.items():
            metadata = dict(item.metadata or {})
            metadata["doc_id"] = doc_id
            metadata["file_path"] = item.file_path
            documents.append(Document(text=item.content, metadata=metadata, id_=doc_id))

        nodes = self._splitter.get_nodes_from_documents(documents)
        for node in nodes:
            node.metadata["chunk_id"] = node.node_id

        self._chunk_count = len(nodes)
        if not nodes:
            self._index = None
            return

        self._index = VectorStoreIndex(nodes, embed_model=self._embed_model)

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
