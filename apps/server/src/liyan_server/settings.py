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
    allowed_emails: str = ""
    supabase_issuer: str = "http://localhost:54321/auth/v1"
    supabase_audience: str = "authenticated"
    supabase_jwks_url: str = ""
    short_source_characters: int = 500
    broker_url: str = "redis://localhost:6379/0"
    crawl4ai_base_directory: str = "/tmp/liyan-crawl4ai"
    url_fetch_timeout_seconds: int = 60

    @cached_property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())

    @cached_property
    def normalized_allowed_emails(self) -> frozenset[str]:
        return frozenset(
            email.strip().casefold() for email in self.allowed_emails.split(",") if email.strip()
        )

    @cached_property
    def resolved_supabase_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_issuer.rstrip('/')}/.well-known/jwks.json"
