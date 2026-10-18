import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from config import settings

logger = logging.getLogger(__name__)

TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
TTS_MODEL = "qwen3-tts-flash"
MAX_AUDIO_BYTES = 5 * 1024 * 1024


class TtsNotConfigured(Exception):
    pass


class TtsMockMisconfigured(Exception):
    pass


class TtsServiceError(Exception):
    pass


class TtsTimeout(Exception):
    pass


class TtsDownloadError(Exception):
    pass


def synthesize(text: str, deadline) -> tuple[bytes, str, str]:
    mock = settings.BAILIAN_TTS_MOCK.strip().lower()
    if mock:
        _mock_tts(mock)
    api_key = settings.BAILIAN_API_KEY.strip()
    if not api_key:
        raise TtsNotConfigured()
    deadline.stage = "tts"
    audio_url = _request_tts(text, api_key, deadline.timeout())
    deadline.stage = "download"
    data = _download_audio(audio_url, deadline.timeout())
    detected = detect_audio(data)
    if detected is None:
        logger.info("语音下载内容不是可识别的音频，字节数 %s", len(data))
        raise TtsDownloadError()
    extension, content_type = detected
    logger.info("语音已下载，格式 %s，类型 %s，字节数 %s", extension, content_type, len(data))
    return data, extension, content_type


def known_tts_mock(value: str) -> bool:
    return value in {"", "error", "timeout", "download"}


def _mock_tts(mock: str) -> None:
    if mock == "error":
        raise TtsServiceError()
    if mock == "timeout":
        raise TtsTimeout()
    if mock == "download":
        raise TtsDownloadError()
    raise TtsMockMisconfigured()


def _request_tts(text: str, api_key: str, timeout: float) -> str:
    payload = {
        "model": TTS_MODEL,
        "input": {"text": text, "voice": "Cherry", "language_type": "Chinese"},
    }
    request = urllib.request.Request(
        TTS_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        logger.info("语音合成失败，HTTP 状态 %s", exc.code)
        raise TtsServiceError() from exc
    except TimeoutError as exc:
        logger.info("语音合成超时")
        raise TtsTimeout() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("语音合成超时")
            raise TtsTimeout() from exc
        logger.info("语音合成失败，网络错误")
        raise TtsServiceError() from exc
    try:
        payload = json.loads(body.decode("utf-8"))
        audio_url = payload["output"]["audio"]["url"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TtsServiceError() from exc
    if not isinstance(audio_url, str) or not audio_url:
        raise TtsServiceError()
    return audio_url


def _download_audio(audio_url: str, timeout: float) -> bytes:
    _ensure_vendor_audio_url(audio_url)
    request = urllib.request.Request(audio_url, headers={"User-Agent": "meetup-audio/0.1"}, method="GET")
    opener = urllib.request.build_opener(_CheckedRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            chunks = []
            total = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_AUDIO_BYTES:
                    raise TtsDownloadError()
                chunks.append(block)
    except TtsDownloadError:
        raise
    except TimeoutError as exc:
        logger.info("语音下载超时")
        raise TtsDownloadError() from exc
    except urllib.error.HTTPError as exc:
        logger.info("语音下载失败，HTTP 状态 %s", exc.code)
        raise TtsDownloadError() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("语音下载超时")
            raise TtsDownloadError() from exc
        logger.info("语音下载失败，网络错误")
        raise TtsDownloadError() from exc
    return b"".join(chunks)


def detect_audio(data: bytes) -> tuple[str, str] | None:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if data.startswith(b"ID3") or _looks_like_mp3(data):
        return "mp3", "audio/mpeg"
    if data.startswith(b"OggS"):
        return "ogg", "audio/ogg"
    if data.startswith(b"fLaC"):
        return "flac", "audio/flac"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a", "audio/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm", "audio/webm"
    return None


def _looks_like_mp3(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def _ensure_vendor_audio_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    allowed = (
        parsed.scheme in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and host.startswith("dashscope-result-")
        and host.endswith(".aliyuncs.com")
    )
    if not allowed:
        logger.warning("语音地址不在百炼结果域名内，协议 %s，主机 %s", parsed.scheme, host)
        raise TtsDownloadError()


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_vendor_audio_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
