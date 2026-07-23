#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切块冻结快照：从现行 rag_chunks 手动打版。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.config import Settings
from app.mysql_chunk_store import ChunkRow, MySQLChunkStore
from app.mysql_connection import connect


@dataclass
class FreezeSummaryRow:
    """冻结版汇总。"""

    freeze_id: int
    freeze_label: str
    note: str | None
    pipeline_version: str | None
    doc_count: int
    chunk_count: int
    created_at: str


@dataclass
class FreezeDetailRow(FreezeSummaryRow):
    """冻结版详情（含样本 chunk）。"""

    sample_items: list[dict]


class NoChunksForFreezeError(RuntimeError):
    """现行 chunks 为空，无法打版。"""


class DuplicateFreezeLabelError(RuntimeError):
    """freeze_label 已存在。"""


class EvalFreezeStore:
    """负责 rag_eval_chunk_freezes / snapshot_items 读写。"""

    def __init__(self, settings: Settings, chunk_store: MySQLChunkStore | None = None) -> None:
        self._settings = settings
        self._chunk_store = chunk_store or MySQLChunkStore(settings)

    def create_freeze(
        self,
        *,
        freeze_label: str,
        note: str | None = None,
        pipeline_version: str | None = None,
        doc_ids: list[str] | None = None,
    ) -> FreezeSummaryRow:
        label = freeze_label.strip()
        if not label:
            raise ValueError("freeze_label 不能为空")

        chunks = self._chunk_store.fetch_chunks(doc_ids)
        if not chunks:
            raise NoChunksForFreezeError("现行 rag_chunks 为空，请先完成切块入库")

        doc_count = len({c.doc_id for c in chunks})
        chunk_count = len(chunks)

        insert_freeze = """
            INSERT INTO rag_eval_chunk_freezes
                (freeze_label, note, pipeline_version, doc_count, chunk_count)
            VALUES (%s, %s, %s, %s, %s)
        """
        insert_item = """
            INSERT INTO rag_eval_chunk_snapshot_items
                (freeze_id, doc_id, chunk_index, chunk_text, content_hash, source_chunk_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        try:
            with connect(self._settings) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        insert_freeze,
                        (label, note, pipeline_version, doc_count, chunk_count),
                    )
                    freeze_id = int(cursor.lastrowid)
                    rows = [
                        (
                            freeze_id,
                            chunk.doc_id,
                            chunk.chunk_index,
                            chunk.chunk_text,
                            self._sha256_hex(chunk.chunk_text),
                            chunk.id,
                        )
                        for chunk in chunks
                    ]
                    cursor.executemany(insert_item, rows)
                    cursor.execute(
                        """
                        SELECT id, freeze_label, note, pipeline_version, doc_count, chunk_count, created_at
                        FROM rag_eval_chunk_freezes WHERE id = %s
                        """,
                        (freeze_id,),
                    )
                    row = cursor.fetchone()
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            # 唯一键冲突
            if "uk_freeze_label" in str(exc) or "Duplicate" in str(exc):
                raise DuplicateFreezeLabelError(f"freeze_label 已存在: {label}") from exc
            raise

        return self._to_summary(row)

    def list_freezes(self, limit: int = 20) -> list[FreezeSummaryRow]:
        query = """
            SELECT id, freeze_label, note, pipeline_version, doc_count, chunk_count, created_at
            FROM rag_eval_chunk_freezes
            ORDER BY id DESC
            LIMIT %s
        """
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
        return [self._to_summary(row) for row in rows]

    def count_freezes(self) -> int:
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM rag_eval_chunk_freezes")
                row = cursor.fetchone()
        return int(row["cnt"]) if row else 0

    def get_freeze(self, freeze_id: int, sample_limit: int = 5) -> FreezeDetailRow | None:
        with connect(self._settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, freeze_label, note, pipeline_version, doc_count, chunk_count, created_at
                    FROM rag_eval_chunk_freezes WHERE id = %s
                    """,
                    (freeze_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute(
                    """
                    SELECT doc_id, chunk_index, source_chunk_id, content_hash,
                           LEFT(chunk_text, 120) AS chunk_text_preview
                    FROM rag_eval_chunk_snapshot_items
                    WHERE freeze_id = %s
                    ORDER BY doc_id ASC, chunk_index ASC
                    LIMIT %s
                    """,
                    (freeze_id, sample_limit),
                )
                samples = cursor.fetchall()
        summary = self._to_summary(row)
        return FreezeDetailRow(
            freeze_id=summary.freeze_id,
            freeze_label=summary.freeze_label,
            note=summary.note,
            pipeline_version=summary.pipeline_version,
            doc_count=summary.doc_count,
            chunk_count=summary.chunk_count,
            created_at=summary.created_at,
            sample_items=[
                {
                    "doc_id": str(item["doc_id"]),
                    "chunk_index": int(item["chunk_index"]),
                    "source_chunk_id": int(item["source_chunk_id"]) if item["source_chunk_id"] is not None else None,
                    "content_hash": str(item["content_hash"]),
                    "chunk_text_preview": str(item["chunk_text_preview"]),
                }
                for item in samples
            ],
        )

    @staticmethod
    def _sha256_hex(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_summary(row: dict) -> FreezeSummaryRow:
        return FreezeSummaryRow(
            freeze_id=int(row["id"]),
            freeze_label=str(row["freeze_label"]),
            note=row["note"],
            pipeline_version=row["pipeline_version"],
            doc_count=int(row["doc_count"]),
            chunk_count=int(row["chunk_count"]),
            created_at=str(row["created_at"]),
        )
