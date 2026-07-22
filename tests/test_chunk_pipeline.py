"""切块管线单元测试：递归切分 / 过短合并 / Markdown 表。"""

from __future__ import annotations

import pytest

from app.chunk.models import EmptyChunkInputError
from app.chunk.pipeline import ChunkPipeline
from app.chunk.recursive_splitter import recursive_split_text
from app.chunk.table_splitter import split_table_html
from app.extract.models import ContentBlock


SAMPLE_TABLE_HTML = """
<table>
<caption>故障码表</caption>
<thead><tr><th>代码</th><th>说明</th></tr></thead>
<tbody>
<tr><td>P0001</td><td>燃油量调节器控制电路开路</td></tr>
<tr><td>P0002</td><td>燃油量调节器控制电路范围性能</td></tr>
<tr><td>P0003</td><td>燃油量调节器控制电路低</td></tr>
<tr><td>P0004</td><td>燃油量调节器控制电路高</td></tr>
</tbody>
</table>
""".strip()

SAMPLE_TABLE_NO_THEAD = """
<table data-logical-id="tbl-000">
<tr><td>参数项</td><td>标准配置值</td><td>备注说明</td></tr>
<tr><td>传输协议</td><td>TCP</td><td>唯一支持协议</td></tr>
<tr><td>默认通信端口</td><td>11009</td><td>可自定义</td></tr>
<tr><td>心跳周期</td><td>30s</td><td>超时60s判定断开</td></tr>
<tr><td>重连间隔</td><td>10s</td><td>断开后自动重试</td></tr>
</table>
""".strip()


def test_rag_chunk_unit_blocks_path_001() -> None:
    pipeline = ChunkPipeline(chunk_size=120, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(
                block_type="paragraph",
                order=0,
                text="这是一段足够长的段落正文，用于结构感知切块，确保不会因过短被并入表格前缀。",
            ),
            ContentBlock(
                block_type="table",
                order=1,
                html=SAMPLE_TABLE_HTML,
                logical_table_id="tbl-1",
            ),
        ],
        full_text="这段 full_text 在有 blocks 时不应被使用。",
        base_metadata={"doc_id": "doc-blocks", "file_path": "/tmp/a.pdf"},
    )
    kinds = [piece.metadata.get("chunk_kind") for piece in pieces]
    assert "paragraph" in kinds
    assert "table_rows" in kinds
    assert "full_text_fallback" not in kinds


def test_rag_chunk_unit_title_list_item_001() -> None:
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="4.1.1 登录报文(0x1001)"),
            ContentBlock(block_type="paragraph", order=1, text="下级平台向上级平台发起登录认证。"),
            ContentBlock(block_type="list_item", order=2, text="• 最大重传 3 次"),
            ContentBlock(block_type="list_item", order=3, text="• 离线缓存 1000 条"),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-types"},
    )
    assert len(pieces) == 1
    text = pieces[0].chunk_text
    assert "0x1001" in text
    assert "最大重传 3 次" in text
    assert pieces[0].metadata.get("section_title") == "4.1.1 登录报文(0x1001)"


def test_rag_chunk_unit_merge_short_paragraphs_001() -> None:
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="7.设备调试与故障排查"),
            ContentBlock(block_type="title", order=1, text="7.1正常通信状态判定"),
            ContentBlock(block_type="paragraph", order=2, text="TCP链路连接正常，无断开重连记录；"),
            ContentBlock(block_type="paragraph", order=3, text="30秒心跳交互正常，无超时异常；"),
            ContentBlock(block_type="paragraph", order=4, text="工况、故障数据上报后可正常接收平台应答；"),
            ContentBlock(block_type="paragraph", order=5, text="报文校验通过率100%，无异常丢弃日志。"),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-merge"},
    )
    assert len(pieces) == 1
    assert "7.设备调试与故障排查" in pieces[0].chunk_text
    assert "报文校验通过率100%" in pieces[0].chunk_text


