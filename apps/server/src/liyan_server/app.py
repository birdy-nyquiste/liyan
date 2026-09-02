import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from liyan_server.account_api import account_router
from liyan_server.auth import HttpJwksLoader, JwksJwtVerifier, JwtVerifier
from liyan_server.authentication import Authenticator, current_user_dependency
from liyan_server.billing.api import billing_router
from liyan_server.billing.packs import billing_state, configured_packs
from liyan_server.billing.stripe_api import StripeApi, stripe_api_for
from liyan_server.database import Database
from liyan_server.execution_dispatch import CeleryExecutionDispatcher, ExecutionDispatcher
from liyan_server.health import health_router
from liyan_server.identity_api import identity_router
from liyan_server.liyan.api import liyan_router
from liyan_server.object_storage import ObjectStorage, R2ObjectStorage
from liyan_server.observability import configure_logging
from liyan_server.publication.api import publication_router
from liyan_server.publication.targets import configured_targets, unreachable_targets
from liyan_server.settings import Settings
from liyan_server.source_editing import source_editing_router
from liyan_server.task_api import task_router
from liyan_server.task_creation.confirmation import task_creation_router
from liyan_server.task_creation.file_api import file_source_router
from liyan_server.task_creation.session_api import task_creation_session_router
from liyan_server.task_creation.url_api import url_source_router
from liyan_server.theme.api import theme_router
from liyan_server.zhiyan.api import zhiyan_router

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    jwt_verifier: JwtVerifier | None = None,
    execution_dispatcher: ExecutionDispatcher | None = None,
    object_storage: ObjectStorage | None = None,
    stripe_api: StripeApi | None = None,
) -> FastAPI:
    # Before anything else logs: the startup warnings below are the first
    # lines an operator reads, and they should arrive in the same shape as
    # every other line.
    configure_logging()
    current_settings = settings or Settings()
    database = Database(current_settings.database_url)
    verifier = jwt_verifier or JwksJwtVerifier(
        issuer=current_settings.supabase_issuer,
        audience=current_settings.supabase_audience,
        load_jwks=HttpJwksLoader(current_settings.resolved_supabase_jwks_url),
    )
    current_user = current_user_dependency(
        Authenticator(current_settings, verifier),
        database,
    )
    dispatcher = execution_dispatcher or CeleryExecutionDispatcher(current_settings.broker_url)
    storage = object_storage or R2ObjectStorage(current_settings)
    payments = stripe_api or stripe_api_for(current_settings)

    # Configuration is checked once, here, so an operator learns about a gap at
    # startup instead of from the first user who trips over it.
    #
    # Read the 发布目标 now so unusable configuration fails the boot rather than
    # the first 发布任务.
    configured_targets(current_settings)
    if stranded := unreachable_targets(current_settings):
        logger.warning("publication_target_unreachable", extra={"targets": list(stranded)})
    # An empty LIYAN_R2_* stays invisible until somebody uploads a file, which
    # is far too late to learn it.
    if missing_storage := storage.missing_settings():
        logger.warning(
            "object_storage_unconfigured",
            extra={"missing": list(missing_storage), "affects": "file source intake"},
        )
    # Read the 额度包 now so a malformed one fails the boot rather than the first
    # 购买. An empty configuration is not malformed — it is a deployment that
    # sells nothing — so it warns instead.
    configured_packs(current_settings)
    if billing_state(current_settings) == "unconfigured":
        logger.warning(
            "billing_unconfigured",
            extra={"affects": "buying 额度"},
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        database.dispose()

    application = FastAPI(
        title="立言阁 Server API",
        version="0.1.0",
        description="The server-owned API contract for 立言阁.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(current_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router(current_settings, database, storage, dispatcher))
    application.include_router(identity_router(current_user))
    application.include_router(account_router(database, current_user))
    application.include_router(
        billing_router(current_settings, database, current_user, payments)
    )
    application.include_router(task_router(database, current_user))
    application.include_router(
        task_creation_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        task_creation_session_router(current_settings, database, current_user, storage)
    )
    application.include_router(
        url_source_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        file_source_router(current_settings, database, current_user, dispatcher, storage)
    )
    application.include_router(
        theme_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        zhiyan_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        source_editing_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        liyan_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        publication_router(current_settings, database, current_user, dispatcher)
    )
    return application


app = create_app()
