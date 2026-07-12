from __future__ import annotations

from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from openai import AsyncOpenAI, OpenAI
from pydantic import Field, PrivateAttr


class QwenEmbedding(BaseEmbedding):
    """基于 OpenAI 兼容协议封装的 Qwen 向量模型。"""

    api_key: str = Field(description="阿里云百炼 API Key")
    api_base: str = Field(description="百炼兼容 OpenAI 的 Base URL")
    timeout: float = Field(default=60.0, ge=0)
    max_retries: int = Field(default=3, ge=0)

    _client: OpenAI | None = PrivateAttr(default=None)
    _aclient: AsyncOpenAI | None = PrivateAttr(default=None)

    @classmethod
    def class_name(cls) -> str:
        return "QwenEmbedding"

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def _get_aclient(self) -> AsyncOpenAI:
        if self._aclient is None:
            self._aclient = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._aclient

    def _normalize_text(self, text: str) -> str:
        # 与 LlamaIndex 既有实现保持一致，统一去除换行降低噪声。
        return text.replace("\n", " ")

    def _extract_embedding(self, response: Any) -> list[float]:
        if not response.data:
            raise ValueError("向量接口未返回有效 embedding 数据")
        return list(response.data[0].embedding)

    def _get_query_embedding(self, query: str) -> list[float]:
        response = self._get_client().embeddings.create(
            model=self.model_name,
            input=self._normalize_text(query),
        )
        return self._extract_embedding(response)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        response = await self._get_aclient().embeddings.create(
            model=self.model_name,
            input=self._normalize_text(query),
        )
        return self._extract_embedding(response)

    def _get_text_embedding(self, text: str) -> list[float]:
        response = self._get_client().embeddings.create(
            model=self.model_name,
            input=self._normalize_text(text),
        )
        return self._extract_embedding(response)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        normalized = [self._normalize_text(text) for text in texts]
        response = self._get_client().embeddings.create(
            model=self.model_name,
            input=normalized,
        )
        return [list(item.embedding) for item in response.data]