def test_rag_chunk_unit_short_title_before_table_001() -> None:
    """表前 title 一律挂到表格前缀（不限长度）；有正文时标题粘在正文首块。"""
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20, min_chunk_chars=20)

    # 正文 + 表前标题：正文单独成块，标题挂表
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="paragraph", order=0, text="前面已有足够长度的正文内容，用于承接后续表格标题。"),
            ContentBlock(block_type="title", order=1, text="2.2 通信参数标准"),
            ContentBlock(block_type="table", order=2, html=SAMPLE_TABLE_HTML),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-title-table"},
    )
    para = [p for p in pieces if p.metadata.get("chunk_kind") == "paragraph"]
    tables = [p for p in pieces if p.metadata.get("chunk_kind") == "table_rows"]
    assert para and "前面已有足够长度" in para[0].chunk_text
    assert tables and tables[0].chunk_text.startswith("2.2 通信参数标准")

    # 仅标题 + 表
    pieces2 = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="3.2 报文头详细定义(16字节)"),
            ContentBlock(block_type="table", order=1, html=SAMPLE_TABLE_HTML),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-short-prefix"},
    )
    assert any(
        p.metadata.get("chunk_kind") == "table_rows" and p.chunk_text.startswith("3.2 报文头详细定义")
        for p in pieces2
    )


def test_rag_chunk_unit_title_sticky_001() -> None:
    """标题必须粘在正文首块，不能落在上块末尾、下块从正文起。"""
    pipeline = ChunkPipeline(chunk_size=120, chunk_overlap=0, min_chunk_chars=20)
    long_body = "这是紧跟标题的正文内容。" * 10
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="1.3 协议基础定义"),
            ContentBlock(block_type="paragraph", order=1, text=long_body),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-sticky"},
    )
    assert pieces
    assert pieces[0].chunk_text.startswith("1.3 协议基础定义")
    # 后续块若有，不应再以该完整标题结尾导致正文孤儿开头
    for piece in pieces[1:]:
        assert not piece.chunk_text.startswith("这是紧跟标题的正文内容。这是紧跟标题的正文内容。这是紧跟标题")


def test_rag_chunk_unit_paragraph_flush_before_table_001() -> None:
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="paragraph", order=0, text="7.2常见故障排查方案，本章说明排查步骤与常见原因。"),
            ContentBlock(block_type="table", order=1, html=SAMPLE_TABLE_HTML),
            ContentBlock(block_type="paragraph", order=2, text="8.安全与运维规范"),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-flush"},
    )
    para_texts = [p.chunk_text for p in pieces if p.metadata.get("chunk_kind") == "paragraph"]
    table_texts = [p.chunk_text for p in pieces if p.metadata.get("chunk_kind") == "table_rows"]
    assert any("7.2常见故障排查方案" in t for t in para_texts)
    assert any("8.安全与运维规范" in t for t in para_texts)
    assert table_texts
    assert all("<table>" not in t for t in table_texts)


def test_rag_chunk_unit_recursive_split_001() -> None:
    """超长文本应被递归切开，且除整句例外外不超过 chunk_size。"""
    pipeline = ChunkPipeline(chunk_size=80, chunk_overlap=10)
    # 使用不同句子，避免去重逻辑把重复句误判为 overlap
    long_para = (
        "第一句完整的中文测试内容，用于验证递归切分。"
        "第二句继续补充说明，仍然属于同一段落。"
        "第三句提供更多上下文信息以便超过长度。"
        "第四句再次拉长文本触发多层切分。"
        "第五句确保总体长度明显高于阈值。"
        "第六句作为收尾内容完成样例构造。"
    )
    pieces = pipeline.chunk_document(
        blocks=[ContentBlock(block_type="paragraph", order=0, text=long_para)],
        full_text="",
        base_metadata={"doc_id": "doc-recursive"},
    )
    assert len(pieces) >= 2
    assert all(len(p.chunk_text) <= 80 for p in pieces)


