"""文档抽取模块。"""

from app.extract.models import ContentBlock, ExtractedDocument, ExtractReport

__all__ = [
    "ContentBlock",
    "ExtractReport",
    "ExtractedDocument",
    "PdfExtractPipeline",
]


def __getattr__(name: str):
    # 延迟加载，避免仅使用 models 时拉取 MinerU
    if name == "PdfExtractPipeline":
        from app.extract.pipeline import PdfExtractPipeline

        return PdfExtractPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
