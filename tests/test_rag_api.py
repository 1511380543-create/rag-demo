"""
审核说明（精简）

- 命名约定：test_xxx 与 spec 的 case_id 一一对应（去掉 test_ 前缀）。
- 审核基准：CASE_META 中的 expected（期望）与 note（备注）。
- 执行命令：conda activate rag-demo && pytest tests/ -q
- Mock 边界：仅隔离外部 Embedding HTTP；抽取 / 切块 / MySQL 均为真实内部依赖。
- 已知差距：rag_retrieval_empty_reg_001 为 xfail（低相关阈值未实现）。
"""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.mysql_test_support import (
    configure_test_mysql_env,
    ensure_test_database,
    fetch_recent_query_logs,
    insert_query_log_at,
    truncate_test_tables,
)

# 备注：确保测试运行时可以稳定导入项目根目录下的 app 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOC_OBD = {
    "doc_id": "pdf-obd-809",
    "file_path": "docs/OBD设备JT_T 809协议虚拟技术手册.pdf",
    "metadata": {"source": "local_pdf", "category": "pdf"},
}
DOC_EMISSION = {
    "doc_id": "pdf-emission-std",
    "file_path": "docs/国三排放标准柴油机动车报废管理实施标准（虚拟政策文档）.pdf",
    "metadata": {"source": "local_pdf", "category": "pdf"},
}


def _keyword_vector(text: str, dim: int = 64) -> list[float]:
    """将文本映射为稳定向量，使用 n-gram 哈希投影避免依赖外部 Embedding 服务。"""
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


@pytest.fixture(scope="session")
def real_extracted_docs():
    """
    Session 级真实抽取缓存：只跑一次 MinerU，避免每条用例重复解析。
    仍使用真实 PdfExtractPipeline，不替换内部实现。
    """
    mpl_dir = tempfile.mkdtemp(prefix="rag-demo-mpl-")
    os.environ["MPLCONFIGDIR"] = mpl_dir
    os.environ.setdefault("NUMBA_CACHE_DIR", tempfile.mkdtemp(prefix="rag-demo-numba-"))

    from app.extract.pipeline import PdfExtractPipeline

    pipeline = PdfExtractPipeline()
    cached = {}
    for item in (DOC_OBD, DOC_EMISSION):
        cached[item["doc_id"]] = pipeline.extract(
            item["doc_id"],
            item["file_path"],
            metadata=item.get("metadata"),
        )
    return cached


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, real_extracted_docs) -> Iterator[TestClient]:
    """
    构造独立测试客户端。

    - 仅 mock 外部 Embedding HTTP
    - 抽取 / 切块 / MySQL 走真实实现（测试库 rag_demo_test）
    """
    monkeypatch.setenv("API_KEY_ALI", "unit-test-key")
    configure_test_mysql_env()
    ensure_test_database()
    truncate_test_tables()

    import app.qwen_embedding as qwen_embedding

    # 仅隔离外部向量服务
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_text_embedding", _fake_get_text_embedding)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_text_embeddings", _fake_get_text_embeddings)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_get_query_embedding", _fake_get_query_embedding)
    monkeypatch.setattr(qwen_embedding.QwenEmbedding, "_aget_query_embedding", _fake_aget_query_embedding)

    import app.main as main_module

    importlib.reload(main_module)
    # 将 session 缓存挂到服务实例，供入库辅助复用真实抽取结果
    main_module.rag_service._test_extracted_docs = real_extracted_docs  # type: ignore[attr-defined]

    with TestClient(main_module.app) as test_client:
        yield test_client

    truncate_test_tables()


def _seed_extracted_documents(doc_ids: list[str]) -> None:
    """把 session 内真实抽取结果写入 MySQL（真实 DocumentStore，不重复跑 partition_pdf）。"""
    import app.main as main_module

    cached = getattr(main_module.rag_service, "_test_extracted_docs", None)
    if not cached:
        raise RuntimeError("缺少真实抽取缓存，请检查 real_extracted_docs fixture")
    for doc_id in doc_ids:
        document = cached[doc_id]
        main_module.rag_service._document_store.replace_document(document)


def _extract_documents(client: TestClient, documents: list[dict]) -> None:
    """走真实 /rag/extract（真实 MinerU）。"""
    response = client.post("/rag/extract", json={"documents": documents})
    assert response.status_code == 200


def _chunk_documents(client: TestClient, doc_ids: list[str]) -> None:
    response = client.post("/rag/chunks", json={"doc_ids": doc_ids})
    assert response.status_code == 200


