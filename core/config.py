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

    # Firebase service account. Two ways in, checked in this order:
    #  - firebase_credentials_json: the JSON *content*, for container secrets
    #  - firebase_credentials_path: a file path, convenient locally
    # A container has no file to mount, so deployments use the JSON form.
    firebase_credentials_path: str = ""
    firebase_credentials_json: str = ""

    # Places API (New), key restricted to that API. Used only by offline jobs —
    # every call is cached and capped (see jobs/resolve_google_maps.py).
    google_maps_api_key: str = ""

    # How long the catalog may be served from memory, and how long clients may
    # cache a content response. The catalog only changes when a job runs, so
    # minutes are safe; lower it if you're iterating on seed data.
    content_cache_seconds: int = 600

    # Browser origins allowed to call the API. Expo web runs on localhost during
    # development; a deployment must name its real origins here. Native apps send
    # no Origin header and are unaffected either way.
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    @property
    def cosmos_configured(self) -> bool:
        return bool(self.cosmos_endpoint and self.cosmos_key)

    @property
    def firebase_configured(self) -> bool:
        """firebase_admin.initialize_app() succeeds with no credentials and only
        fails at the first token verification, so this is checked at startup."""
        return bool(self.firebase_credentials_json or self.firebase_credentials_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
