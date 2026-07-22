import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.config import Settings
from app.extract.models import ContentBlock, ExtractReport, ExtractedDocument


@dataclass
class DocumentRow:
    doc_id: str
    file_path: str
    extract_version: str
    page_count: int
    char_count: int
    full_text: str
    blocks: list[ContentBlock]
    extract_report: ExtractReport | None
    metadata: dict[str, Any] | None
    content_hash: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


def document_row_to_extracted(row: DocumentRow) -> ExtractedDocument:
    """将数据库行转换为抽取文档对象。"""
    return ExtractedDocument(
        doc_id=row.doc_id,
        file_path=row.file_path,
        extract_version=row.extract_version,
        page_count=row.page_count,
        blocks=row.blocks,
        full_text=row.full_text,
        metadata=row.metadata,
        content_hash=row.content_hash,
        extract_report=row.extract_report or ExtractReport(),
    )


class MySQLDocumentStore:
    """负责 rag_documents 表的读写。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def replace_document(self, document: ExtractedDocument) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM rag_documents WHERE doc_id = %s", (document.doc_id,))
                insert_sql = """
                    INSERT INTO rag_documents (
                        doc_id,
                        file_path,
                        extract_version,
                        page_count,
                        char_count,
                        full_text,
                        blocks,
                        extract_report,
                        metadata,
                        content_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_sql,
                    (
                        document.doc_id,
                        document.file_path,
                        document.extract_version,
                        document.page_count,
                        document.char_count,
                        document.full_text,
                        self._blocks_to_json(document.blocks),
                        self._to_json(document.extract_report.to_dict()),
                        self._to_json(document.metadata),
                        document.content_hash,
                    ),
                )
            conn.commit()

    def fetch_document(self, doc_id: str) -> DocumentRow | None:
        rows = self.fetch_documents([doc_id])
        return rows[0] if rows else None

    def fetch_documents(self, doc_ids: list[str]) -> list[DocumentRow]:
        if not doc_ids:
            return []

        placeholders = ", ".join(["%s"] * len(doc_ids))
        query = f"""
            SELECT
                doc_id,
                file_path,
                extract_version,
                page_count,
                char_count,
                full_text,
                blocks,
                extract_report,
                metadata,
                content_hash,
                created_at,
                updated_at
            FROM rag_documents
            WHERE doc_id IN ({placeholders})
            ORDER BY doc_id ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(doc_ids))
                rows = cursor.fetchall()
        return [self._to_document_row(row) for row in rows]

    def count_documents(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM rag_documents")
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
    def _blocks_to_json(blocks: list[ContentBlock]) -> str:
        payload = []
        for block in blocks:
            item: dict[str, Any] = {
                "type": block.block_type,
                "order": block.order,
            }
            if block.text is not None:
                item["text"] = block.text
            if block.html is not None:
                item["html"] = block.html
            if block.logical_table_id is not None:
                item["logical_table_id"] = block.logical_table_id
            if block.page_idx is not None:
                item["page_idx"] = block.page_idx
            if block.bbox is not None:
                item["bbox"] = block.bbox
            if block.text_level is not None:
                item["text_level"] = block.text_level
            payload.append(item)
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _from_blocks_json(value: Any) -> list[ContentBlock]:
        if value is None:
            return []
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            return []

        blocks: list[ContentBlock] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type", "")).strip()
            if block_type not in {"title", "paragraph", "list_item", "table"}:
                continue
            blocks.append(
                ContentBlock(
                    block_type=block_type,  # type: ignore[arg-type]
                    order=int(item.get("order", 0)),
                    text=item.get("text"),
                    html=item.get("html"),
                    logical_table_id=item.get("logical_table_id"),
                    page_idx=_parse_optional_int(item.get("page_idx")),
                    bbox=_parse_optional_bbox(item.get("bbox")),
                    text_level=_parse_optional_int(item.get("text_level")),
                )
            )
        return sorted(blocks, key=lambda block: block.order)

    @staticmethod
    def _from_report_json(value: Any) -> ExtractReport | None:
        if value is None:
            return None
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict):
            return None
        paragraph_count = int(
            parsed.get("paragraph_count", parsed.get("paragraph_block_count", 0))
        )
        return ExtractReport(
            element_count=int(parsed.get("element_count", 0)),
            dropped_elements=int(parsed.get("dropped_elements", 0)),
            dropped_fragments=int(parsed.get("dropped_fragments", 0)),
            dropped_garbled=int(parsed.get("dropped_garbled", 0)),
            table_count=int(parsed.get("table_count", 0)),
            table_quality_failed=int(parsed.get("table_quality_failed", 0)),
            merged_continuations=int(parsed.get("merged_continuations", 0)),
            title_count=int(parsed.get("title_count", 0)),
            paragraph_count=paragraph_count,
            list_item_count=int(parsed.get("list_item_count", 0)),
            paragraph_block_count=int(parsed.get("paragraph_block_count", paragraph_count)),
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

    def _to_document_row(self, row: dict[str, Any]) -> DocumentRow:
        return DocumentRow(
            doc_id=str(row["doc_id"]),
            file_path=str(row["file_path"]),
            extract_version=str(row["extract_version"]),
            page_count=int(row["page_count"]),
            char_count=int(row["char_count"]),
            full_text=str(row["full_text"]),
            blocks=self._from_blocks_json(row["blocks"]),
            extract_report=self._from_report_json(row["extract_report"]),
            metadata=self._from_json(row["metadata"]),
            content_hash=str(row["content_hash"]),
            created_at=row.get("created_at") if isinstance(row.get("created_at"), datetime) else None,
            updated_at=row.get("updated_at") if isinstance(row.get("updated_at"), datetime) else None,
        )


def _parse_optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None
