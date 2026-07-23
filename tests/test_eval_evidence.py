#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳定证据键映射单测（不依赖 MySQL）。"""

from __future__ import annotations

from app.eval_evidence import (
    EvidenceKeyData,
    merge_relevant_chunk_ids,
    resolve_evidence_keys_to_chunk_ids,
)
from app.mysql_chunk_store import ChunkRow


def _chunk(chunk_id: int, doc_id: str, text: str, metadata: dict | None = None) -> ChunkRow:
    return ChunkRow(
        id=chunk_id,
        doc_id=doc_id,
        chunk_index=0,
        chunk_text=text,
        metadata=metadata,
    )


def test_resolve_evidence_keys_by_anchor_and_doc() -> None:
    chunks = [
        _chunk(11, "pdf-a", "默认端口 11009，心跳周期 30 秒"),
        _chunk(12, "pdf-b", "默认端口 22022，心跳周期 60 秒"),
    ]
    keys = [EvidenceKeyData(doc_id="pdf-a", anchor_text="11009")]
    assert resolve_evidence_keys_to_chunk_ids(keys, chunks) == ["11"]


def test_resolve_evidence_keys_content_hash() -> None:
    chunks = [
        _chunk(21, "pdf-a", "正文A", metadata={"content_hash": "abc"}),
        _chunk(22, "pdf-a", "正文B", metadata={"content_hash": "def"}),
    ]
    keys = [EvidenceKeyData(anchor_text="", content_hash="DEF")]
    assert resolve_evidence_keys_to_chunk_ids(keys, chunks) == ["22"]


def test_merge_relevant_chunk_ids_dedupe() -> None:
    assert merge_relevant_chunk_ids(["1", "2"], ["2", "3"]) == ["1", "2", "3"]
    assert merge_relevant_chunk_ids(None, []) is None
