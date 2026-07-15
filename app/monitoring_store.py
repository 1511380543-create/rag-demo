import math
from dataclasses import dataclass

from app.config import Settings
from app.mysql_connection import connect


@dataclass
class QueryLogItem:
    """单次查询监控记录的写入数据。"""

    query_text: str
    top_k: int
    filters_applied: bool
    embed_ms: int
    retrieve_ms: int
    total_ms: int
    retrieved_before_filter: int
    retrieved_after_filter: int
    is_empty_recall: bool
    top_score: float | None
    min_score_value: float | None
    avg_score: float | None
    error_code: str | None


@dataclass
class MetricsResult:
    """监控指标聚合结果。"""

    window_minutes: int | None
    total_queries: int
    empty_recall_count: int
    empty_recall_rate: float
    avg_total_ms: float
    p95_total_ms: float
    avg_embed_ms: float
    avg_retrieve_ms: float
    avg_top_score: float


class MonitoringStore:
    """负责 rag_query_logs 表的写入与聚合。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def insert_query_log(self, item: QueryLogItem) -> None:
        insert_sql = """
            INSERT INTO rag_query_logs (
                query_text, top_k, filters_applied, embed_ms, retrieve_ms, total_ms,
                retrieved_before_filter, retrieved_after_filter, is_empty_recall,
                top_score, min_score_value, avg_score, error_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            item.query_text,
            item.top_k,
            1 if item.filters_applied else 0,
            item.embed_ms,
            item.retrieve_ms,
            item.total_ms,
            item.retrieved_before_filter,
            item.retrieved_after_filter,
            1 if item.is_empty_recall else 0,
            item.top_score,
            item.min_score_value,
            item.avg_score,
            item.error_code,
        )
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(insert_sql, params)
            conn.commit()

    def aggregate_metrics(self, window_minutes: int | None) -> MetricsResult:
        query = """
            SELECT total_ms, embed_ms, retrieve_ms, top_score, is_empty_recall
            FROM rag_query_logs
        """
        params: tuple[int, ...] = ()
        if window_minutes is not None:
            query = f"{query} WHERE created_at >= NOW(3) - INTERVAL %s MINUTE"
            params = (window_minutes,)

        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()

        total_queries = len(rows)
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

        total_ms_values = [int(row["total_ms"]) for row in rows]
        embed_ms_values = [int(row["embed_ms"]) for row in rows]
        retrieve_ms_values = [int(row["retrieve_ms"]) for row in rows]
        top_scores = [float(row["top_score"]) for row in rows if row["top_score"] is not None]
        empty_recall_count = sum(1 for row in rows if int(row["is_empty_recall"]) == 1)

        return MetricsResult(
            window_minutes=window_minutes,
            total_queries=total_queries,
            empty_recall_count=empty_recall_count,
            empty_recall_rate=empty_recall_count / total_queries,
            avg_total_ms=sum(total_ms_values) / total_queries,
            p95_total_ms=self._percentile(total_ms_values, 0.95),
            avg_embed_ms=sum(embed_ms_values) / total_queries,
            avg_retrieve_ms=sum(retrieve_ms_values) / total_queries,
            avg_top_score=(sum(top_scores) / len(top_scores)) if top_scores else 0.0,
        )

    @staticmethod
    def _percentile(values: list[int], ratio: float) -> float:
        # 采用最近秩（nearest-rank）方法计算分位数，样本量较小时结果稳定。
        if not values:
            return 0.0
        ordered = sorted(values)
        rank = math.ceil(ratio * len(ordered))
        index = min(max(rank - 1, 0), len(ordered) - 1)
        return float(ordered[index])