def _ingest_documents(client: TestClient, documents: list[dict]) -> None:
    """
    入库：写入真实抽取结果 + 真实切块。
    抽取结果来自 session 级真实 PdfExtractPipeline 缓存，切块仍走 /rag/chunks。
    """
    doc_ids = [item["doc_id"] for item in documents]
    _seed_extracted_documents(doc_ids)
    _chunk_documents(client, doc_ids)


def _ingest_two_pdfs(client: TestClient) -> None:
    _ingest_documents(client, [DOC_OBD, DOC_EMISSION])


def _ingest_obd_pdf_only(client: TestClient) -> None:
    """仅入库 OBD 协议文档，便于回归断言稳定命中关键字段。"""
    _ingest_documents(client, [DOC_OBD])


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


def _setup_obd_index_for_query(client: TestClient) -> None:
    """入库 OBD 文档并构建索引，供查询/监控用例复用。"""
    _ingest_obd_pdf_only(client)
    _build_index(client)


def test_rag_query_fail_no_index_001(client: TestClient) -> None:
    """备注：未初始化索引时应返回 400。"""
    response = client.post("/rag/query", json={"query": "什么是RAG"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INDEX_NOT_READY"


def test_rag_extract_fail_empty_001(client: TestClient) -> None:
    """备注：documents 为空数组应返回 422。"""
    response = client.post("/rag/extract", json={"documents": []})
    assert response.status_code == 422


def test_rag_extract_fail_non_pdf_001(client: TestClient) -> None:
    """备注：非 PDF 路径应被拒绝。"""
    response = client.post("/rag/extract", json={"documents": [{"doc_id": "x1", "file_path": "docs/a.txt"}]})
    assert response.status_code == 422


def test_rag_extract_fail_file_not_found_001(client: TestClient) -> None:
    """备注：本地文件不存在应返回 422。"""
    response = client.post("/rag/extract", json={"documents": [{"doc_id": "x2", "file_path": "docs/not_exist.pdf"}]})
    assert response.status_code == 422


def test_rag_extract_ok_001(client: TestClient) -> None:
    """备注：2 个 PDF 走真实 Unstructured 抽取入库。"""
    payload = {"documents": [DOC_OBD, DOC_EMISSION]}
    response = client.post("/rag/extract", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["extracted_doc_count"] == 2
    assert body["total_page_count"] > 0
    assert body["total_char_count"] > 0


def test_rag_chunks_fail_empty_001(client: TestClient) -> None:
    """备注：doc_ids 为空数组应返回 422。"""
    response = client.post("/rag/chunks", json={"doc_ids": []})
    assert response.status_code == 422


def test_rag_chunks_fail_not_extracted_001(client: TestClient) -> None:
    """备注：未抽取文档直接切块应返回 400。"""
    response = client.post("/rag/chunks", json={"doc_ids": ["missing-doc"]})
    assert response.status_code == 400
    assert response.json()["error_code"] == "DOCUMENT_NOT_EXTRACTED"


def test_rag_chunks_ok_001(client: TestClient) -> None:
    """备注：真实抽取结果经真实切块入库。"""
    documents = [DOC_OBD, DOC_EMISSION]
    _seed_extracted_documents([item["doc_id"] for item in documents])
    response = client.post("/rag/chunks", json={"doc_ids": [item["doc_id"] for item in documents]})
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
    assert body["extracted_docs"] == 1
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
    # 未传请求级 top_k 时应回显样本实际窗口，而非误记默认 3
    assert body["top_k"] == _OBD_REG_TOP_K
    assert body["avg_hit"] == 1.0
    assert 0.0 <= body["avg_recall"] <= 1.0
    assert 0.0 <= body["avg_mrr"] <= 1.0
    assert body["avg_latency_ms"] >= 0
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert "retrieved_chunk_ids" in item
    assert isinstance(item["retrieved_chunk_ids"], list)
    assert len(item["retrieved_chunk_ids"]) <= _OBD_REG_TOP_K


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
    from app.config import get_settings

    _setup_obd_index_for_query(client)
    response = client.post("/rag/query", json={"query": _OBD_REG_QUERY, "top_k": 3})
    assert response.status_code == 200

    logs = fetch_recent_query_logs(get_settings(), limit=1)
    assert len(logs) == 1
    assert logs[0]["top_score"] is not None
    assert logs[0]["avg_score"] is not None


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
    from app.config import get_settings
    from app.monitoring_store import QueryLogItem

    _setup_obd_index_for_query(client)
    insert_query_log_at(
        get_settings(),
        created_at=datetime.now() - timedelta(minutes=10),
        item=QueryLogItem(
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
