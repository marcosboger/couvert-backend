from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "couvert"
    users_container: str = "users"
    restaurants_container: str = "restaurants"
    user_content_container: str = "user_content"
    content_container: str = "content"

    # Path to the Firebase service-account JSON (Project settings > Service accounts)
    firebase_credentials_path: str = ""

    # Places API (New), key restricted to that API. Used only by offline jobs —
    # every call is cached and capped (see jobs/resolve_google_maps.py).
    google_maps_api_key: str = ""

    @property
    def cosmos_configured(self) -> bool:
        return bool(self.cosmos_endpoint and self.cosmos_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
