from fastapi import APIRouter, Request
from fastapi.responses import Response

from schemas import (
    ApiError,
    ErrorResponse,
    FinalizeRequest,
    FinalizeResponse,
    success_response,
)
from services.bailian_tts import TtsMockMisconfigured, detect_audio
from services.finalize import finalize_search
from services.reply_audio import InvalidReplyAudioId, ReplyAudioNotFound, load_reply_audio
from services.reply_text import (
    ReplyMockMisconfigured,
    ReplyModelError,
    ReplyNotConfigured,
    ReplyServiceError,
    ReplyTimeout,
)
from services.search_store import InvalidSearchId, SearchHasNoPoi, SearchNotFound

router = APIRouter(tags=["finalize"])


@router.post(
    "/finalize",
    response_model=FinalizeResponse,
    responses={
        404: {"model": ErrorResponse, "description": "找不到找店结果"},
        422: {"model": ErrorResponse, "description": "编号不正确或没有可用的店"},
        502: {"model": ErrorResponse, "description": "推荐语生成失败"},
        503: {"model": ErrorResponse, "description": "推荐语服务未配置"},
        504: {"model": ErrorResponse, "description": "推荐语生成超时"},
    },
)
def finalize_meeting(request: Request, body: FinalizeRequest) -> dict:
    search_id = body.search_id.strip()
    if not search_id:
        raise ApiError(422, "invalid_request", "请提供找店编号。", "request")
    try:
        data = finalize_search(search_id)
    except InvalidSearchId as exc:
        raise ApiError(422, "invalid_search_id", "找店编号不正确。", "finalize") from exc
    except SearchNotFound as exc:
        raise ApiError(404, "search_not_found", "没有找到这次找店结果，请重新找店。", "finalize") from exc
    except SearchHasNoPoi as exc:
        raise ApiError(422, "no_poi", "这次找店没有可用的店。", "finalize") from exc
    except ReplyTimeout as exc:
        raise ApiError(504, "reply_timeout", "推荐语生成超时，请稍后再试。", "finalize") from exc
    except ReplyModelError as exc:
        raise ApiError(502, "reply_invalid", "推荐语暂时生成失败，请稍后再试。", "finalize") from exc
    except ReplyServiceError as exc:
        raise ApiError(502, "reply_failed", "推荐语暂时生成失败，请稍后再试。", "finalize") from exc
    except ReplyNotConfigured as exc:
        raise ApiError(503, "reply_not_configured", "推荐语服务未配置，请先填写 DeepSeek 密钥。", "finalize") from exc
    except (ReplyMockMisconfigured, TtsMockMisconfigured) as exc:
        raise ApiError(
            503,
            "reply_not_configured",
            "模拟推荐的配置不正确。推荐语只接受 error、timeout；语音只接受 error、timeout、download。",
            "finalize",
        ) from exc
    return success_response(request, data)


@router.get(
    "/audio/{audio_id}",
    responses={
        200: {"content": {"audio/wav": {}, "audio/mpeg": {}, "audio/ogg": {}, "audio/mp4": {}}},
        404: {"model": ErrorResponse, "description": "找不到语音"},
        422: {"model": ErrorResponse, "description": "音频编号不正确"},
    },
)
def read_reply_audio(audio_id: str) -> Response:
    try:
        data, extension = load_reply_audio(audio_id)
    except InvalidReplyAudioId as exc:
        raise ApiError(422, "invalid_audio_id", "音频编号不正确。", "audio") from exc
    except ReplyAudioNotFound as exc:
        raise ApiError(404, "audio_not_found", "没有找到这段语音。", "audio") from exc
    detected = detect_audio(data)
    if detected is None or detected[0] != extension:
        raise ApiError(404, "audio_not_found", "没有找到这段语音。", "audio")
    return Response(
        content=data,
        media_type=detected[1],
        headers={"Content-Disposition": f'inline; filename="reply.{detected[0]}"'},
    )
