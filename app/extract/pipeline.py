import hashlib
from typing import Any

from unstructured.documents.elements import Element, PageBreak

from app.extract.cleaners import EXTRACT_CLEANERS, is_table_node, resolve_category
from app.extract.models import ContentBlock, ExtractReport, ExtractedDocument
from app.extract.nodes import ExtractNode
from app.extract.table_continuation import merge_table_continuations, wrap_table_html
from app.extract.text_renderer import render_full_text
from app.extract.unstructured_loader import EXTRACT_VERSION, load_pdf_elements

TABLE_CATEGORY = "Table"


class PdfExtractPipeline:
    """PDF 抽取编排：加载、清洗、续表合并、渲染。"""

    def extract(self, doc_id: str, file_path: str, metadata: dict[str, Any] | None = None) -> ExtractedDocument:
        elements = load_pdf_elements(file_path)
        if not elements:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        nodes = self._elements_to_nodes(elements)
        if not nodes:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        report = ExtractReport(element_count=len(nodes))
        cleaned_nodes, dropped = self._run_cleaners(nodes)
        report.dropped_elements = dropped

        blocks = self._nodes_to_blocks(cleaned_nodes)
        blocks, merged_count = merge_table_continuations(blocks)
        report.merged_continuations = merged_count
        report.table_count = sum(1 for block in blocks if block.block_type == "table")
        report.paragraph_block_count = sum(1 for block in blocks if block.block_type == "paragraph")

        full_text = render_full_text(blocks)
        if not full_text:
            raise ValueError(f"文档内容为空，无法抽取: {file_path}")

        page_count = self._estimate_page_count(elements)
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
    def _elements_to_nodes(elements: list[Element]) -> list[ExtractNode]:
        nodes: list[ExtractNode] = []
        for index, element in enumerate(elements):
            if isinstance(element, PageBreak):
                continue
            metadata = dict(element.metadata.to_dict())
            category = resolve_category(metadata) or str(getattr(element, "category", "")).strip()
            metadata["category"] = category
            if category == TABLE_CATEGORY:
                html = str(metadata.get("text_as_html") or element.text or "").strip()
                metadata["table_html"] = html
                nodes.append(ExtractNode(text=html, metadata=metadata, node_id=f"table-{index}"))
            else:
                nodes.append(
                    ExtractNode(
                        text=str(element.text or ""),
                        metadata=metadata,
                        node_id=f"text-{index}",
                    )
                )
        return nodes

    @staticmethod
    def _run_cleaners(nodes: list[ExtractNode]) -> tuple[list[ExtractNode], int]:
        current = nodes
        total_dropped = 0
        for cleaner in EXTRACT_CLEANERS:
            before = len(current)
            current = cleaner(current)
            total_dropped += before - len(current)
        return current, total_dropped

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
            if text:
                blocks.append(ContentBlock(block_type="paragraph", order=order, text=text))
        return blocks

    @staticmethod
    def _estimate_page_count(elements: list[Element]) -> int:
        page_numbers: set[int] = set()
        for element in elements:
            page_number = element.metadata.page_number
            if isinstance(page_number, int) and page_number > 0:
                page_numbers.add(page_number)
        if page_numbers:
            return len(page_numbers)
        return max(len(elements), 1)

    @staticmethod
    def _compute_hash(full_text: str) -> str:
        return hashlib.sha256(full_text.encode("utf-8")).hexdigest()
