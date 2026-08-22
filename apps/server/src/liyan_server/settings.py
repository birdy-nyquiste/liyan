from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LIYAN_",
        extra="ignore",
        frozen=True,
    )

    database_url: str = "postgresql+psycopg://liyan:liyan@localhost:5432/liyan"
    cors_origins: str = "http://localhost:5173"

    @cached_property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())
