from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models import (
    BuildIndexRequest,
    BuildIndexResponse,
    ChunkIngestResponse,
    ErrorResponse,
    EvalDatasetListResponse,
    EvalDatasetUpsertRequest,
    EvalDatasetUpsertResponse,
    EvalRunListResponse,
    EvalRunRequest,
    EvalRunResponse,
    HealthResponse,
    IndexRequest,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
)
from app.rag_service import EvalDatasetEmptyError, IndexNotReadyError, NoChunksAvailableError, RagService


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
    # Pydantic 的 errors() 里可能包含 ValueError 对象，需要先转为可 JSON 序列化结构。
    safe_errors = jsonable_encoder(exc.errors())
    return _error_response(
        status_code=422,
        error_code="VALIDATION_ERROR",
        message="请求参数校验失败",
        detail={"errors": safe_errors},
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


@app.post("/rag/chunks", response_model=ChunkIngestResponse)
async def ingest_chunks(request: IndexRequest) -> ChunkIngestResponse:
    try:
        stored_doc_count, stored_chunk_count = rag_service.ingest_documents(request.documents)
        return ChunkIngestResponse(stored_doc_count=stored_doc_count, stored_chunk_count=stored_chunk_count)
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
                "error_code": "CHUNK_INGEST_ERROR",
                "message": "文档切分或 MySQL 写入异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.post("/rag/index/build", response_model=BuildIndexResponse)
async def build_index(request: BuildIndexRequest) -> BuildIndexResponse:
    try:
        indexed_doc_count, indexed_chunk_count, index_name = rag_service.build_index(request)
        return BuildIndexResponse(
            indexed_doc_count=indexed_doc_count,
            indexed_chunk_count=indexed_chunk_count,
            index_name=index_name,
        )
    except NoChunksAvailableError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "NO_CHUNKS_FOR_INDEX",
                "message": str(exc),
                "detail": None,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "索引构建参数非法",
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


@app.get("/rag/metrics", response_model=MetricsResponse)
async def metrics(window_minutes: int | None = Query(default=None, ge=1)) -> MetricsResponse:
    try:
        return rag_service.get_metrics(window_minutes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "METRICS_READ_ERROR",
                "message": "监控数据读取异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.post("/rag/eval/dataset", response_model=EvalDatasetUpsertResponse)
async def upsert_eval_dataset(request: EvalDatasetUpsertRequest) -> EvalDatasetUpsertResponse:
    try:
        upserted_count = rag_service.upsert_eval_dataset(request.cases)
        return EvalDatasetUpsertResponse(upserted_count=upserted_count)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "EVAL_DATASET_UPSERT_ERROR",
                "message": "评测样本写入异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.get("/rag/eval/dataset", response_model=EvalDatasetListResponse)
async def list_eval_dataset() -> EvalDatasetListResponse:
    try:
        return rag_service.list_eval_dataset()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "EVAL_DATASET_READ_ERROR",
                "message": "评测样本读取异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.post("/rag/eval/run", response_model=EvalRunResponse)
async def run_eval(request: EvalRunRequest) -> EvalRunResponse:
    try:
        return rag_service.run_eval(request)
    except IndexNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INDEX_NOT_READY", "message": str(exc), "detail": None},
        ) from exc
    except EvalDatasetEmptyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "EVAL_DATASET_EMPTY", "message": str(exc), "detail": None},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "评测参数非法",
                "detail": {"reason": str(exc)},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "EVAL_RUN_ERROR",
                "message": "评测执行异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc


@app.get("/rag/eval/runs", response_model=EvalRunListResponse)
async def list_eval_runs(limit: int = Query(default=20, ge=1, le=100)) -> EvalRunListResponse:
    try:
        return rag_service.list_eval_runs(limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "EVAL_RUNS_READ_ERROR",
                "message": "评测历史读取异常",
                "detail": {"reason": str(exc)},
            },
        ) from exc
