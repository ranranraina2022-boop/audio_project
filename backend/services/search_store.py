import json
import re
import uuid
from datetime import datetime, timezone

from config import STORAGE_DIR

SEARCH_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def save_search(result: dict) -> str:
    root = (STORAGE_DIR / "searches").resolve()
    root.mkdir(parents=True, exist_ok=True)
    search_id = uuid.uuid4().hex
    path = (root / f"{search_id}.json").resolve()
    if path.parent != root:
        raise RuntimeError("找店结果保存位置无效")
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "search_id": search_id,
        **result,
    }
    partial = root / f"{search_id}.json.partial"
    partial.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)
    return search_id


class InvalidSearchId(Exception):
    pass


class SearchNotFound(Exception):
    pass


class SearchHasNoPoi(Exception):
    pass


def load_first_poi(search_id: str) -> dict[str, str]:
    if not SEARCH_ID_PATTERN.fullmatch(search_id):
        raise InvalidSearchId()
    root = (STORAGE_DIR / "searches").resolve()
    path = (root / f"{search_id}.json").resolve()
    if path.parent != root or not path.is_file():
        raise SearchNotFound()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SearchNotFound() from exc
    pois = payload.get("pois") if isinstance(payload, dict) else None
    if not isinstance(pois, list) or not pois or not isinstance(pois[0], dict):
        raise SearchHasNoPoi()
    first = pois[0]
    name = first.get("name")
    address = first.get("address")
    distance = first.get("distance_to_midpoint_m")
    if not isinstance(name, str) or not isinstance(address, str):
        raise SearchHasNoPoi()
    name = name.strip()
    address = address.strip()
    if not name or not address or isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise SearchHasNoPoi()
    return {"name": name, "address": address}
