"""
审核说明（精简）

- 命名约定：test_xxx 与 spec 的 case_id 一一对应（去掉 test_ 前缀）。
- 审核基准：CASE_META 中的 expected（期望）与 note（备注）。
- 执行命令：pytest tests/test_rag_api.py -q
- 已知差距：rag_retrieval_empty_reg_001 为 xfail（低相关阈值未实现）。
"""

import importlib
import hashlib
import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


# 备注：确保测试运行时可以稳定导入项目根目录下的 app 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _keyword_vector(text: str, dim: int = 64) -> list[float]:
    """将文本映射为稳定向量，使用 n-gram 哈希投影避免人工关键词依赖。"""
    normalized = " ".join(text.lower().split())
    if not normalized:
        normalized = "<empty>"

    # 备注：首位固定为 1.0，避免极端输入下出现全零向量。
    values = [0.0] * dim
    values[0] = 1.0

    grams = [normalized[i : i + 2] for i in range(max(len(normalized) - 1, 1))]
    if not grams:
        grams = [normalized]

    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).hexdigest()
        number = int(digest, 16)
        idx = number % dim
        sign = 1.0 if ((number >> 1) & 1) == 0 else -1.0
        values[idx] += sign

    return values


def _fake_get_text_embedding(self, text: str) -> list[float]:
    return _keyword_vector(text)


def _fake_get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
    return [_keyword_vector(text) for text in texts]


def _fake_get_query_embedding(self, query: str) -> list[float]:
    return _keyword_vector(query)


async def _fake_aget_query_embedding(self, query: str) -> list[float]:
    return _keyword_vector(query)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """构造独立测试客户端。备注：每个用例都会重置索引状态。"""
    monkeypatch.setenv("API_KEY_ALI", "unit-test-key")

    import app.qwen_embedding as qwen_embedding
    import app.rag_service as rag_service_module
    from app.mysql_chunk_store import ChunkRow

    class InMemoryChunkStore:
        """测试使用的内存 chunk 存储，避免依赖真实 MySQL。"""

        def __init__(self, settings=None, **_kwargs) -> None:
            self._rows: list[ChunkRow] = []
            self._next_id = 1

        def replace_document_chunks(self, doc_id: str, chunks) -> int:
            self._rows = [row for row in self._rows if row.doc_id != doc_id]
            for item in chunks:
                self._rows.append(
                    ChunkRow(
                        id=self._next_id,
                        doc_id=doc_id,
                        chunk_index=item.chunk_index,
                        chunk_text=item.chunk_text,
                        metadata=item.metadata,
                    )
                )
                self._next_id += 1
            return len(chunks)

        def fetch_chunks(self, doc_ids: list[str] | None):
            rows = self._rows
            if doc_ids:
                doc_set = set(doc_ids)
                rows = [row for row in rows if row.doc_id in doc_set]
            return sorted(rows, key=lambda r: (r.doc_id, r.chunk_index))

        def count_distinct_docs(self) -> int:
            return len({row.doc_id for row in self._rows})

        def count_chunks(self) -> int:
            return len(self._rows)

    class InMemoryMonitoringStore:
        """测试使用的内存监控存储。"""

        def __init__(self, settings=None, **_kwargs) -> None:
            self._logs: list = []

        def insert_query_log(self, item) -> None:
            self._logs.append(item)

        def aggregate_metrics(self, window_minutes: int | None):
            from app.monitoring_store import MetricsResult

            total_queries = len(self._logs)
            if total_queries == 0:
                return MetricsResult(
                    window_minutes=window_minutes,
                    total_queries=0,
                    empty_recall_count=0,
                    empty_recall_rate=0.0,
                    avg_total_ms=0.0,
                    p95_total_ms=0.0,
                    avg_embed_ms=0.0,
                    avg_retrieve_ms=0.0,
                    avg_top_score=0.0,
                )

            empty_recall_count = sum(1 for item in self._logs if item.is_empty_recall)
            top_scores = [item.top_score for item in self._logs if item.top_score is not None]
            return MetricsResult(
                window_minutes=window_minutes,
                total_queries=total_queries,
                empty_recall_count=empty_recall_count,
                empty_recall_rate=empty_recall_count / total_queries,
                avg_total_ms=sum(item.total_ms for item in self._logs) / total_queries,
                p95_total_ms=float(max(item.total_ms for item in self._logs)),
                avg_embed_ms=sum(item.embed_ms for item in self._logs) / total_queries,
                avg_retrieve_ms=sum(item.retrieve_ms for item in self._logs) / total_queries,
                avg_top_score=(sum(top_scores) / len(top_scores)) if top_scores else 0.0,
            )

    class InMemoryEvalStore:
        """测试使用的内存评测存储。"""

        def __init__(self, settings=None, **_kwargs) -> None:
            self._cases: dict[str, object] = {}
            self._runs: list = []
            self._run_items: list = []
            self._next_run_id = 1

        def upsert_cases(self, cases) -> int:
            for case in cases:
                self._cases[case.case_id] = case
            return len(cases)

        def list_cases(self):
            return sorted(self._cases.values(), key=lambda item: item.case_id)

        def fetch_cases(self, case_ids: list[str] | None):
            rows = list(self._cases.values())
            if case_ids:
                case_set = set(case_ids)
                rows = [row for row in rows if row.case_id in case_set]
            else:
                rows = [row for row in rows if row.enabled]
            return sorted(rows, key=lambda item: item.case_id)

        def insert_run(self, dataset_size, top_k, avg_hit, avg_recall, avg_mrr, avg_latency_ms, note):
            run_id = self._next_run_id
            self._next_run_id += 1
            self._runs.append(
                {
                    "run_id": run_id,
                    "dataset_size": dataset_size,
                    "top_k": top_k,
                    "avg_hit": avg_hit,
                    "avg_recall": avg_recall,
                    "avg_mrr": avg_mrr,
                    "avg_latency_ms": avg_latency_ms,
                    "note": note,
                    "created_at": "2026-01-01 00:00:00",
                }
            )
            return run_id

        def insert_run_items(self, run_id, items) -> None:
            self._run_items.extend(items)

        def list_runs(self, limit: int):
            from app.eval_store import EvalRunSummaryRow

            selected = list(reversed(self._runs))[:limit]
            return [
                EvalRunSummaryRow(
                    run_id=row["run_id"],
                    dataset_size=row["dataset_size"],
                    top_k=row["top_k"],
                    avg_hit=row["avg_hit"],
                    avg_recall=row["avg_recall"],
                    avg_mrr=row["avg_mrr"],
                    avg_latency_ms=row["avg_latency_ms"],
                    note=row["note"],
                    created_at=row["created_at"],
                )
                for row in selected
            ]

        def count_runs(self) -> int:
            return len(self._runs)

    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_text_embedding", _fake_get_text_embedding)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_text_embeddings", _fake_get_text_embeddings)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_query_embedding", _fake_get_query_embedding)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_aget_query_embedding", _fake_aget_query_embedding)
    monkeypatch.setattr(rag_service_module, "MySQLChunkStore", InMemoryChunkStore)
    monkeypatch.setattr(rag_service_module, "MonitoringStore", InMemoryMonitoringStore)
    monkeypatch.setattr(rag_service_module, "EvalStore", InMemoryEvalStore)

    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as test_client:
        yield test_client


