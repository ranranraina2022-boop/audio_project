import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from config import settings
from services.search_store import save_search

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AROUND_URL = "https://restapi.amap.com/v3/place/around"
_SUBWAY_PAREN = re.compile(r"([^\s()（）省市区县]{2,12})[(（]\s*地铁站\s*[)）]")
_SUBWAY_WORD = re.compile(r"([^\s()（）省市区县]{2,12})地铁站")
TOTAL_BUDGET_SECONDS = 20
PER_CALL_SECONDS = 5
FIRST_RADIUS_M = 2000
EXPANDED_RADIUS_M = 5000
MAX_POIS = 3
# 只拒绝行政区划。高德对龙翔桥实际返回「公交地铁站点」，不是文档里的「公交站台」。
COARSE_LEVELS = {"国家", "省", "市", "区县", "开发区", "乡镇", "村庄", "未知"}


class SearchNotConfigured(Exception):
    pass


class SearchMockMisconfigured(Exception):
    pass


class SearchServiceError(Exception):
    pass


class SearchTimeout(Exception):
    pass


class AmbiguousLocation(Exception):
    def __init__(self, address: str):
        super().__init__(address)
        self.address = address


class LocationNotFound(Exception):
    def __init__(self, address: str):
        super().__init__(address)
        self.address = address


class NoPoi(Exception):
    pass


class CrossCity(Exception):
    pass


@dataclass
class _Point:
    longitude: float
    latitude: float


