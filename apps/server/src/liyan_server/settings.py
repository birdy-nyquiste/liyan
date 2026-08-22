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
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    file_max_bytes: int = 10 * 1024 * 1024
    file_max_pages: int = 100
    file_max_normalized_characters: int = 500_000
    file_parse_timeout_seconds: int = 60
    file_max_docx_entries: int = 2_000
    file_max_docx_uncompressed_bytes: int = 50 * 1024 * 1024
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    zhiyan_model: str = "deepseek-v4-pro"
    zhiyan_timeout_seconds: int = 300

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
