from typing import Any

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.config import Settings


def connect(settings: Settings) -> Connection:
    """创建一个 MySQL 连接，供监控与测评存储层复用。"""
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def to_json(value: Any) -> str | None:
    """将 Python 对象序列化为 JSON 字符串，保留中文。"""
    import json

    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def from_json(value: Any) -> Any:
    """将 MySQL JSON 字段解析为 Python 对象。"""
    import json

    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return None