@dataclass
class _Deadline:
    end: float

    def timeout(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining < 1:
            raise SearchTimeout()
        return min(PER_CALL_SECONDS, remaining)


def search_places(
    city_a: str,
    address_a: str,
    city_b: str,
    address_b: str,
    category: str,
) -> dict:
    if _normalize_city(city_a) != _normalize_city(city_b):
        raise CrossCity()
    mock = settings.AMAP_SEARCH_MOCK.strip().lower()
    if mock:
        return _mock_search(mock)
    api_key = settings.AMAP_API_KEY.strip()
    if not api_key:
        raise SearchNotConfigured()

    deadline = _Deadline(time.monotonic() + TOTAL_BUDGET_SECONDS)
    point_a = _locate(address_a, city_a, api_key, deadline)
    point_b = _locate(address_b, city_b, api_key, deadline)
    midpoint = _midpoint(point_a, point_b)
    pois = _search_around(midpoint, city_a, category, FIRST_RADIUS_M, api_key, deadline)
    if not pois:
        pois = _search_around(midpoint, city_a, category, EXPANDED_RADIUS_M, api_key, deadline)
    if not pois:
        raise NoPoi()
    stored = {
        "city_a": city_a,
        "address_a": address_a,
        "city_b": city_b,
        "address_b": address_b,
        "category": category,
        "midpoint": {"longitude": midpoint.longitude, "latitude": midpoint.latitude},
        "pois": pois,
    }
    search_id = save_search(stored)
    return {
        "search_id": search_id,
        "midpoint": stored["midpoint"],
        "pois": [
            {
                "name": item["name"],
                "address": item["address"],
                "distance_to_midpoint_m": item["distance_to_midpoint_m"],
            }
            for item in pois[:MAX_POIS]
        ],
    }


def _mock_search(mock: str) -> dict:
    if mock == "empty":
        raise NoPoi()
    if mock == "ambiguous":
        raise AmbiguousLocation("这个地点")
    if mock == "error":
        raise SearchServiceError()
    if mock == "timeout":
        raise SearchTimeout()
    raise SearchMockMisconfigured()


def _locate(address: str, city: str, api_key: str, deadline: _Deadline) -> _Point:
    if _subway_cores(address):
        subway = _locate_subway(address, city, api_key, deadline)
        if subway is not None:
            return subway
    payload = _amap_get(
        GEOCODE_URL,
        {"key": api_key, "address": address, "city": city},
        deadline,
    )
    geocodes = payload.get("geocodes") or []
    if not isinstance(geocodes, list):
        raise SearchServiceError()
    for item in geocodes:
        if isinstance(item, dict):
            logger.info(
                "定位候选 %s level=%s address=%s location=%s",
                address,
                item.get("level"),
                item.get("formatted_address"),
                item.get("location"),
            )
    point = _choose_geocode(address, city, geocodes)
    logger.info("定位 %s 使用经度 %s 纬度 %s", address, point.longitude, point.latitude)
    return point


def _locate_subway(address: str, city: str, api_key: str, deadline: _Deadline) -> _Point | None:
    payload = _amap_get(
        PLACE_TEXT_URL,
        {
            "key": api_key,
            "keywords": address,
            "city": city,
            "citylimit": "true",
            "offset": 20,
            "page": 1,
            "extensions": "base",
        },
        deadline,
    )
    pois = payload.get("pois") or []
    if not isinstance(pois, list):
        raise SearchServiceError()
    query_cores = _subway_cores(address)
    matched = []
    for item in pois:
        if not isinstance(item, dict):
            continue
        point = _parse_location(item.get("location"))
        if point is None or not _city_matches(city, item):
            continue
        overlap = query_cores & _subway_cores_from_item(item)
        if not overlap:
            continue
        logger.info(
            "地铁模糊候选 %s name=%s address=%s location=%s",
            address,
            item.get("name"),
            item.get("address"),
            item.get("location"),
        )
        matched.append((item, point, overlap))
    if not matched:
        return None
    found_cores = set()
    for _, _, overlap in matched:
        found_cores |= overlap
    if len(found_cores) > 1:
        raise AmbiguousLocation(address)
    core = next(iter(found_cores))
    matched.sort(key=lambda row: _subway_rank(row[0], core))
    best_rank = _subway_rank(matched[0][0], core)
    top = [row for row in matched if _subway_rank(row[0], core) == best_rank]
    if len({(row[1].longitude, row[1].latitude) for row in top}) > 1:
        raise AmbiguousLocation(address)
    point = top[0][1]
    logger.info("地铁模糊定位 %s 使用经度 %s 纬度 %s", address, point.longitude, point.latitude)
    return point


def _choose_geocode(address: str, city: str, geocodes: list) -> _Point:
    precise = []
    saw_city = False
    saw_imprecise = False
    for item in geocodes:
        if not isinstance(item, dict):
            continue
        point = _parse_location(item.get("location"))
        if point is None or not _city_matches(city, item):
            continue
        saw_city = True
        if item.get("level") in COARSE_LEVELS or not isinstance(item.get("level"), str):
            saw_imprecise = True
            continue
        precise.append((item, point))
    named = [(item, point) for item, point in precise if _name_matches(address, item)]
    # 多个候选即使相距不到 300 米，也不并成同一个地点。
    if len(named) == 1:
        return named[0][1]
    if len(named) > 1 or (precise and not named) or (saw_city and saw_imprecise and not named):
        raise AmbiguousLocation(address)
    raise LocationNotFound(address)


def _search_around(
    midpoint: _Point,
    city: str,
    category: str,
    radius: int,
    api_key: str,
    deadline: _Deadline,
) -> list[dict]:
    payload = _amap_get(
        AROUND_URL,
        {
            "key": api_key,
            "location": f"{midpoint.longitude},{midpoint.latitude}",
            "keywords": category,
            "city": city,
            "radius": radius,
            "sortrule": "distance",
            "offset": 25,
            "page": 1,
            "extensions": "base",
        },
        deadline,
    )
    raw_pois = payload.get("pois") or []
    if not isinstance(raw_pois, list):
        raise SearchServiceError()
    found = []
    for item in raw_pois:
        if not isinstance(item, dict):
            continue
        point = _parse_location(item.get("location"))
        name = item.get("name")
        address = item.get("address")
        if point is None or not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(address, str) or not address.strip():
            continue
        distance = _distance_m(midpoint, point)
        if not math.isfinite(distance) or distance > radius:
            continue
        found.append(
            {
                "name": name.strip(),
                "address": address.strip(),
                "distance_to_midpoint_m": int(round(distance)),
                "longitude": point.longitude,
                "latitude": point.latitude,
            }
        )
    found.sort(key=lambda item: (item["distance_to_midpoint_m"], item["name"]))
    return found[:MAX_POIS]


def _amap_get(url: str, params: dict, deadline: _Deadline) -> dict:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=deadline.timeout()) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        logger.info("高德请求失败，HTTP 状态 %s", exc.code)
        raise SearchServiceError() from exc
    except TimeoutError as exc:
        logger.info("高德请求超时")
        raise SearchTimeout() from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.info("高德请求超时")
            raise SearchTimeout() from exc
        logger.info("高德请求失败，网络错误")
        raise SearchServiceError() from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchServiceError() from exc
    if not isinstance(payload, dict) or payload.get("status") != "1":
        logger.info("高德返回失败，info=%s", payload.get("info") if isinstance(payload, dict) else "")
        raise SearchServiceError()
    return payload


