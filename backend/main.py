import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.health import router as health_router
from config import settings
from schemas import error_response

logger = logging.getLogger(__name__)

app = FastAPI(title="语音约碰面地点", version="0.1.0")
app.state.settings = settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    return await call_next(request)


def _framework_error(status_code: int) -> tuple[int, str, str, str]:
    if status_code == 404:
        return 404, "not_found", "接口不存在", "request"
    if status_code == 405:
        return 405, "method_not_allowed", "请求方法不支持", "request"
    if status_code >= 500:
        return status_code, "internal_error", "服务暂时不可用，请稍后再试", "server"
    return status_code, "request_failed", "请求失败", "request"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    status_code, code, message, stage = _framework_error(exc.status_code)
    return JSONResponse(
        status_code=status_code,
        content=error_response(request, code, message, stage),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_response(request, "invalid_request", "请求参数不正确", "request"),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理的异常")
    return JSONResponse(
        status_code=500,
        content=error_response(
            request, "internal_error", "服务暂时不可用，请稍后再试", "server"
        ),
    )


app.include_router(health_router)
