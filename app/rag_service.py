from threading import RLock
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

from app.config import Settings
from app.local_pdf_reader import read_pdf_text
from app.models import BuildIndexRequest, HealthResponse, IndexDocument, QueryRequest, QueryResponse, RetrievedContext
from app.mysql_chunk_store import ChunkWriteItem, MySQLChunkStore
from app.qwen_embedding import QwenEmbedding


class IndexNotReadyError(RuntimeError):
    """索引未就绪异常。"""


class NoChunksAvailableError(RuntimeError):
    """没有可用于构建索引的 chunk。"""


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
        with self._lock:
            if self._index is None:
                raise IndexNotReadyError("索引尚未初始化，请先调用 /rag/index/build")

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
            indexed_docs = self._chunk_store.count_distinct_docs()
            indexed_chunks = self._chunk_store.count_chunks()
            return HealthResponse(
                status="ok",
                index_ready=self._index is not None,
                indexed_docs=indexed_docs,
                indexed_chunks=indexed_chunks,
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