def _midpoint(first: _Point, second: _Point) -> _Point:
    lat1 = math.radians(first.latitude)
    lat2 = math.radians(second.latitude)
    lon1 = math.radians(first.longitude)
    lon2 = math.radians(second.longitude)
    x = math.cos(lat1) * math.cos(lon1) + math.cos(lat2) * math.cos(lon2)
    y = math.cos(lat1) * math.sin(lon1) + math.cos(lat2) * math.sin(lon2)
    z = math.sin(lat1) + math.sin(lat2)
    longitude = math.degrees(math.atan2(y, x))
    latitude = math.degrees(math.atan2(z, math.hypot(x, y)))
    return _Point(round(longitude, 6), round(latitude, 6))


def _distance_m(origin: _Point, target: _Point) -> float:
    radius = 6_371_000
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(target.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(target.longitude - origin.longitude)
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(haversine))


def _parse_location(value: object) -> _Point | None:
    if not isinstance(value, str) or "," not in value:
        return None
    left, right = value.split(",", 1)
    try:
        longitude = float(left)
        latitude = float(right)
    except ValueError:
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return _Point(longitude, latitude)


def _city_matches(expected: str, item: dict) -> bool:
    wanted = _normalize_city(expected)
    if not wanted:
        return False
    parts = []
    for key in ("province", "city", "district", "formatted_address", "pname", "cityname", "adname"):
        parts.extend(_text_parts(item.get(key)))
    return wanted in _normalize_city("".join(parts))


def _text_parts(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for part in value if isinstance(part, str)]
    return []


def _name_matches(address: str, item: dict) -> bool:
    query_cores = _subway_cores(address)
    if query_cores:
        return bool(query_cores & _subway_cores_from_item(item))
    needle = _distinctive_place(address)
    if len(needle) < 2:
        return False
    for key in ("formatted_address", "name", "address"):
        value = item.get(key)
        if isinstance(value, str) and needle in _distinctive_place(value):
            return True
    return False


def _subway_cores(text: str) -> set[str]:
    cores = set()
    for pattern in (_SUBWAY_PAREN, _SUBWAY_WORD):
        cores.update(_trim_place_prefix(core) for core in pattern.findall(text))
    return {core for core in cores if len(core) >= 2}


def _subway_cores_from_item(item: dict) -> set[str]:
    cores = set()
    for key in ("name", "formatted_address", "address"):
        for part in _text_parts(item.get(key)):
            cores |= _subway_cores(part)
    return cores


def _trim_place_prefix(name: str) -> str:
    for prefix in ("请到", "去往", "走到", "到", "去", "在", "从", "往"):
        if name.startswith(prefix) and len(name) - len(prefix) >= 2:
            return name[len(prefix) :]
    return name


def _subway_rank(item: dict, core: str) -> int:
    names = _text_parts(item.get("name")) + _text_parts(item.get("formatted_address"))
    for name in names:
        compact = re.sub(r"\s+", "", name)
        if compact in {f"{core}(地铁站)", f"{core}（地铁站）", f"{core}地铁站"}:
            return 0
    if any("地铁站" in name for name in names):
        return 1
    return 2


def _loose_text(text: str) -> str:
    return re.sub(r"[\s()（）\[\]【】{}<>《》·,，.。、/\\\-—_]", "", text.strip())


def _distinctive_place(text: str) -> str:
    folded = _loose_text(text)
    folded = folded.replace("地铁站", "站").replace("公交站", "站")
    folded = folded.replace("地铁", "").replace("公交", "")
    if folded.endswith("站") and len(folded) > 1:
        folded = folded[:-1]
    return folded


def _normalize_city(city: str) -> str:
    text = city.strip().replace(" ", "")
    if text.endswith("市") and len(text) > 1:
        return text[:-1]
    return text
