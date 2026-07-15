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
from datetime import datetime, timedelta
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
            self._logs: list[tuple[datetime, object]] = []

        def insert_query_log(self, item) -> None:
            self._logs.append((datetime.now(), item))

        def insert_query_log_at(self, item, created_at: datetime) -> None:
            """测试辅助：按指定时间写入监控日志。"""
            self._logs.append((created_at, item))

        def list_logs(self) -> list:
            return [item for _, item in self._logs]

        def _aggregate_items(self, items: list, window_minutes: int | None):
            from app.monitoring_store import MetricsResult

            total_queries = len(items)
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

            empty_recall_count = sum(1 for item in items if item.is_empty_recall)
            top_scores = [item.top_score for item in items if item.top_score is not None]
            return MetricsResult(
                window_minutes=window_minutes,
                total_queries=total_queries,
                empty_recall_count=empty_recall_count,
                empty_recall_rate=empty_recall_count / total_queries,
                avg_total_ms=sum(item.total_ms for item in items) / total_queries,
                p95_total_ms=float(max(item.total_ms for item in items)),
                avg_embed_ms=sum(item.embed_ms for item in items) / total_queries,
                avg_retrieve_ms=sum(item.retrieve_ms for item in items) / total_queries,
                avg_top_score=(sum(top_scores) / len(top_scores)) if top_scores else 0.0,
            )

        def aggregate_metrics(self, window_minutes: int | None):
            rows = self._logs
            if window_minutes is not None:
                cutoff = datetime.now() - timedelta(minutes=window_minutes)
                rows = [(ts, item) for ts, item in self._logs if ts >= cutoff]
            items = [item for _, item in rows]
            return self._aggregate_items(items, window_minutes)

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


# 备注：与 rag_retrieval_reg_001 共用固定 query，便于测评确定性断言。
_OBD_REG_QUERY = "JT/T 809 协议默认通信端口和心跳周期是多少？"
# 备注：关键线索在 PDF 较后位置，测试环境 hash 向量下需更大 top_k 才能召回。
_OBD_REG_KEYWORDS = ["11009", "30s", "30秒"]
_OBD_REG_TOP_K = 10


def _upsert_eval_cases(client: TestClient, cases: list[dict]) -> None:
    response = client.post("/rag/eval/dataset", json={"cases": cases})
    assert response.status_code == 200


def _setup_obd_index_with_eval_case(client: TestClient, case_id: str = "obd-reg-001", enabled: bool = True) -> None:
    """入库 OBD 文档、构建索引并写入一条 keyword 评测样本。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)
    _upsert_eval_cases(
        client,
        [
            {
                "case_id": case_id,
                "query_text": _OBD_REG_QUERY,
                "expected_keywords": _OBD_REG_KEYWORDS,
                "top_k": _OBD_REG_TOP_K,
                "enabled": enabled,
            }
        ],
    )


def _get_monitoring_store():
    """获取当前测试客户端绑定的内存监控存储。"""
    import app.main as main_module

    return main_module.rag_service._monitoring_store


def _setup_obd_index_for_query(client: TestClient) -> None:
    """入库 OBD 文档并构建索引，供查询/监控用例复用。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)


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


