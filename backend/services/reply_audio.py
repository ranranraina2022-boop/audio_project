import json
import re
import uuid
from datetime import datetime, timezone

from config import STORAGE_DIR

AUDIO_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
PUBLIC_AUDIO_BASE = "http://localhost:8003/audio"


class InvalidReplyAudioId(Exception):
    pass


class ReplyAudioNotFound(Exception):
    pass


def save_reply_audio(data: bytes, extension: str, content_type: str) -> str:
    root = (STORAGE_DIR / "replies").resolve()
    root.mkdir(parents=True, exist_ok=True)
    audio_id = uuid.uuid4().hex
    audio_path = (root / f"{audio_id}.{extension}").resolve()
    meta_path = (root / f"{audio_id}.json").resolve()
    if audio_path.parent != root or meta_path.parent != root:
        raise RuntimeError("语音保存位置无效")
    partial = root / f"{audio_id}.{extension}.partial"
    partial.write_bytes(data)
    partial.replace(audio_path)
    try:
        meta_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "content_type": content_type,
                    "extension": extension,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise
    return audio_id


def public_audio_url(audio_id: str) -> str:
    return f"{PUBLIC_AUDIO_BASE}/{audio_id}"


def load_reply_audio(audio_id: str) -> tuple[bytes, str]:
    if not AUDIO_ID_PATTERN.fullmatch(audio_id):
        raise InvalidReplyAudioId()
    root = (STORAGE_DIR / "replies").resolve()
    meta_path = (root / f"{audio_id}.json").resolve()
    if meta_path.parent != root or not meta_path.is_file():
        raise ReplyAudioNotFound()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        extension = meta["extension"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReplyAudioNotFound() from exc
    if not isinstance(extension, str) or not re.fullmatch(r"[a-z0-9]{2,4}", extension):
        raise ReplyAudioNotFound()
    audio_path = (root / f"{audio_id}.{extension}").resolve()
    if audio_path.parent != root or not audio_path.is_file():
        raise ReplyAudioNotFound()
    return audio_path.read_bytes(), extension
