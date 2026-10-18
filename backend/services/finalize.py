import logging
import time

from config import settings
from services.bailian_tts import (
    TtsDownloadError,
    TtsMockMisconfigured,
    TtsNotConfigured,
    TtsServiceError,
    TtsTimeout,
    known_tts_mock,
    synthesize,
)
from services.reply_audio import public_audio_url, save_reply_audio
from services.reply_text import (
    ReplyMockMisconfigured,
    ReplyTimeout,
    generate_reply,
)
from services.search_store import load_first_poi

logger = logging.getLogger(__name__)

TOTAL_BUDGET_SECONDS = 45
PER_CALL_SECONDS = 15
TEXT_ONLY_WARNING = "语音暂时没有生成，可以先看文字。"


class _Deadline:
    def __init__(self) -> None:
        self.end = time.monotonic() + TOTAL_BUDGET_SECONDS
        self.stage = "reply"

    def timeout(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining < 1:
            if self.stage == "download":
                raise TtsDownloadError()
            if self.stage == "tts":
                raise TtsTimeout()
            raise ReplyTimeout()
        return min(PER_CALL_SECONDS, remaining)


def finalize_search(search_id: str) -> dict:
    poi = load_first_poi(search_id)
    _check_mocks()
    deadline = _Deadline()
    reply_text = generate_reply(poi["name"], poi["address"], deadline.timeout())
    deadline.stage = "tts"
    audio_url, warning = _try_audio(reply_text, deadline)
    return {"reply_text": reply_text, "audio_url": audio_url, "warning": warning}


def _check_mocks() -> None:
    reply_mock = settings.DEEPSEEK_REPLY_MOCK.strip().lower()
    tts_mock = settings.BAILIAN_TTS_MOCK.strip().lower()
    if reply_mock not in {"", "error", "timeout"}:
        raise ReplyMockMisconfigured()
    if not known_tts_mock(tts_mock):
        raise TtsMockMisconfigured()


def _try_audio(reply_text: str, deadline: _Deadline) -> tuple[str | None, str | None]:
    try:
        data, extension, content_type = synthesize(reply_text, deadline)
        audio_id = save_reply_audio(data, extension, content_type)
        return public_audio_url(audio_id), None
    except TtsTimeout:
        logger.info("语音合成超时，保留推荐语")
        return None, "语音合成超时，可以先看文字。"
    except TtsDownloadError:
        logger.info("语音下载失败，保留推荐语")
        return None, "语音下载失败，可以先看文字。"
    except TtsNotConfigured:
        logger.info("未配置语音密钥，保留推荐语")
        return None, "语音服务未配置，可以先看文字。"
    except TtsServiceError:
        logger.info("语音合成失败，保留推荐语")
        return None, TEXT_ONLY_WARNING
    except OSError:
        logger.info("保存语音失败，保留推荐语")
        return None, TEXT_ONLY_WARNING
