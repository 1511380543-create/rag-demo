#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测稳定证据键：映射到现行 rag_chunks.id。"""

from __future__ import annotations

from dataclasses import dataclass

from app.mysql_chunk_store import ChunkRow


@dataclass(frozen=True)
class EvidenceKeyData:
    """稳定证据键（与 API EvidenceKey 对应）。"""

    anchor_text: str
    doc_id: str | None = None
    content_hash: str | None = None


def resolve_evidence_keys_to_chunk_ids(
    evidence_keys: list[EvidenceKeyData] | None,
    chunks: list[ChunkRow],
) -> list[str]:
    """将证据键解析为当期 chunk_id 列表（去重，保持首次出现顺序）。"""
    if not evidence_keys:
        return []

    matched: list[str] = []
    seen: set[str] = set()
    for key in evidence_keys:
        anchor = (key.anchor_text or "").strip()
        content_hash = (key.content_hash or "").strip().lower()
        if not anchor and not content_hash:
            continue
        for chunk in chunks:
            if key.doc_id and chunk.doc_id != key.doc_id:
                continue
            ok = False
            if content_hash:
                # 与冻结表一致：SHA-256 hex；此处对正文即时计算过重，仅当 metadata 带 hash 时可用。
                # 当前阶段以 anchor_text 为主；content_hash 预留与快照对齐。
                meta_hash = ""
                if chunk.metadata and isinstance(chunk.metadata.get("content_hash"), str):
                    meta_hash = chunk.metadata["content_hash"].strip().lower()
                if meta_hash and meta_hash == content_hash:
                    ok = True
            if anchor and anchor in chunk.chunk_text:
                ok = True
            if not ok:
                continue
            chunk_id = str(chunk.id)
            if chunk_id not in seen:
                seen.add(chunk_id)
                matched.append(chunk_id)
    return matched


def merge_relevant_chunk_ids(
    explicit_ids: list[str] | None,
    resolved_from_evidence: list[str],
) -> list[str] | None:
    """合并显式 chunk 标注与证据键解析结果。"""
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(explicit_ids or []) + resolved_from_evidence:
        cleaned = str(item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged or None
