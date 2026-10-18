import logging

from fastapi import APIRouter, Request

from schemas import ApiError, AsrRequest, AsrResponse, ErrorResponse, success_response
from services.audio_store import (
    InvalidAudioId,
    RecordingExpired,
    RecordingNotFound,
    load_recording,
)
from services.bailian_asr import (
    AsrEmptyResult,
    AsrMockMisconfigured,
    AsrNotConfigured,
    AsrServiceError,
    AsrTimeout,
    AudioPayloadTooLarge,
    transcribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["asr"])


@router.post(
    "/asr",
    response_model=AsrResponse,
    responses={
        404: {"model": ErrorResponse, "description": "找不到录音"},
        410: {"model": ErrorResponse, "description": "录音已超过 24 小时"},
        413: {"model": ErrorResponse, "description": "Base64 后超过限制"},
        422: {"model": ErrorResponse, "description": "编号不正确或没有识别到文字"},
        502: {"model": ErrorResponse, "description": "识别服务失败"},
        503: {"model": ErrorResponse, "description": "识别服务未配置"},
        504: {"model": ErrorResponse, "description": "识别超时"},
    },
)
def recognize_audio(request: Request, body: AsrRequest) -> dict:
    try:
        audio = load_recording(body.audio_id)
    except InvalidAudioId as exc:
        raise ApiError(422, "invalid_audio_id", "录音编号不正确。", "asr") from exc
    except RecordingNotFound as exc:
        raise ApiError(404, "audio_not_found", "找不到这支录音，请重新上传。", "asr") from exc
    except RecordingExpired as exc:
        raise ApiError(410, "audio_expired", "这支录音已超过 24 小时，请重新上传。", "asr") from exc

    try:
        text = transcribe(audio)
    except AudioPayloadTooLarge as exc:
        raise ApiError(413, "audio_too_large", "录音编码后超过 10MB，无法识别。", "asr") from exc
    except AsrEmptyResult as exc:
        raise ApiError(422, "empty_transcript", "没有识别到文字，请重新说一遍。", "asr") from exc
    except AsrTimeout as exc:
        raise ApiError(504, "asr_timeout", "语音识别超时，请稍后再试。", "asr") from exc
    except AsrServiceError as exc:
        raise ApiError(502, "asr_failed", "语音识别暂时失败，请稍后再试。", "asr") from exc
    except AsrNotConfigured as exc:
        raise ApiError(503, "asr_not_configured", "语音识别服务未配置，请先填写百炼密钥。", "asr") from exc
    except AsrMockMisconfigured as exc:
        raise ApiError(
            503,
            "asr_not_configured",
            "模拟识别的配置不正确。只接受 empty、error、timeout。",
            "asr",
        ) from exc

    logger.info("识别完成，audio_id=%s", body.audio_id)
    return success_response(request, {"text": text})
