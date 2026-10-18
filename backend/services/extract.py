import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
EXTRACT_TIMEOUT_SECONDS = 30
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract.txt"

REQUIRED_KEYS = {
    "party_count",
    "city_a",
    "address_a",
    "city_a_spoken",
    "city_b",
    "address_b",
    "city_b_spoken",
    "address_a_vague",
    "address_b_vague",
    "category",
    "incomplete_reason",
}

VAGUE_ADDRESSES = {
    "家",
    "我家",
    "我家里",
    "家里",
    "家附近",
    "我家附近",
    "公司",
    "我公司",
    "公司附近",
    "单位",
    "单位附近",
    "朋友家",
    "这边",
    "那边",
    "这里",
    "那里",
    "附近",
    "随便",
    "某个地方",
    "某处",
}

CATEGORY_ALIASES = {
    "咖啡": "咖啡店",
    "咖啡店": "咖啡店",
    "咖啡馆": "咖啡店",
    "咖啡厅": "咖啡店",
    "cafe": "咖啡店",
    "coffee": "咖啡店",
    "奶茶": "茶饮店",
    "奶茶店": "茶饮店",
    "茶饮": "茶饮店",
    "茶饮店": "茶饮店",
    "餐厅": "餐厅",
    "饭店": "餐厅",
    "餐馆": "餐厅",
    "吃饭": "餐厅",
    "火锅": "餐厅",
    "书店": "书店",
    "酒吧": "酒吧",
    "面包": "面包店",
    "面包店": "面包店",
    "甜品": "甜品店",
    "甜品店": "甜品店",
}

GENERIC_CATEGORIES = {"店", "地方", "好吃的", "喝的", "吃的", "东西", "店铺", "商店", "碰面", "见面"}


class ExtractNotConfigured(Exception):
    pass


class ExtractModelError(Exception):
    pass


class ExtractServiceError(Exception):
    pass


class ExtractTimeout(Exception):
    pass


class ExtractIncomplete(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def extract_meeting(text: str, page_city: str) -> dict[str, str]:
    api_key = settings.DEEPSEEK_API_KEY.strip()
    if not api_key:
        raise ExtractNotConfigured()
    raw = _request_deepseek(text, page_city, api_key)
    logger.info("extract 模型原始输出: %s", raw)
    parsed = _parse_model_output(raw)
    result = _apply_business_rules(parsed, page_city)
    logger.info("extract 最终结果: %s", result)
    return result


def _request_deepseek(text: str, page_city: str, api_key: str) -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"页面城市：{page_city}\n口述：{text}"},
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
        with urllib.request.urlopen(request, timeout=EXTRACT_TIMEOUT_SECONDS) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        logger.info("DeepSeek 提取失败，HTTP 状态 %s", exc.code)
        raise ExtractServiceError() from exc
    except TimeoutError as exc:
        logger.info("DeepSeek 提取超时")
        raise ExtractTimeout() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("DeepSeek 提取超时")
            raise ExtractTimeout() from exc
        logger.info("DeepSeek 提取失败，网络错误")
        raise ExtractServiceError() from exc

    try:
        body = json.loads(response_body.decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ExtractModelError() from exc
    if not isinstance(content, str) or not content.strip():
        raise ExtractModelError()
    return content


def _parse_model_output(raw: str) -> dict:
    try:
        parsed = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise ExtractModelError() from exc
    if not isinstance(parsed, dict) or not REQUIRED_KEYS.issubset(parsed):
        raise ExtractModelError()
    if not _valid_party_count(parsed["party_count"]):
        raise ExtractModelError()
    for key in ("city_a", "address_a", "city_b", "address_b", "category", "incomplete_reason"):
        if not _nullable_string(parsed[key]):
            raise ExtractModelError()
    for key in ("city_a_spoken", "city_b_spoken", "address_a_vague", "address_b_vague"):
        if not isinstance(parsed[key], bool):
            raise ExtractModelError()
    return parsed


def _apply_business_rules(parsed: dict, page_city: str) -> dict[str, str]:
    if parsed["party_count"] != 2:
        raise ExtractIncomplete("party_count")
    if parsed["address_a_vague"] or parsed["address_b_vague"]:
        raise ExtractIncomplete("vague_address")
    if _is_vague_address(parsed["address_a"]) or _is_vague_address(parsed["address_b"]):
        raise ExtractIncomplete("vague_address")
    address_a = _clean_text(parsed["address_a"])
    address_b = _clean_text(parsed["address_b"])
    if not address_a or not address_b:
        raise ExtractIncomplete("missing_address")

    city_a = _resolve_city(parsed["city_a"], parsed["city_a_spoken"], page_city)
    city_b = _resolve_city(parsed["city_b"], parsed["city_b_spoken"], page_city)
    if city_a != city_b:
        raise ExtractIncomplete("cross_city")

    category = _normalize_category(parsed["category"])
    if not category:
        raise ExtractIncomplete("missing_category")
    return {
        "city_a": city_a,
        "address_a": address_a,
        "city_b": city_b,
        "address_b": address_b,
        "category": category,
    }


def _resolve_city(spoken_city: str | None, spoken: bool, page_city: str) -> str:
    if spoken:
        if not _clean_text(spoken_city):
            raise ExtractModelError()
        return _normalize_city(spoken_city or "")
    return _normalize_city(page_city)


def _normalize_city(city: str) -> str:
    text = city.strip().replace(" ", "")
    if text.endswith("市") and len(text) > 1:
        return text[:-1]
    return text


def _normalize_category(category: str | None) -> str:
    text = _clean_text(category)
    if not text:
        return ""
    alias = CATEGORY_ALIASES.get(text.casefold(), CATEGORY_ALIASES.get(text))
    if alias:
        return alias
    if text in GENERIC_CATEGORIES:
        return ""
    return text


def _is_vague_address(address: str | None) -> bool:
    text = _clean_text(address).replace(" ", "")
    if not text or text in VAGUE_ADDRESSES:
        return bool(text)
    for suffix in ("附近", "旁边", "边上"):
        if text.endswith(suffix):
            remain = text[: -len(suffix)]
            return remain in {"", "家", "我", "我家", "公司", "单位", "朋友家"}
    return False


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _nullable_string(value: object) -> bool:
    return value is None or isinstance(value, str)


def _valid_party_count(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    return text.strip()
