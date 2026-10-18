from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent / ".env"


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


settings = Settings()
