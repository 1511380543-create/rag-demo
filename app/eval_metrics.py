from dataclasses import dataclass

from app.eval_store import EvalCaseRow


@dataclass
class EvalMetricsResult:
    """单条评测样本的指标结果。"""

    hit: int
    recall: float
    mrr: float


def _is_chunk_relevant(chunk_id: str, relevant_chunk_ids: list[str]) -> bool:
    return chunk_id in set(relevant_chunk_ids)


def _is_text_relevant(chunk_text: str, expected_keywords: list[str]) -> bool:
    lowered = chunk_text.lower()
    return any(keyword.lower() in lowered for keyword in expected_keywords)


def _is_result_relevant(
    chunk_id: str,
    chunk_text: str,
    case: EvalCaseRow,
) -> bool:
    chunk_hit = False
    keyword_hit = False
    if case.relevant_chunk_ids:
        chunk_hit = _is_chunk_relevant(chunk_id, case.relevant_chunk_ids)
    if case.expected_keywords:
        keyword_hit = _is_text_relevant(chunk_text, case.expected_keywords)
    if case.relevant_chunk_ids and case.expected_keywords:
        return chunk_hit or keyword_hit
    if case.relevant_chunk_ids:
        return chunk_hit
    return keyword_hit


def compute_eval_metrics(
    case: EvalCaseRow,
    retrieved_chunk_ids: list[str],
    retrieved_texts: list[str],
) -> EvalMetricsResult:
    """计算单条评测样本的 hit/recall/mrr。"""
    relevant_flags = [
        _is_result_relevant(chunk_id, chunk_text, case)
        for chunk_id, chunk_text in zip(retrieved_chunk_ids, retrieved_texts, strict=True)
    ]

    hit = 1 if any(relevant_flags) else 0

    recall = 0.0
    if case.relevant_chunk_ids:
        relevant_set = set(case.relevant_chunk_ids)
        matched = sum(1 for chunk_id in retrieved_chunk_ids if chunk_id in relevant_set)
        recall = matched / len(relevant_set)

    mrr = 0.0
    for index, is_relevant in enumerate(relevant_flags, start=1):
        if is_relevant:
            mrr = 1.0 / index
            break

    return EvalMetricsResult(hit=hit, recall=recall, mrr=mrr)