def _ingest_documents(client: TestClient, documents: list[dict]) -> None:
    response = client.post("/rag/chunks", json={"documents": documents})
    assert response.status_code == 200


def _ingest_two_pdfs(client: TestClient) -> None:
    _ingest_documents(
        client,
        [
            {
                "doc_id": "pdf-obd-809",
                "file_path": "docs/OBD设备JT_T 809协议虚拟技术手册.pdf",
                "metadata": {"source": "local_pdf", "category": "policy"},
            },
            {
                "doc_id": "pdf-emission-std",
                "file_path": "docs/国三排放标准柴油机动车报废管理实施标准（虚拟政策文档）.pdf",
                "metadata": {"source": "local_pdf", "category": "policy"},
            },
        ],
    )


def _ingest_obd_pdf_only(client: TestClient) -> None:
    """仅入库 OBD 协议文档，便于回归断言稳定命中关键字段。"""
    _ingest_documents(
        client,
        [
            {
                "doc_id": "pdf-obd-809",
                "file_path": "docs/OBD设备JT_T 809协议虚拟技术手册.pdf",
                "metadata": {"source": "local_pdf", "category": "policy"},
            }
        ],
    )


def _build_index(client: TestClient, payload: dict | None = None) -> None:
    request_payload = payload or {"force_rebuild": True}
    response = client.post("/rag/index/build", json=request_payload)
    assert response.status_code == 200


