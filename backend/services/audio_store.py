import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from config import STORAGE_DIR

AUDIO_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RECORDING_TTL = timedelta(hours=24)


def save_recording(data: bytes) -> str:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    audio_id = uuid.uuid4().hex
    audio_path = (STORAGE_DIR / f"{audio_id}.webm").resolve()
    meta_path = (STORAGE_DIR / f"{audio_id}.json").resolve()
    storage_root = STORAGE_DIR.resolve()
    if audio_path.parent != storage_root or meta_path.parent != storage_root:
        raise RuntimeError("录音保存位置无效")

    partial_path = storage_root / f"{audio_id}.webm.partial"
    partial_path.write_bytes(data)
    partial_path.replace(audio_path)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        meta_path.write_text(
            json.dumps({"created_at": created_at}),
            encoding="utf-8",
        )
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise
    return audio_id


class InvalidAudioId(Exception):
    pass


class RecordingNotFound(Exception):
    pass


class RecordingExpired(Exception):
    pass


def load_recording(audio_id: str) -> bytes:
    if not AUDIO_ID_PATTERN.fullmatch(audio_id):
        raise InvalidAudioId()
    root = STORAGE_DIR.resolve()
    audio_path = (root / f"{audio_id}.webm").resolve()
    meta_path = (root / f"{audio_id}.json").resolve()
    if audio_path.parent != root or meta_path.parent != root:
        raise InvalidAudioId()
    if not audio_path.is_file() or not meta_path.is_file():
        raise RecordingNotFound()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(meta["created_at"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RecordingNotFound() from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created_at > RECORDING_TTL:
        raise RecordingExpired()
    return audio_path.read_bytes()
