from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。"""

    api_key_ali: str = Field(alias="API_KEY_ALI")
    embedding_model: str = "text-embedding-v4"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chunk_size: int = 500
    chunk_overlap: int = 50
    index_name: str = "local_rag_index"

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("api_key_ali")
    @classmethod
    def validate_api_key_ali(cls, value: str) -> str:
        api_key = value.strip()
        if not api_key:
            raise ValueError("环境变量 API_KEY_ALI 不能为空")
        return api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载并缓存配置。"""
    return Settings()