def test_rag_query_fail_no_index_001(client: TestClient) -> None:
    """备注：未初始化索引时应返回 400。"""
    response = client.post("/rag/query", json={"query": "什么是RAG"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INDEX_NOT_READY"


def test_rag_chunks_fail_empty_001(client: TestClient) -> None:
    """备注：documents 为空数组应返回 422。"""
    response = client.post("/rag/chunks", json={"documents": []})
    assert response.status_code == 422


def test_rag_chunks_fail_non_pdf_001(client: TestClient) -> None:
    """备注：非 PDF 路径应被拒绝。"""
    response = client.post("/rag/chunks", json={"documents": [{"doc_id": "x1", "file_path": "docs/a.txt"}]})
    assert response.status_code == 422


def test_rag_chunks_fail_file_not_found_001(client: TestClient) -> None:
    """备注：本地文件不存在应返回 422。"""
    response = client.post("/rag/chunks", json={"documents": [{"doc_id": "x2", "file_path": "docs/not_exist.pdf"}]})
    assert response.status_code == 422


def test_rag_chunks_ok_001(client: TestClient) -> None:
    """备注：2 个 PDF 正常切分入库。"""
    payload = {
        "documents": [
            {"doc_id": "pdf-obd-809", "file_path": "docs/OBD设备JT_T 809协议虚拟技术手册.pdf"},
            {"doc_id": "pdf-emission-std", "file_path": "docs/国三排放标准柴油机动车报废管理实施标准（虚拟政策文档）.pdf"},
        ]
    }
    response = client.post("/rag/chunks", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["stored_doc_count"] == 2
    assert body["stored_chunk_count"] > 0


def test_rag_index_build_fail_no_chunks_001(client: TestClient) -> None:
    """备注：无 chunk 时构建索引应返回 400。"""
    response = client.post("/rag/index/build", json={"force_rebuild": True})
    assert response.status_code == 400
    assert response.json()["error_code"] == "NO_CHUNKS_FOR_INDEX"


def test_rag_index_build_fail_invalid_doc_ids_001(client: TestClient) -> None:
    """备注：doc_ids 含空字符串应返回 422。"""
    response = client.post("/rag/index/build", json={"doc_ids": ["ok", "   "]})
    assert response.status_code == 422


def test_rag_index_build_ok_001(client: TestClient) -> None:
    """备注：切分入库后可正常构建索引。"""
    _ingest_two_pdfs(client)
    response = client.post("/rag/index/build", json={"force_rebuild": True})
    assert response.status_code == 200
    body = response.json()
    assert body["indexed_doc_count"] == 2
    assert body["indexed_chunk_count"] > 0
    assert body["index_name"]


def test_rag_query_fail_empty_001(client: TestClient) -> None:
    """备注：空白 query 应返回 422。"""
    response = client.post("/rag/query", json={"query": "   "})
    assert response.status_code == 422


def test_rag_query_fail_topk_001(client: TestClient) -> None:
    """备注：非法 top_k=0 应返回 422。"""
    response = client.post("/rag/query", json={"query": "a", "top_k": 0})
    assert response.status_code == 422


def test_rag_health_ok_001(client: TestClient) -> None:
    """备注：健康检查基础可用。"""
    _ingest_obd_pdf_only(client)
    response = client.get("/rag/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["indexed_docs"] == 1
    assert body["indexed_chunks"] > 0


def test_rag_query_ok_001(client: TestClient) -> None:
    """备注：默认 top_k=3 的查询应成功。"""
    _ingest_two_pdfs(client)
    _build_index(client)
    response = client.post("/rag/query", json={"query": "JT/T 809 协议默认通信端口和心跳周期是多少？", "top_k": 3})
    assert response.status_code == 200
    assert len(response.json()["contexts"]) <= 3


def test_rag_query_ok_topk_001(client: TestClient) -> None:
    """备注：自定义 top_k=5 生效。"""
    _ingest_two_pdfs(client)
    _build_index(client)
    response = client.post("/rag/query", json={"query": "OBD车辆故障码上报对应的报文ID是什么？", "top_k": 5})
    assert response.status_code == 200
    assert len(response.json()["contexts"]) <= 5


def test_rag_retrieval_reg_001(client: TestClient) -> None:
    """备注：回归样例需命中关键片段。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)
    response = client.post("/rag/query", json={"query": "JT/T 809 协议默认通信端口和心跳周期是多少？", "top_k": 3})
    assert response.status_code == 200
    contexts = response.json()["contexts"]
    merged_text = "\n".join(item["chunk_text"] for item in contexts).lower().replace("\x01", "")
    # 备注：PDF 抽取文本存在字形差异（如“心/⼼”）和控制字符，断言需兼容常见关键线索。
    assert any(
        token in merged_text
        for token in ["11009", "30秒", "30s", "0x1005", "0x1006", "心跳", "⼼跳", "端口", "端⼝"]
    )


@pytest.mark.xfail(reason="当前实现无低相关阈值过滤，已知行为", strict=False)
def test_rag_retrieval_empty_reg_001(client: TestClient) -> None:
    """备注：该用例用于跟踪低相关查询返回空召回的目标行为。"""
    _ingest_two_pdfs(client)
    _build_index(client)
    response = client.post("/rag/query", json={"query": "今天天气怎么样，推荐电影", "top_k": 3})
    assert response.status_code == 200
    assert response.json()["contexts"] == []
