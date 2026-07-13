import json
from dataclasses import dataclass
from typing import Any

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.config import Settings


@dataclass
class ChunkRow:
    id: int
    doc_id: str
    chunk_index: int
    chunk_text: str
    metadata: dict[str, Any] | None


@dataclass
class ChunkWriteItem:
    chunk_index: int
    chunk_text: str
    metadata: dict[str, Any] | None


class MySQLChunkStore:
    """负责 chunks 表的读写操作。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def replace_document_chunks(self, doc_id: str, chunks: list[ChunkWriteItem]) -> int:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM rag_chunks WHERE doc_id = %s", (doc_id,))
                if chunks:
                    insert_sql = """
                        INSERT INTO rag_chunks (doc_id, chunk_index, chunk_text, metadata)
                        VALUES (%s, %s, %s, %s)
                    """
                    rows = [
                        (
                            doc_id,
                            item.chunk_index,
                            item.chunk_text,
                            self._to_json(item.metadata),
                        )
                        for item in chunks
                    ]
                    cursor.executemany(insert_sql, rows)
            conn.commit()
        return len(chunks)

    def fetch_chunks(self, doc_ids: list[str] | None) -> list[ChunkRow]:
        query = """
            SELECT id, doc_id, chunk_index, chunk_text, metadata
            FROM rag_chunks
        """
        params: tuple[Any, ...] = ()
        if doc_ids:
            placeholders = ", ".join(["%s"] * len(doc_ids))
            query = f"{query} WHERE doc_id IN ({placeholders})"
            params = tuple(doc_ids)
        query = f"{query} ORDER BY doc_id ASC, chunk_index ASC"

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()

        return [
            ChunkRow(
                id=int(row["id"]),
                doc_id=str(row["doc_id"]),
                chunk_index=int(row["chunk_index"]),
                chunk_text=str(row["chunk_text"]),
                metadata=self._from_json(row["metadata"]),
            )
            for row in rows
        ]

    def count_distinct_docs(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(DISTINCT doc_id) AS cnt FROM rag_chunks")
                row = cursor.fetchone()
        return int((row or {}).get("cnt", 0))

    def count_chunks(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM rag_chunks")
                row = cursor.fetchone()
        return int((row or {}).get("cnt", 0))

    def _connect(self) -> Connection:
        return pymysql.connect(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_user,
            password=self._settings.mysql_password,
            database=self._settings.mysql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    @staticmethod
    def _to_json(value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _from_json(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        return None
