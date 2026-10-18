import logging

from fastapi import APIRouter, File, Request, UploadFile

from schemas import ApiError, ErrorResponse, UploadResponse, success_response
from services.audio_store import save_recording
from services.webm_opus import AudioFormatError, measure_webm_opus_duration_us

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])

MAX_AUDIO_BYTES = 5 * 1024 * 1024
MIN_DURATION_US = 1_000_000
MAX_DURATION_US = 60_000_000


@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={
        413: {"model": ErrorResponse, "description": "文件过大"},
        415: {"model": ErrorResponse, "description": "格式不支持"},
        422: {"model": ErrorResponse, "description": "时长不合规"},
    },
)
async def upload_audio(request: Request, file: UploadFile = File(...)) -> dict:
    payload = await _read_limited(file)
    if not payload:
        raise ApiError(415, "unsupported_format", "只支持 WebM/Opus 录音，请重新录制。", "upload")
    try:
        duration_us = measure_webm_opus_duration_us(payload)
    except AudioFormatError as exc:
        logger.info("上传格式未通过: %s", exc)
        raise ApiError(
            415, "unsupported_format", "只支持 WebM/Opus 录音，请重新录制。", "upload"
        ) from exc
    if duration_us < MIN_DURATION_US or duration_us > MAX_DURATION_US:
        raise ApiError(
            422, "invalid_duration", "录音时长需要在 1 到 60 秒之间。", "upload"
        )
    audio_id = save_recording(payload)
    return success_response(request, {"audio_id": audio_id})


async def _read_limited(file: UploadFile) -> bytes:
    chunks = []
    total = 0
    try:
        while True:
            piece = await file.read(64 * 1024)
            if not piece:
                break
            total += len(piece)
            if total > MAX_AUDIO_BYTES:
                raise ApiError(413, "file_too_large", "录音文件不能超过 5MB。", "upload")
            chunks.append(piece)
    finally:
        await file.close()
    return b"".join(chunks)
