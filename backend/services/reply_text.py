import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "reply.txt"
MAX_REPLY_CHARS = 600


class ReplyNotConfigured(Exception):
    pass


class ReplyMockMisconfigured(Exception):
    pass


class ReplyModelError(Exception):
    pass


class ReplyServiceError(Exception):
    pass


class ReplyTimeout(Exception):
    pass


def generate_reply(name: str, address: str, timeout: float) -> str:
    mock = settings.DEEPSEEK_REPLY_MOCK.strip().lower()
    if mock:
        return _mock_reply(mock)
    api_key = settings.DEEPSEEK_API_KEY.strip()
    if not api_key:
        raise ReplyNotConfigured()
    raw = _request_deepseek(name, address, api_key, timeout)
    logger.info("finalize 推荐语原始输出: %s", raw)
    reply = _parse_reply(raw, name, address)
    logger.info("finalize 推荐语: %s", reply)
    return reply


def _mock_reply(mock: str) -> str:
    if mock == "error":
        raise ReplyServiceError()
    if mock == "timeout":
        raise ReplyTimeout()
    raise ReplyMockMisconfigured()


def _request_deepseek(name: str, address: str, api_key: str, timeout: float) -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"店名：{name}\n地址：{address}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        logger.info("推荐语生成失败，HTTP 状态 %s", exc.code)
        raise ReplyServiceError() from exc
    except TimeoutError as exc:
        logger.info("推荐语生成超时")
        raise ReplyTimeout() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("推荐语生成超时")
            raise ReplyTimeout() from exc
        logger.info("推荐语生成失败，网络错误")
        raise ReplyServiceError() from exc
    try:
        body = json.loads(response_body.decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ReplyModelError() from exc
    if not isinstance(content, str) or not content.strip():
        raise ReplyModelError()
    return content


def _parse_reply(raw: str, name: str, address: str) -> str:
    try:
        parsed = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise ReplyModelError() from exc
    reply = parsed.get("reply_text") if isinstance(parsed, dict) else None
    if not isinstance(reply, str):
        raise ReplyModelError()
    reply = reply.strip()
    if not reply or len(reply) > MAX_REPLY_CHARS or name not in reply or address not in reply:
        raise ReplyModelError()
    return reply


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    return text.strip()
