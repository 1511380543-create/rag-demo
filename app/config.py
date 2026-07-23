from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。"""

    api_key_ali: str = Field(alias="API_KEY_ALI")
    embedding_model: str = "text-embedding-v4"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chunk_size: int = 500
    chunk_overlap: int = 20
    min_chunk_chars: int = 20
    # 同标题章节软上限：总长不超过时整节一块（可超过 chunk_size）
    section_soft_max: int = 1000
    # 检索最低相似度：低于该分的 chunk 丢弃；全部低于则空召回（contexts=[]）
    min_score: float = Field(default=0.5, alias="RAG_MIN_SCORE")
    index_name: str = "local_rag_index"
    mysql_host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_user: str = Field(default="root", alias="MYSQL_USER")
    mysql_password: str = Field(default="root", alias="MYSQL_PASSWORD")
    mysql_database: str = Field(default="rag_demo", alias="MYSQL_DATABASE")

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("api_key_ali")
    @classmethod
    def validate_api_key_ali(cls, value: str) -> str:
        api_key = value.strip()
        if not api_key:
            raise ValueError("环境变量 API_KEY_ALI 不能为空")
        return api_key

    @field_validator("mysql_host", "mysql_user", "mysql_password", "mysql_database")
    @classmethod
    def validate_mysql_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("MySQL 配置不能为空")
        return cleaned

    @field_validator("mysql_port")
    @classmethod
    def validate_mysql_port(cls, value: int) -> int:
        if value <= 0 or value > 65535:
            raise ValueError("MySQL 端口必须在 1-65535 之间")
        return value

    @field_validator("min_score")
    @classmethod
    def validate_min_score(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("RAG_MIN_SCORE 必须在 0-1 之间")
        return float(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载并缓存配置。"""
    return Settings()
