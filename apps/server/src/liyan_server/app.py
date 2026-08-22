from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from liyan_server.auth import HttpJwksLoader, JwksJwtVerifier, JwtVerifier
from liyan_server.authentication import Authenticator, current_user_dependency
from liyan_server.database import Database
from liyan_server.execution_dispatch import CeleryExecutionDispatcher, ExecutionDispatcher
from liyan_server.health import health_router
from liyan_server.identity_api import identity_router
from liyan_server.object_storage import ObjectStorage, R2ObjectStorage
from liyan_server.settings import Settings
from liyan_server.task_api import task_router
from liyan_server.task_creation.confirmation import task_creation_router
from liyan_server.task_creation.file_api import file_source_router
from liyan_server.task_creation.session_api import task_creation_session_router
from liyan_server.task_creation.url_api import url_source_router


def create_app(
    settings: Settings | None = None,
    *,
    jwt_verifier: JwtVerifier | None = None,
    execution_dispatcher: ExecutionDispatcher | None = None,
    object_storage: ObjectStorage | None = None,
) -> FastAPI:
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
    application.include_router(health_router(database))
    application.include_router(identity_router(current_user))
    application.include_router(task_router(database, current_user))
    application.include_router(task_creation_router(current_settings, database, current_user))
    application.include_router(
        task_creation_session_router(current_settings, database, current_user, storage)
    )
    application.include_router(
        url_source_router(current_settings, database, current_user, dispatcher)
    )
    application.include_router(
        file_source_router(current_settings, database, current_user, dispatcher, storage)
    )
    return application


app = create_app()
