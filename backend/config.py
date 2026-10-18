from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
STORAGE_DIR = BACKEND_DIR / "storage"


class Settings(BaseSettings):
    """密钥都可以为空。健康检查不读取这些值，也不访问外部服务。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BAILIAN_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    AMAP_API_KEY: str = ""
    # 仅用于本地模拟识别失败。空字符串表示调用真实百炼。不写入 .env.example。
    BAILIAN_ASR_MOCK: str = ""
    # 仅用于本地模拟高德故障。空字符串表示调用真实高德。不写入 .env.example。
    AMAP_SEARCH_MOCK: str = ""
    # 仅用于本地模拟推荐语失败。空字符串表示调用真实 DeepSeek。不写入 .env.example。
    DEEPSEEK_REPLY_MOCK: str = ""
    # 仅用于本地模拟语音合成或下载失败。空字符串表示调用真实百炼。不写入 .env.example。
    BAILIAN_TTS_MOCK: str = ""


settings = Settings()
