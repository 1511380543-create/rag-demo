"""评测指标单元测试，与 spec/testing/05_test_plan_and_cases.md §3.1 对齐。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.eval_metrics import compute_eval_metrics
from app.eval_store import EvalCaseRow


def test_rag_eval_metrics_unit_keyword_001() -> None:
    """备注：仅 expected_keywords 模式命中时 recall 恒为 0。"""
    case = EvalCaseRow(
        case_id="kw-001",
        query_text="测试查询",
        relevant_chunk_ids=None,
        expected_keywords=["11009"],
        top_k=None,
        enabled=True,
    )
    result = compute_eval_metrics(
        case=case,
        retrieved_chunk_ids=["chunk-a"],
        retrieved_texts=["默认通信端口 11009，心跳周期 30秒"],
    )
    assert result.hit == 1
    assert result.recall == 0.0
    assert result.mrr > 0


def test_rag_eval_metrics_unit_chunk_001() -> None:
    """备注：relevant_chunk_ids 模式下按 chunk 命中比例计算 recall。"""
    case = EvalCaseRow(
        case_id="chunk-001",
        query_text="测试查询",
        relevant_chunk_ids=["c1", "c2"],
        expected_keywords=None,
        top_k=None,
        enabled=True,
    )
    result = compute_eval_metrics(
        case=case,
        retrieved_chunk_ids=["c1", "other"],
        retrieved_texts=["无关文本", "无关文本"],
    )
    assert result.hit == 1
    assert result.recall == 0.5
    assert result.mrr == 1.0


def test_rag_eval_metrics_unit_dual_or_001() -> None:
    """备注：双标注时 chunk 未命中但 keyword 命中，仍判定为相关。"""
    case = EvalCaseRow(
        case_id="dual-001",
        query_text="测试查询",
        relevant_chunk_ids=["missing-chunk"],
        expected_keywords=["keyword"],
        top_k=None,
        enabled=True,
    )
    result = compute_eval_metrics(
        case=case,
        retrieved_chunk_ids=["other-chunk"],
        retrieved_texts=["text with keyword inside"],
    )
    assert result.hit == 1
    assert result.mrr > 0
