from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.auth import InvalidAccessToken, JwtVerifier
from liyan_server.database import Database, User
from liyan_server.settings import Settings

CurrentUserDependency = Callable[..., User]


class Authenticator:
    def __init__(self, settings: Settings, verifier: JwtVerifier) -> None:
        self._allowed_emails = settings.normalized_allowed_emails
        self._verifier = verifier
        self.bearer = HTTPBearer(auto_error=False)

    def authenticate(
        self,
        credentials: HTTPAuthorizationCredentials | None,
        session: Session,
    ) -> User:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
            )
        try:
            identity = self._verifier.verify(credentials.credentials)
        except InvalidAccessToken as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is temporarily unavailable.",
            ) from error

        normalized_email = identity.email.strip().casefold()
        if normalized_email not in self._allowed_emails:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access is not available for this account.",
            )

        user = session.scalar(select(User).where(User.auth_subject == identity.subject))
        if user is None:
            user = User(auth_subject=identity.subject, email=normalized_email)
            session.add(user)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                user = session.scalar(select(User).where(User.auth_subject == identity.subject))
                if user is None:
                    raise
        elif user.email != normalized_email:
            user.email = normalized_email
            session.commit()
        return user


def current_user_dependency(
    authenticator: Authenticator,
    database: Database,
) -> CurrentUserDependency:
    def current_user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(authenticator.bearer),
        ],
        session: Annotated[Session, Depends(database.session)],
    ) -> User:
        return authenticator.authenticate(credentials, session)

    return current_user