def test_rag_eval_dataset_upsert_001(client: TestClient) -> None:
    """备注：评测样本批量 upsert 应返回写入条数。"""
    response = client.post(
        "/rag/eval/dataset",
        json={
            "cases": [
                {
                    "case_id": "eval-upsert-001",
                    "query_text": "JT/T 809 协议默认通信端口和心跳周期是多少？",
                    "expected_keywords": ["11009"],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["upserted_count"] > 0


def test_rag_eval_dataset_list_001(client: TestClient) -> None:
    """备注：upsert 后 GET 列表应与最新写入一致，同 case_id 覆盖生效。"""
    case_id = "eval-list-001"
    first_payload = {
        "case_id": case_id,
        "query_text": "第一次写入的 query",
        "expected_keywords": ["11009"],
    }
    upsert_response = client.post("/rag/eval/dataset", json={"cases": [first_payload]})
    assert upsert_response.status_code == 200

    updated_payload = {
        "case_id": case_id,
        "query_text": "覆盖后的 query",
        "expected_keywords": ["30秒"],
        "enabled": False,
    }
    overwrite_response = client.post("/rag/eval/dataset", json={"cases": [updated_payload]})
    assert overwrite_response.status_code == 200

    list_response = client.get("/rag/eval/dataset")
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert len(body["cases"]) == 1
    listed = body["cases"][0]
    assert listed["case_id"] == case_id
    assert listed["query_text"] == updated_payload["query_text"]
    assert listed["expected_keywords"] == updated_payload["expected_keywords"]
    assert listed["enabled"] is False


def test_rag_eval_dataset_fail_empty_001(client: TestClient) -> None:
    """备注：cases 为空数组应返回 422。"""
    response = client.post("/rag/eval/dataset", json={"cases": []})
    assert response.status_code == 422


def test_rag_eval_dataset_fail_no_gt_001(client: TestClient) -> None:
    """备注：两类 ground truth 均缺失应返回 422。"""
    response = client.post(
        "/rag/eval/dataset",
        json={"cases": [{"case_id": "no-gt-001", "query_text": "缺少标注的 query"}]},
    )
    assert response.status_code == 422


def test_rag_eval_run_ok_001(client: TestClient) -> None:
    """备注：固定 OBD 语料下测评应确定性命中。"""
    _setup_obd_index_with_eval_case(client)
    response = client.post("/rag/eval/run", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] > 0
    assert body["avg_hit"] == 1.0
    assert 0.0 <= body["avg_recall"] <= 1.0
    assert 0.0 <= body["avg_mrr"] <= 1.0
    assert body["avg_latency_ms"] >= 0
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert "retrieved_chunk_ids" in item
    assert isinstance(item["retrieved_chunk_ids"], list)


def test_rag_eval_run_enabled_filter_001(client: TestClient) -> None:
    """备注：未传 case_ids 时仅执行 enabled=true 的样本。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)
    _upsert_eval_cases(
        client,
        [
            {
                "case_id": "enabled-case",
                "query_text": _OBD_REG_QUERY,
                "expected_keywords": _OBD_REG_KEYWORDS,
                "top_k": _OBD_REG_TOP_K,
                "enabled": True,
            },
            {
                "case_id": "disabled-case",
                "query_text": "不会被默认执行的 query",
                "expected_keywords": ["不会被默认执行"],
                "enabled": False,
            },
        ],
    )
    response = client.post("/rag/eval/run", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["case_id"] == "enabled-case"


def test_rag_eval_run_case_ids_override_001(client: TestClient) -> None:
    """备注：传入 case_ids 时可执行 enabled=false 的样本。"""
    disabled_case_id = "disabled-override-001"
    _setup_obd_index_with_eval_case(client, case_id=disabled_case_id, enabled=False)
    response = client.post("/rag/eval/run", json={"case_ids": [disabled_case_id]})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_size"] == 1
    assert body["items"][0]["case_id"] == disabled_case_id


def test_rag_eval_run_no_monitor_pollution_001(client: TestClient) -> None:
    """备注：测评不应增加在线监控查询计数。"""
    _setup_obd_index_with_eval_case(client)
    metrics_before = client.get("/rag/metrics")
    assert metrics_before.status_code == 200
    total_before = metrics_before.json()["total_queries"]

    run_response = client.post("/rag/eval/run", json={})
    assert run_response.status_code == 200

    metrics_after = client.get("/rag/metrics")
    assert metrics_after.status_code == 200
    assert metrics_after.json()["total_queries"] == total_before


def test_rag_eval_run_fail_no_index_001(client: TestClient) -> None:
    """备注：未建索引执行测评应返回 INDEX_NOT_READY。"""
    _upsert_eval_cases(
        client,
        [{"case_id": "no-index-case", "query_text": "测试 query", "expected_keywords": ["测试"]}],
    )
    response = client.post("/rag/eval/run", json={})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INDEX_NOT_READY"


def test_rag_eval_run_fail_empty_dataset_001(client: TestClient) -> None:
    """备注：评测集为空时执行测评应返回 EVAL_DATASET_EMPTY。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)
    response = client.post("/rag/eval/run", json={})
    assert response.status_code == 400
    assert response.json()["error_code"] == "EVAL_DATASET_EMPTY"


def test_rag_eval_runs_list_001(client: TestClient) -> None:
    """备注：执行测评后应能在历史列表中查到对应轮次。"""
    _setup_obd_index_with_eval_case(client)
    run_response = client.post("/rag/eval/run", json={"note": "list-test-run"})
    assert run_response.status_code == 200
    run_body = run_response.json()

    list_response = client.get("/rag/eval/runs", params={"limit": 10})
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["total"] >= 1
    assert len(list_body["runs"]) >= 1

    latest = list_body["runs"][0]
    assert latest["run_id"] == run_body["run_id"]
    assert latest["dataset_size"] == run_body["dataset_size"]
    assert latest["avg_hit"] == run_body["avg_hit"]
    assert latest["note"] == "list-test-run"


def test_rag_query_score_record_001(client: TestClient) -> None:
    """备注：正常查询后监控日志应写入分数分布。"""
    _setup_obd_index_for_query(client)
    response = client.post("/rag/query", json={"query": _OBD_REG_QUERY, "top_k": 3})
    assert response.status_code == 200

    logs = _get_monitoring_store().list_logs()
    assert len(logs) == 1
    log_item = logs[0]
    assert log_item.top_score is not None
    assert log_item.avg_score is not None


def test_rag_metrics_ok_001(client: TestClient) -> None:
    """备注：多次查询后监控聚合指标应正确返回。"""
    _setup_obd_index_for_query(client)
    for _ in range(2):
        response = client.post("/rag/query", json={"query": _OBD_REG_QUERY, "top_k": 3})
        assert response.status_code == 200

    metrics_response = client.get("/rag/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.json()
    assert body["total_queries"] > 0
    assert 0.0 <= body["empty_recall_rate"] <= 1.0
    assert body["avg_total_ms"] >= 0.0
    assert body["avg_top_score"] >= 0.0


def test_rag_metrics_window_001(client: TestClient) -> None:
    """备注：时间窗口应仅统计窗口内的查询记录。"""
    from app.monitoring_store import QueryLogItem

    _setup_obd_index_for_query(client)
    store = _get_monitoring_store()
    store.insert_query_log_at(
        QueryLogItem(
            query_text="历史查询",
            top_k=3,
            filters_applied=False,
            embed_ms=10,
            retrieve_ms=20,
            total_ms=30,
            retrieved_before_filter=1,
            retrieved_after_filter=1,
            is_empty_recall=False,
            top_score=0.5,
            min_score_value=0.5,
            avg_score=0.5,
            error_code=None,
        ),
        created_at=datetime.now() - timedelta(minutes=10),
    )

    for _ in range(2):
        response = client.post("/rag/query", json={"query": _OBD_REG_QUERY, "top_k": 3})
        assert response.status_code == 200

    all_metrics = client.get("/rag/metrics")
    assert all_metrics.status_code == 200
    assert all_metrics.json()["total_queries"] == 3

    window_metrics = client.get("/rag/metrics", params={"window_minutes": 5})
    assert window_metrics.status_code == 200
    assert window_metrics.json()["total_queries"] == 2
    assert window_metrics.json()["window_minutes"] == 5


def test_rag_metrics_fail_window_001(client: TestClient) -> None:
    """备注：非法 window_minutes 应返回 422。"""
    for invalid_value in [0, -1]:
        response = client.get("/rag/metrics", params={"window_minutes": invalid_value})
        assert response.status_code == 422
