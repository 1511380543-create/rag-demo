from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models import ErrorResponse, HealthResponse, IndexRequest, IndexResponse, QueryRequest, QueryResponse
from app.rag_service import IndexNotReadyError, RagService


def _load_settings():
    try:
        return get_settings()
    except Exception as exc:  # noqa: BLE001
        # 启动阶段明确要求 API_KEY_ALI 存在，缺失时直接阻止服务启动。
        raise RuntimeError("缺少必要环境变量 API_KEY_ALI，请先设置后再启动服务") from exc


settings = _load_settings()
rag_service = RagService(settings=settings)
app = FastAPI(title="RAG Service", version="0.1.0")


def _error_response(status_code: int, error_code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    payload = ErrorResponse(error_code=error_code, message=message, detail=detail)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        status_code=422,
        error_code="VALIDATION_ERROR",
        message="请求参数校验失败",
        detail={"errors": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return _error_response(
            status_code=exc.status_code,
            error_code=str(exc.detail.get("error_code", "HTTP_ERROR")),
            message=str(exc.detail.get("message", "请求处理失败")),
            detail=exc.detail.get("detail"),
        )
    return _error_response(status_code=exc.status_code, error_code="HTTP_ERROR", message=str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        status_code=500,
        error_code="INTERNAL_ERROR",
        message="服务内部异常",
        detail={"reason": str(exc)},
    )


@app.post("/rag/index", response_model=IndexResponse)
async def index_documents(request: IndexRequest) -> IndexResponse:
    try:
        indexed_count, chunk_count, index_name = rag_service.index_documents(request.documents)
        return IndexResponse(indexed_count=indexed_count, chunk_count=chunk_count, index_name=index_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "本地文档读取失败，请检查 file_path 与文档格式",
                "detail": {"reason": str(exc)},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "INDEX_BUILD_ERROR",
                "message": "索引构建异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.post("/rag/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    try:
        return rag_service.query(request)
    except IndexNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INDEX_NOT_READY", "message": str(exc), "detail": None},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "QUERY_EXECUTION_ERROR",
                "message": "检索过程异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.get("/rag/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return rag_service.health()
