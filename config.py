
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    admin_username: str
    admin_password: str

    pilot_department: str = "Pilot Department"
    app_name: str = "Project TAU"

    environment: str = "development"

    redis_url: str | None = None
    rate_limit_hash_secret: str | None = None

    turnstile_site_key: str | None = None
    turnstile_secret_key: str | None = None
    turnstile_allowed_hostnames: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