def test_rag_chunk_unit_fallback_001() -> None:
    pipeline = ChunkPipeline(chunk_size=80, chunk_overlap=10)
    full_text = "回退路径测试。这句话用于验证无 blocks 时的切分行为。" * 3
    pieces = pipeline.chunk_document(
        blocks=[],
        full_text=full_text,
        base_metadata={"doc_id": "doc-fallback", "file_path": "/tmp/b.pdf"},
    )
    assert pieces
    assert all(piece.metadata.get("chunk_kind") == "full_text_fallback" for piece in pieces)


def test_rag_chunk_unit_table_header_001() -> None:
    pieces = split_table_html(
        SAMPLE_TABLE_HTML,
        chunk_size=120,
        base_metadata={"doc_id": "doc-table"},
        logical_table_id="tbl-header",
    )
    assert len(pieces) >= 2
    for piece in pieces:
        assert piece.metadata["table_format"] == "markdown"
        assert "| 代码 | 说明 |" in piece.chunk_text
        assert "<table>" not in piece.chunk_text


def test_rag_chunk_unit_table_first_row_header_001() -> None:
    pieces = split_table_html(
        SAMPLE_TABLE_NO_THEAD,
        chunk_size=100,
        base_metadata={"doc_id": "doc-no-thead"},
        logical_table_id="tbl-000",
    )
    assert len(pieces) >= 2
    for piece in pieces:
        assert "| 参数项 | 标准配置值 | 备注说明 |" in piece.chunk_text


def test_rag_chunk_unit_table_fallback_001() -> None:
    pieces = split_table_html(
        "<table><caption>空表</caption></table>",
        chunk_size=200,
        base_metadata={"doc_id": "doc-empty-table"},
    )
    assert pieces[0].metadata["chunk_kind"] == "table_fallback"
    assert "<table>" not in pieces[0].chunk_text


def test_rag_chunk_unit_empty_input_001() -> None:
    pipeline = ChunkPipeline(chunk_size=100, chunk_overlap=20)
    with pytest.raises(EmptyChunkInputError):
        pipeline.chunk_document(blocks=[], full_text="", base_metadata={"doc_id": "empty"})


def test_rag_chunk_unit_recursive_helper_001() -> None:
    parts = recursive_split_text("第一段内容。\n\n第二段内容。\n\n第三段内容。", chunk_size=20, chunk_overlap=0)
    assert len(parts) >= 2
    assert all(len(p) <= 20 or "。" in p for p in parts)


def test_rag_chunk_unit_metadata_enterprise_001() -> None:
    """企业级 metadata：页码、章节路径、长度指标、链表、无 block_type。"""
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(
                block_type="title",
                order=0,
                text="4 数据交互流程",
                page_idx=10,
                text_level=1,
                bbox=[1.0, 2.0, 3.0, 4.0],
            ),
            ContentBlock(
                block_type="title",
                order=1,
                text="4.2 终端上报指令",
                page_idx=11,
                text_level=2,
            ),
            ContentBlock(
                block_type="title",
                order=2,
                text="4.2.1 车辆OBD工况数据上报(0x6001)",
                page_idx=12,
                text_level=3,
            ),
            ContentBlock(
                block_type="paragraph",
                order=3,
                text="终端按周期上报 OBD 工况数据，报文标识为 0x6001，详见协议正文说明。",
                page_idx=12,
                bbox=[58.0, 240.0, 540.0, 780.0],
            ),
        ],
        full_text="",
        base_metadata={
            "doc_id": "pdf-obd-809",
            "file_path": "docs/a.pdf",
            "source": "local_pdf",
            "category": "pdf",
            "doc_version": "V2.3",
            "access_group": ["rd", "after_sales"],
        },
    )
    assert len(pieces) == 1
    meta = pieces[0].metadata
    assert "block_type" not in meta
    assert meta["chunk_kind"] == "paragraph"
    assert meta["chunk_index"] == 0
    assert meta["prev_chunk_index"] is None
    assert meta["next_chunk_index"] is None
    assert meta["page_num"] == 11  # min page_idx 10 → 但 section 含 10,11,12 → min+1=11
    assert meta["page_end"] == 13
    assert meta["is_cross_page"] is True
    assert meta["full_section_path"] == [
        "4 数据交互流程",
        "4.2 终端上报指令",
        "4.2.1 车辆OBD工况数据上报(0x6001)",
    ]
    assert meta["parent_section"] == "4.2 终端上报指令"
    assert meta["section_title"] == "4.2.1 车辆OBD工况数据上报(0x6001)"
    assert meta["char_count"] == len(pieces[0].chunk_text)
    assert meta["token_count"] > 0
    assert meta["has_protocol_code"] is True
    assert meta["access_group"] == ["rd", "after_sales"]
    assert meta["doc_version"] == "V2.3"
    assert meta["bbox"] is None  # 跨 block 且 bbox 不一致


