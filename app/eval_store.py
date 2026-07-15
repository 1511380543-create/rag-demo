from dataclasses import dataclass

from app.config import Settings
from app.mysql_connection import connect, from_json, to_json


@dataclass
class EvalCaseRow:
    """评测集样本。"""

    case_id: str
    query_text: str
    relevant_chunk_ids: list[str] | None
    expected_keywords: list[str] | None
    top_k: int | None
    enabled: bool


@dataclass
class EvalRunItemRow:
    """评测逐条明细写入数据。"""

    case_id: str
    query_text: str
    hit: int
    recall: float
    mrr: float
    latency_ms: int
    retrieved_chunk_ids: list[str]


@dataclass
class EvalRunSummaryRow:
    """评测轮次汇总。"""

    run_id: int
    dataset_size: int
    top_k: int
    avg_hit: float
    avg_recall: float
    avg_mrr: float
    avg_latency_ms: float
    note: str | None
    created_at: str


class EvalStore:
    """负责评测集与评测轮次相关表的读写。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def upsert_cases(self, cases: list[EvalCaseRow]) -> int:
        upsert_sql = """
            INSERT INTO rag_eval_dataset
                (case_id, query_text, relevant_chunk_ids, expected_keywords, top_k, enabled)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                query_text = VALUES(query_text),
                relevant_chunk_ids = VALUES(relevant_chunk_ids),
                expected_keywords = VALUES(expected_keywords),
                top_k = VALUES(top_k),
                enabled = VALUES(enabled)
        """
        rows = [
            (
                case.case_id,
                case.query_text,
                to_json(case.relevant_chunk_ids),
                to_json(case.expected_keywords),
                case.top_k,
                1 if case.enabled else 0,
            )
            for case in cases
        ]
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(upsert_sql, rows)
            conn.commit()
        return len(cases)

    def list_cases(self) -> list[EvalCaseRow]:
        query = """
            SELECT case_id, query_text, relevant_chunk_ids, expected_keywords, top_k, enabled
            FROM rag_eval_dataset
            ORDER BY case_id ASC
        """
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
        return [self._to_case_row(row) for row in rows]

    def fetch_cases(self, case_ids: list[str] | None) -> list[EvalCaseRow]:
        query = """
            SELECT case_id, query_text, relevant_chunk_ids, expected_keywords, top_k, enabled
            FROM rag_eval_dataset
        """
        params: tuple[str, ...] = ()
        if case_ids:
            placeholders = ", ".join(["%s"] * len(case_ids))
            query = f"{query} WHERE case_id IN ({placeholders})"
            params = tuple(case_ids)
        else:
            query = f"{query} WHERE enabled = 1"
        query = f"{query} ORDER BY case_id ASC"

        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [self._to_case_row(row) for row in rows]

    def insert_run(
        self,
        dataset_size: int,
        top_k: int,
        avg_hit: float,
        avg_recall: float,
        avg_mrr: float,
        avg_latency_ms: float,
        note: str | None,
    ) -> int:
        insert_sql = """
            INSERT INTO rag_eval_runs
                (dataset_size, top_k, avg_hit, avg_recall, avg_mrr, avg_latency_ms, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    insert_sql,
                    (dataset_size, top_k, avg_hit, avg_recall, avg_mrr, avg_latency_ms, note),
                )
                run_id = int(cursor.lastrowid)
            conn.commit()
        return run_id

    def insert_run_items(self, run_id: int, items: list[EvalRunItemRow]) -> None:
        if not items:
            return
        insert_sql = """
            INSERT INTO rag_eval_run_items
                (run_id, case_id, query_text, hit, recall, mrr, latency_ms, retrieved_chunk_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = [
            (
                run_id,
                item.case_id,
                item.query_text,
                item.hit,
                item.recall,
                item.mrr,
                item.latency_ms,
                to_json(item.retrieved_chunk_ids),
            )
            for item in items
        ]
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(insert_sql, rows)
            conn.commit()

    def list_runs(self, limit: int) -> list[EvalRunSummaryRow]:
        query = """
            SELECT id, dataset_size, top_k, avg_hit, avg_recall, avg_mrr, avg_latency_ms, note, created_at
            FROM rag_eval_runs
            ORDER BY id DESC
            LIMIT %s
        """
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
        return [
            EvalRunSummaryRow(
                run_id=int(row["id"]),
                dataset_size=int(row["dataset_size"]),
                top_k=int(row["top_k"]),
                avg_hit=float(row["avg_hit"]),
                avg_recall=float(row["avg_recall"]),
                avg_mrr=float(row["avg_mrr"]),
                avg_latency_ms=float(row["avg_latency_ms"]),
                note=row["note"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def count_runs(self) -> int:
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM rag_eval_runs")
                row = cursor.fetchone()
        return int((row or {}).get("cnt", 0))

    @staticmethod
    def _to_case_row(row: dict) -> EvalCaseRow:
        relevant = from_json(row["relevant_chunk_ids"])
        keywords = from_json(row["expected_keywords"])
        return EvalCaseRow(
            case_id=str(row["case_id"]),
            query_text=str(row["query_text"]),
            relevant_chunk_ids=list(relevant) if isinstance(relevant, list) else None,
            expected_keywords=list(keywords) if isinstance(keywords, list) else None,
            top_k=int(row["top_k"]) if row["top_k"] is not None else None,
            enabled=int(row["enabled"]) == 1,
        )
