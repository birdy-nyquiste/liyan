from functools import cached_property

from pydantic import field_validator
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
    zhiyan_model: str = "deepseek-v4-flash"
    zhiyan_timeout_seconds: int = 300
    liyan_model: str = "deepseek-v4-flash"
    liyan_timeout_seconds: int = 300
    #: A JSON array of 发布目标. Operator configuration, never user data:
    #: {key, display_name, site_url, api_base_url, author, emails}.
    publication_targets: str = ""
    blog_ingest_token: str = ""
    blog_timeout_seconds: int = 60
    #: What each of these costs is documented in `.env.example`; why the rules
    #: are what they are is in `cleanup.py`.
    cleanup_interval_seconds: int = 3600
    cleanup_task_creation_session_ttl_hours: int = 24
    cleanup_source_edit_session_ttl_hours: int = 24
    cleanup_deleted_task_retention_days: int = 30
    #: How long a run may say nothing before it is presumed lost. Generous:
    #: calling a slow run dead costs a user their work, calling a dead one
    #: slow only delays the next sweep.
    stalled_execution_timeout_minutes: int = 30
    unclaimed_execution_timeout_minutes: int = 30
    stalled_sweep_interval_seconds: int = 300
    #: How many Executions one user may hold in flight at once, across every
    #: operation; 0 disables the ceiling, which is what Local wants. What it
    #: protects and how the number was chosen are in
    #: `docs/operations/limits.md`; why a batch that starts under it is
    #: admitted whole is in `execution_limits.py`.
    max_active_executions_per_user: int = 6
    #: 赠送额度 a new user is given once, on first sign-in. There is no monthly
    #: refill: this product's cadence is one article at a time, and a standing
    #: grant is a standing bill against every account ever abandoned.
    #:
    #: A placeholder. `docs/operations/credits.md` sizes it at one complete
    #: 立言任务, which its own table puts near 118 额度 — but that table rests on
    #: assumptions `scripts/calibrate_costs.py` has not yet been able to settle.
    #: Raise it in Local, where one developer competes with nobody.
    signup_grant_credits: int = 150
    #: Names this worker in its heartbeat. Render sets it per service, so
    #: one silent worker among several is identifiable.
    worker_name: str = "celery-worker"

    @field_validator("database_url")
    @classmethod
    def name_the_installed_driver(cls, value: str) -> str:
        """Point a bare PostgreSQL URL at psycopg 3, which is what is installed.

        A managed database hands out its URL in the platform's shape: Render's
        `fromDatabase` wiring produces `postgresql://…` and Heroku still emits
        `postgres://…`. SQLAlchemy reads a URL with no driver as psycopg 2, and
        this project installs psycopg 3, so the first thing to touch the
        database dies with ModuleNotFoundError for a driver nobody chose —
        during the build, before anything has a chance to explain itself.

        Editing the value by hand is not the fix: on Render it is wired from the
        database resource, so a hand-edit is overwritten or has to be maintained
        against it. A URL that already names a driver is left exactly as it is,
        including psycopg 2, because naming one is a deliberate act.
        """
        for platform_scheme in ("postgresql://", "postgres://"):
            if value.startswith(platform_scheme):
                return "postgresql+psycopg://" + value[len(platform_scheme) :]
        return value

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
