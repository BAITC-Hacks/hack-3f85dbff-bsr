from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    ekt_api_base: str = "https://ekt.kz/api"
    ekt_api_user: str = ""
    ekt_api_password: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    catalog_max_pages: int = 120
    catalog_cache_seconds: int = 300
    request_timeout_seconds: float = 20.0
    public_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
