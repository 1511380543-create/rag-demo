import hashlib
from typing import Any

from app.extract.cleaners import CleanStats, apply_text_cleaners, filter_tables_by_quality, is_table_node
from app.extract.mapper import map_content_list_to_nodes
from app.extract.mineru_loader import EXTRACT_VERSION, load_pdf_content_list
from app.extract.models import ContentBlock, ExtractReport, ExtractedDocument
from app.extract.nodes import ExtractNode
from app.extract.table_continuation import merge_table_continuations, wrap_table_html
from app.extract.text_renderer import render_full_text


class PdfExtractPipeline:
    """PDF 抽取编排：MinerU 加载 → 映射 → 清洗 → 表格门禁 → 续表兜底 → 渲染。"""

    def extract(self, doc_id: str, file_path: str, metadata: dict[str, Any] | None = None) -> ExtractedDocument:
        items, page_count = load_pdf_content_list(file_path)
        nodes, discarded_other = map_content_list_to_nodes(items)
        if not nodes:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        stats = CleanStats(discarded_other=discarded_other)
        cleaned = apply_text_cleaners(nodes, stats)
        cleaned = filter_tables_by_quality(cleaned, stats)
        if not cleaned:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        blocks = self._nodes_to_blocks(cleaned)
        blocks, merged_count = merge_table_continuations(blocks)

        report = self._build_report(
            element_count=len(items),
            stats=stats,
            blocks=blocks,
            merged_continuations=merged_count,
        )

        full_text = render_full_text(blocks)
        if not full_text:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        doc_metadata = dict(metadata or {})
        doc_metadata["doc_id"] = doc_id
        doc_metadata["file_path"] = file_path

        return ExtractedDocument(
            doc_id=doc_id,
            file_path=file_path.strip(),
            extract_version=EXTRACT_VERSION,
            page_count=page_count,
            blocks=blocks,
            full_text=full_text,
            metadata=doc_metadata,
            content_hash=self._compute_hash(full_text),
            extract_report=report,
        )

    @staticmethod
    def _nodes_to_blocks(nodes: list[ExtractNode]) -> list[ContentBlock]:
        blocks: list[ContentBlock] = []
        table_seq = 0
        for order, node in enumerate(nodes):
            if is_table_node(node):
                logical_id = f"tbl-{table_seq:03d}"
                table_seq += 1
                html = str(node.metadata.get("table_html") or node.text or "").strip()
                blocks.append(
                    ContentBlock(
                        block_type="table",
                        order=order,
                        html=wrap_table_html(html, logical_id),
                        logical_table_id=logical_id,
                    )
                )
                continue
            text = (node.text or "").strip()
            if not text:
                continue
            blocks.append(
                ContentBlock(
                    block_type=node.node_type,
                    order=order,
                    text=text,
                )
            )
        # 重新编号，保证 order 连续
        for order, block in enumerate(blocks):
            block.order = order
        return blocks

    @staticmethod
    def _build_report(
        *,
        element_count: int,
        stats: CleanStats,
        blocks: list[ContentBlock],
        merged_continuations: int,
    ) -> ExtractReport:
        title_count = sum(1 for block in blocks if block.block_type == "title")
        paragraph_count = sum(1 for block in blocks if block.block_type == "paragraph")
        list_item_count = sum(1 for block in blocks if block.block_type == "list_item")
        table_count = sum(1 for block in blocks if block.block_type == "table")
        dropped_elements = stats.dropped_elements + stats.discarded_other
        return ExtractReport(
            element_count=element_count,
            dropped_elements=dropped_elements,
            dropped_fragments=stats.dropped_fragments,
            dropped_garbled=stats.dropped_garbled,
            table_count=table_count,
            table_quality_failed=stats.table_quality_failed,
            merged_continuations=merged_continuations,
            title_count=title_count,
            paragraph_count=paragraph_count,
            list_item_count=list_item_count,
            paragraph_block_count=paragraph_count,
        )

    @staticmethod
    def _compute_hash(full_text: str) -> str:
        return hashlib.sha256(full_text.encode("utf-8")).hexdigest()
