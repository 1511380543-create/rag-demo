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
