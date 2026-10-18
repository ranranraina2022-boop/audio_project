import logging

from fastapi import APIRouter, Request

from schemas import ApiError, ErrorResponse, ExtractRequest, ExtractResponse, success_response
from services.extract import (
    ExtractIncomplete,
    ExtractModelError,
    ExtractNotConfigured,
    ExtractServiceError,
    ExtractTimeout,
    extract_meeting,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extract"])

INCOMPLETE_ERRORS = {
    "party_count": (422, "party_count", "请一次说清楚两个人分别在哪里。"),
    "missing_address": (422, "missing_address", "有一个地点没说清楚，请重新说。"),
    "vague_address": (422, "vague_address", "地点太含糊，请说出具体地点。"),
    "cross_city": (422, "cross_city", "两个人不在同一座城市，请重新说。"),
    "missing_category": (422, "missing_category", "请说想找什么店，比如咖啡店。"),
}


@router.post(
    "/extract",
    response_model=ExtractResponse,
    responses={
        422: {"model": ErrorResponse, "description": "口述信息不完整"},
        502: {"model": ErrorResponse, "description": "模型格式异常或服务失败"},
        503: {"model": ErrorResponse, "description": "未配置 DeepSeek 密钥"},
        504: {"model": ErrorResponse, "description": "提取超时"},
    },
)
def extract_places(request: Request, body: ExtractRequest) -> dict:
    text = body.text.strip()
    city = body.city.strip()
    if not text or not city:
        raise ApiError(422, "invalid_request", "请提供口述内容和页面上的城市。", "request")

    try:
        data = extract_meeting(text, city)
    except ExtractIncomplete as exc:
        status_code, code, message = INCOMPLETE_ERRORS[exc.reason]
        raise ApiError(status_code, code, message, "extract") from exc
    except ExtractModelError as exc:
        logger.info("extract 模型格式异常")
        raise ApiError(502, "extract_invalid_response", "地点理解暂时失败，请稍后再试。", "extract") from exc
    except ExtractTimeout as exc:
        raise ApiError(504, "extract_timeout", "地点理解超时，请稍后再试。", "extract") from exc
    except ExtractServiceError as exc:
        raise ApiError(502, "extract_failed", "地点理解暂时失败，请稍后再试。", "extract") from exc
    except ExtractNotConfigured as exc:
        raise ApiError(503, "extract_not_configured", "地点理解服务未配置，请先填写 DeepSeek 密钥。", "extract") from exc

    return success_response(request, data)
