from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class AuditMeta:
    expected: str
    note: str


CASE_AUDIT_META: dict[str, AuditMeta] = {
    "rag_query_fail_no_index_001": AuditMeta("400 + INDEX_NOT_READY", "未建索引直接查询应拒绝"),
    "rag_chunks_fail_empty_001": AuditMeta("422", "documents 为空数组"),
    "rag_chunks_fail_non_pdf_001": AuditMeta("422", "仅支持 PDF 路径"),
    "rag_chunks_fail_file_not_found_001": AuditMeta("422", "本地文件不存在"),
    "rag_chunks_ok_001": AuditMeta("200 + stored_doc_count=2 + stored_chunk_count>0", "双文档切分入库成功"),
    "rag_index_build_fail_no_chunks_001": AuditMeta("400 + NO_CHUNKS_FOR_INDEX", "无 chunk 时构建应拒绝"),
    "rag_index_build_fail_invalid_doc_ids_001": AuditMeta("422", "doc_ids 含空字符串"),
    "rag_index_build_ok_001": AuditMeta("200 + indexed_doc_count=2 + indexed_chunk_count>0", "索引构建成功"),
    "rag_query_fail_empty_001": AuditMeta("422", "query 为空白"),
    "rag_query_fail_topk_001": AuditMeta("422", "top_k 小于 1"),
    "rag_health_ok_001": AuditMeta("200 + status=ok + indexed_docs/chunks", "健康检查可用"),
    "rag_query_ok_001": AuditMeta("200 + contexts<=3", "默认 top_k 查询成功"),
    "rag_query_ok_topk_001": AuditMeta("200 + contexts<=5", "自定义 top_k 查询成功"),
    "rag_retrieval_reg_001": AuditMeta("200 + 命中关键线索", "回归查询命中证据片段"),
    "rag_retrieval_empty_reg_001": AuditMeta("200 + contexts=[]", "当前为已知差距（低相关阈值未实现）"),
    "rag_query_score_record_001": AuditMeta("top_score/avg_score 已写入", "查询后监控日志记录分数"),
    "rag_metrics_ok_001": AuditMeta("200 + total_queries>0", "监控指标聚合正确"),
    "rag_metrics_window_001": AuditMeta("200 + 窗口内统计", "时间窗口过滤生效"),
    "rag_metrics_fail_window_001": AuditMeta("422", "非法 window_minutes"),
    "rag_eval_dataset_upsert_001": AuditMeta("200 + upserted_count>0", "评测样本批量 upsert"),
    "rag_eval_dataset_list_001": AuditMeta("200 + 列表与 upsert 一致", "GET 读路径与覆盖更新"),
    "rag_eval_dataset_fail_empty_001": AuditMeta("422", "cases 为空数组"),
    "rag_eval_dataset_fail_no_gt_001": AuditMeta("422", "缺少 ground truth"),
    "rag_eval_run_ok_001": AuditMeta("200 + avg_hit=1.0", "固定 OBD 语料确定性测评"),
    "rag_eval_run_enabled_filter_001": AuditMeta("200 + dataset_size=1", "enabled=false 默认不参与"),
    "rag_eval_run_case_ids_override_001": AuditMeta("200 + dataset_size=1", "case_ids 忽略 enabled"),
    "rag_eval_run_no_monitor_pollution_001": AuditMeta("total_queries 不变", "测评不写入监控日志"),
    "rag_eval_run_fail_no_index_001": AuditMeta("400 + INDEX_NOT_READY", "未建索引执行测评"),
    "rag_eval_run_fail_empty_dataset_001": AuditMeta("400 + EVAL_DATASET_EMPTY", "空评测集执行测评"),
    "rag_eval_runs_list_001": AuditMeta("200 + 历史轮次列表", "评测历史查询"),
    "rag_eval_metrics_unit_keyword_001": AuditMeta("hit=1 recall=0", "仅 keyword 指标计算"),
    "rag_eval_metrics_unit_chunk_001": AuditMeta("hit=1 recall=0.5 mrr=1", "仅 chunk 指标计算"),
    "rag_eval_metrics_unit_dual_or_001": AuditMeta("hit=1 mrr>0", "双标注 OR 规则"),
    "rag_eval_metrics_unit_keyword_all_001": AuditMeta("部分命中 hit=0", "keyword_match_mode=all"),
}


def _case_id_from_nodeid(nodeid: str) -> str | None:
    # 示例: tests/test_rag_api.py::test_rag_query_ok_001
    test_name = nodeid.rsplit("::", 1)[-1]
    if not test_name.startswith("test_"):
        return None
    return test_name.replace("test_", "", 1)


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    rows: list[tuple[str, str, str, str]] = []

    case_outcomes: dict[str, str] = {}

    for rep in terminalreporter.getreports("passed"):
        case_id = _case_id_from_nodeid(rep.nodeid)
        if case_id:
            case_outcomes[case_id] = "通过"

    for rep in terminalreporter.getreports("failed"):
        case_id = _case_id_from_nodeid(rep.nodeid)
        if case_id:
            case_outcomes[case_id] = "失败"

    for rep in terminalreporter.getreports("xfailed"):
        case_id = _case_id_from_nodeid(rep.nodeid)
        if case_id:
            case_outcomes[case_id] = "预期失败"

    # 对没有执行的用例也保留，方便审核是否遗漏。
    all_case_ids = sorted(CASE_AUDIT_META.keys())
    for case_id in all_case_ids:
        meta = CASE_AUDIT_META[case_id]
        outcome = case_outcomes.get(case_id, "未执行")
        rows.append((case_id, meta.expected, outcome, meta.note))

    terminalreporter.write_sep("-", "用例审核表（期望值 vs 实际结果）")
    terminalreporter.write_line("| case_id | 期望值 | 实际结果 | 备注 |")
    terminalreporter.write_line("|---|---|---|---|")
    for case_id, expected, outcome, note in rows:
        terminalreporter.write_line(f"| {case_id} | {expected} | {outcome} | {note} |")

    passed = sum(1 for _, _, outcome, _ in rows if outcome == "通过")
    failed = sum(1 for _, _, outcome, _ in rows if outcome == "失败")
    xfailed = sum(1 for _, _, outcome, _ in rows if outcome == "预期失败")
    not_run = sum(1 for _, _, outcome, _ in rows if outcome == "未执行")
    total = len(rows)
    terminalreporter.write_line(
        f"审核汇总: total={total}, 通过={passed}, 失败={failed}, 预期失败={xfailed}, 未执行={not_run}"
    )
