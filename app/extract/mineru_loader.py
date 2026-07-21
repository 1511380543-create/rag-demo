"""通过本地 MinerU CLI 解析 PDF，读取 content_list.json。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

EXTRACT_VERSION = "mineru-v1"

# 默认解析后端；可用环境变量 MINERU_BACKEND 覆盖（如 pipeline）
_DEFAULT_BACKEND = "pipeline"
# CLI 超时（秒），大文档可按需调大
_DEFAULT_TIMEOUT_SECONDS = 3600


def load_pdf_content_list(file_path: str) -> tuple[list[dict[str, Any]], int]:
    """
    调用本地 mineru CLI，返回 (content_list, page_count)。

    依赖：conda 环境已安装 mineru，且模型可用（如 MINERU_MODEL_SOURCE=modelscope）。
    禁止默认走公网 SaaS。
    """
    normalized = file_path.strip()
    if not normalized.lower().endswith(".pdf"):
        raise ValueError("仅支持 PDF 文档抽取，请传入 .pdf 文件路径")

    pdf_path = Path(normalized).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {normalized}")

    mineru_bin = shutil.which("mineru")
    if not mineru_bin:
        raise RuntimeError(
            "未找到 mineru 命令，请先在 conda 环境 rag-demo 中安装 mineru，"
            "并确保 PATH 中可执行 `mineru`"
        )

    backend = (os.environ.get("MINERU_BACKEND") or _DEFAULT_BACKEND).strip() or _DEFAULT_BACKEND
    timeout = int(os.environ.get("MINERU_TIMEOUT_SECONDS") or _DEFAULT_TIMEOUT_SECONDS)

    with tempfile.TemporaryDirectory(prefix="rag-demo-mineru-") as tmp_dir:
        output_dir = Path(tmp_dir)
        cmd = [
            mineru_bin,
            "-p",
            str(pdf_path),
            "-o",
            str(output_dir),
            "-b",
            backend,
            "-t",
            "true",
            "-f",
            "false",
        ]
        env = os.environ.copy()
        # 国内常见：未设置时提示用户可设 modelscope；不强制改写已有配置
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit_code={completed.returncode}"
            raise RuntimeError(f"MinerU 解析失败: {detail}")

        content_path = _find_content_list_file(output_dir)
        if content_path is None:
            raise RuntimeError(
                f"MinerU 未产出 content_list.json，输出目录: {output_dir}。"
                f"stdout={(completed.stdout or '')[-500:]}"
            )

        raw = json.loads(content_path.read_text(encoding="utf-8"))
        items = _normalize_content_list(raw)
        if not items:
            raise ValueError(f"文档内容为空，无法抽取: {normalized}")

        page_count = _estimate_page_count(items)
        return items, page_count


def _find_content_list_file(output_dir: Path) -> Path | None:
    """优先取 *_content_list.json（非 v2）；找不到再退回任意 content_list。"""
    candidates = sorted(output_dir.rglob("*_content_list.json"))
    preferred = [path for path in candidates if "content_list_v2" not in path.name]
    if preferred:
        return preferred[0]
    v2 = sorted(output_dir.rglob("*_content_list_v2.json"))
    return v2[0] if v2 else None


def _normalize_content_list(raw: Any) -> list[dict[str, Any]]:
    """将 content_list / content_list_v2 统一为扁平 dict 列表。"""
    if isinstance(raw, list):
        if not raw:
            return []
        # content_list_v2：按页分组的二维列表
        if isinstance(raw[0], list):
            flat: list[dict[str, Any]] = []
            for page_idx, page_items in enumerate(raw):
                if not isinstance(page_items, list):
                    continue
                for item in page_items:
                    if isinstance(item, dict):
                        mapped = _map_v2_item(item, page_idx)
                        if mapped is not None:
                            flat.append(mapped)
            return flat
        return [item for item in raw if isinstance(item, dict)]
    raise RuntimeError(f"无法识别 MinerU content_list 结构: {type(raw).__name__}")


def _map_v2_item(item: dict[str, Any], page_idx: int) -> dict[str, Any] | None:
    """将 content_list_v2 单项映射为接近 v1 的扁平结构。"""
    item_type = str(item.get("type") or "").strip().lower()
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    bbox = item.get("bbox")
    base: dict[str, Any] = {"page_idx": page_idx}
    if bbox is not None:
        base["bbox"] = bbox

    if item_type == "title":
        text = _spans_to_text(content.get("title_content"))
        level = content.get("level")
        return {**base, "type": "text", "text": text, "text_level": int(level or 1)}
    if item_type == "paragraph":
        text = _spans_to_text(content.get("paragraph_content"))
        return {**base, "type": "text", "text": text, "text_level": 0}
    if item_type in {"list", "index"}:
        items = content.get("list_items") or []
        texts = [_spans_to_text(x) if isinstance(x, list) else str(x) for x in items]
        return {**base, "type": "list", "list_items": [t for t in texts if t.strip()]}
    if item_type == "table":
        table_body = content.get("table_body") or content.get("html") or ""
        captions = content.get("table_caption") or content.get("captions") or []
        if isinstance(captions, str):
            captions = [captions]
        return {
            **base,
            "type": "table",
            "table_body": str(table_body),
            "table_caption": captions,
        }
    # 图片/公式/页眉页脚等本阶段丢弃
    return None


def _spans_to_text(spans: Any) -> str:
    if spans is None:
        return ""
    if isinstance(spans, str):
        return spans
    if not isinstance(spans, list):
        return str(spans)
    parts: list[str] = []
    for span in spans:
        if isinstance(span, str):
            parts.append(span)
        elif isinstance(span, dict):
            if "content" in span and isinstance(span["content"], str):
                parts.append(span["content"])
            elif "children" in span:
                parts.append(_spans_to_text(span["children"]))
    return "".join(parts)


def _estimate_page_count(items: list[dict[str, Any]]) -> int:
    pages: set[int] = set()
    for item in items:
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int) and page_idx >= 0:
            pages.add(page_idx)
    if pages:
        return max(pages) + 1
    return 1