def test_rag_chunk_unit_metadata_table_cols_001() -> None:
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(
                block_type="table",
                order=0,
                html=SAMPLE_TABLE_HTML,
                logical_table_id="tbl-1",
                page_idx=5,
                bbox=[10.0, 20.0, 30.0, 40.0],
            )
        ],
        full_text="",
        base_metadata={"doc_id": "doc-table-meta"},
    )
    table_pieces = [p for p in pieces if p.metadata.get("chunk_kind") == "table_rows"]
    assert table_pieces
    meta = table_pieces[0].metadata
    assert meta["table_cols"] == 2
    assert meta["page_num"] == 6
    assert meta["page_end"] == 6
    assert meta["is_cross_page"] is False
    assert meta["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert meta["access_group"] == ["rd"]
    assert "block_type" not in meta


def test_rag_chunk_unit_section_path_numbering_over_flat_level_001() -> None:
    """即便 text_level 全为 2，编号启发也应保留中间章节层。"""
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="OBD设备JT/T 809协议虚拟技术手册", text_level=1),
            ContentBlock(block_type="title", order=1, text="1. 手册总则", text_level=2),
            ContentBlock(block_type="title", order=2, text="1.1 手册目的", text_level=2),
            ContentBlock(block_type="paragraph", order=3, text="本手册用于规范 OBD 设备与监管平台的数据交互。"),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-path"},
    )
    meta = pieces[0].metadata
    assert meta["full_section_path"] == [
        "OBD设备JT/T 809协议虚拟技术手册",
        "1. 手册总则",
        "1.1 手册目的",
    ]
    assert meta["parent_section"] == "1. 手册总则"
    assert meta["section_title"] == "1.1 手册目的"


def test_rag_chunk_unit_table_section_follows_prefix_001() -> None:
    """表前 title 写入 chunk_text 时，section_title / path 必须同步到该标题。"""
    pipeline = ChunkPipeline(chunk_size=500, chunk_overlap=20)
    pieces = pipeline.chunk_document(
        blocks=[
            ContentBlock(block_type="title", order=0, text="7. 设备调试与故障排查", text_level=2),
            ContentBlock(block_type="title", order=1, text="7.1 正常通信状态判定", text_level=2),
            ContentBlock(block_type="list_item", order=2, text="• TCP链路连接正常，无断开重连记录；"),
            ContentBlock(block_type="list_item", order=3, text="• 30秒心跳交互正常，无超时异常；"),
            ContentBlock(block_type="title", order=4, text="7.2 常见故障排查方案", text_level=2),
            ContentBlock(
                block_type="table",
                order=5,
                html=SAMPLE_TABLE_HTML,
                logical_table_id="tbl-7-2",
            ),
        ],
        full_text="",
        base_metadata={"doc_id": "doc-table-section"},
    )
    table_piece = next(p for p in pieces if p.metadata.get("chunk_kind") == "table_rows")
    assert table_piece.chunk_text.startswith("7.2 常见故障排查方案")
    assert table_piece.metadata["section_title"] == "7.2 常见故障排查方案"
    assert table_piece.metadata["parent_section"] == "7. 设备调试与故障排查"
    assert table_piece.metadata["full_section_path"] == [
        "7. 设备调试与故障排查",
        "7.2 常见故障排查方案",
    ]
