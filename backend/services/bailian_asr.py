import base64
import json
import logging
import urllib.error
import urllib.request

from config import settings

logger = logging.getLogger(__name__)

# 华北2（北京）仍可使用的域名。业务空间专属域名需要 WorkspaceId，当前只配置了密钥。
ASR_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
ASR_MODEL = "qwen3-asr-flash"
ASR_TIMEOUT_SECONDS = 60
# 百炼要求 Base64 之后的音频仍不超过 10MB。
MAX_BASE64_BYTES = 10 * 1024 * 1024


class AudioPayloadTooLarge(Exception):
    pass


class AsrNotConfigured(Exception):
    pass


class AsrMockMisconfigured(Exception):
    pass


class AsrEmptyResult(Exception):
    pass


class AsrServiceError(Exception):
    pass


class AsrTimeout(Exception):
    pass


def transcribe(audio: bytes) -> str:
    encoded = base64.b64encode(audio).decode("ascii")
    if len(encoded.encode("ascii")) > MAX_BASE64_BYTES:
        raise AudioPayloadTooLarge()
    mock = settings.BAILIAN_ASR_MOCK.strip().lower()
    if mock:
        return _mock_transcribe(mock)
    api_key = settings.BAILIAN_API_KEY.strip()
    if not api_key:
        raise AsrNotConfigured()
    return _request_bailian(encoded, api_key)


def _mock_transcribe(mock: str) -> str:
    if mock == "empty":
        raise AsrEmptyResult()
    if mock == "error":
        raise AsrServiceError()
    if mock == "timeout":
        raise AsrTimeout()
    raise AsrMockMisconfigured()


def _request_bailian(encoded_audio: str, api_key: str) -> str:
    payload = {
        "model": ASR_MODEL,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"audio": f"data:audio/webm;base64,{encoded_audio}"}],
                }
            ]
        },
        "parameters": {"asr_options": {"language": "zh", "enable_itn": False}},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ASR_URL,
        data=raw_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=ASR_TIMEOUT_SECONDS) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        logger.info("百炼识别失败，HTTP 状态 %s", exc.code)
        raise AsrServiceError() from exc
    except TimeoutError as exc:
        logger.info("百炼识别超时")
        raise AsrTimeout() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("百炼识别超时")
            raise AsrTimeout() from exc
        logger.info("百炼识别失败，网络错误")
        raise AsrServiceError() from exc

    text = _read_transcript(response_body)
    if not text.strip():
        raise AsrEmptyResult()
    return text


def _read_transcript(response_body: bytes) -> str:
    try:
        payload = json.loads(response_body.decode("utf-8"))
        content = payload["output"]["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        logger.info("百炼识别结果无法解析")
        raise AsrServiceError() from exc
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise AsrServiceError()
    parts = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)
