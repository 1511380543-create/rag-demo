"""测试用 MySQL 基建：独立库 rag_demo_test，不污染业务库 rag_demo。"""

from __future__ import annotations

import os
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings, get_settings

TEST_DATABASE = "rag_demo_test"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "spec" / "sql" / "mysql_schema.sql"

TABLES = (
    "rag_eval_run_items",
    "rag_eval_runs",
    "rag_eval_dataset",
    "rag_eval_chunk_snapshot_items",
    "rag_eval_chunk_freezes",
    "rag_query_logs",
    "rag_chunks",
    "rag_documents",
)


def configure_test_mysql_env() -> None:
    """将进程指向测试库，并清理 Settings 缓存。"""
    os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
    os.environ.setdefault("MYSQL_PORT", "3306")
    os.environ.setdefault("MYSQL_USER", "root")
    os.environ.setdefault("MYSQL_PASSWORD", "root")
    os.environ["MYSQL_DATABASE"] = TEST_DATABASE
    get_settings.cache_clear()


def _base_connect(*, database: str | None = None):
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "root"),
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def ensure_test_database() -> None:
    """创建测试库并按 schema 建表（幂等）。"""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # 将业务库名替换为测试库，避免误写 rag_demo
    schema_sql = schema_sql.replace("`rag_demo`", f"`{TEST_DATABASE}`")
    schema_sql = schema_sql.replace("USE `rag_demo`;", f"USE `{TEST_DATABASE}`;")

    with _base_connect() as conn:
        with conn.cursor() as cursor:
            for statement in _split_sql_statements(schema_sql):
                cursor.execute(statement)
            # 旧测试库可能缺第二轮新增列，补齐后再跑用例
            _ensure_column(
                cursor,
                TEST_DATABASE,
                "rag_eval_dataset",
                "expect_hit",
                "TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '期望命中:1正样本0负样本'",
            )
            _ensure_column(
                cursor,
                TEST_DATABASE,
                "rag_eval_dataset",
                "filters",
                "JSON NULL COMMENT '样本级元数据过滤'",
            )


def _ensure_column(cursor, database: str, table: str, column: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (database, table, column),
    )
    row = cursor.fetchone() or {}
    if int(row.get("cnt", 0)) == 0:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def truncate_test_tables(settings: Settings | None = None) -> None:
    """清空测试库业务表，保证用例隔离。"""
    cfg = settings or get_settings()
    with _base_connect(database=cfg.mysql_database) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            for table in TABLES:
                cursor.execute(f"TRUNCATE TABLE `{table}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")


def insert_query_log_at(settings: Settings, *, created_at, item) -> None:
    """按指定时间写入监控日志（仅测试使用，验证时间窗口聚合）。"""
    sql = """
        INSERT INTO rag_query_logs (
            query_text, top_k, filters_applied, embed_ms, retrieve_ms, total_ms,
            retrieved_before_filter, retrieved_after_filter, is_empty_recall,
            top_score, min_score_value, avg_score, error_code, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        created_at,
    )
    with _base_connect(database=settings.mysql_database) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)


def fetch_recent_query_logs(settings: Settings, limit: int = 10) -> list[dict]:
    """读取最近监控日志，供断言分数写入。"""
    sql = """
        SELECT id, query_text, top_score, avg_score, error_code, created_at
        FROM rag_query_logs
        ORDER BY id DESC
        LIMIT %s
    """
    with _base_connect(database=settings.mysql_database) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (limit,))
            return list(cursor.fetchall())


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";")
            if statement:
                statements.append(statement)
            buffer = []
    if buffer:
        statement = "\n".join(buffer).strip().rstrip(";")
        if statement:
            statements.append(statement)
    return statements
