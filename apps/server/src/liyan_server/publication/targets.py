"""发布目标: server configuration, never user data.

A target names a destination plus the 作者映射 that says, for each authorized
user, the author name 立言阁 publishes under there. Author identity belongs to
the user rather than to the destination: two people publishing to one Blog are
two authors, not two targets. The mapping is therefore also the authorization —
a user may publish to a target exactly when it names them.

The MVP gives the user no way to create, bind, or authorize one, so the whole
set lives in server configuration. The ingest credential is deliberately absent
from this record: it is read from settings at submission time and never travels
with a target.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from liyan_server.settings import Settings

BLOG_PLATFORM = "lsforum_blog"


@dataclass(frozen=True)
class PublicationTarget:
    key: str
    platform: str
    display_name: str
    site_url: str
    api_base_url: str
    #: Verified email, folded for comparison, to the author name Blog displays.
    authors: Mapping[str, str]

    def authorizes(self, email: str) -> bool:
        return self.author_for(email) is not None

    def author_for(self, email: str) -> str | None:
        """The name this user publishes under here, or None if they may not."""
        return self.authors.get(email.strip().casefold())


@lru_cache(maxsize=8)
def _parsed(configuration: str) -> tuple[PublicationTarget, ...]:
    if not configuration.strip():
        return ()
    entries = json.loads(configuration)
    if not isinstance(entries, list):
        raise ValueError("LIYAN_PUBLICATION_TARGETS must be a JSON array.")
    return tuple(_target(entry) for entry in entries)


def _target(entry: object) -> PublicationTarget:
    if not isinstance(entry, dict):
        raise ValueError("Every publication target must be a JSON object.")
    site_url = str(entry["site_url"]).rstrip("/")
    return PublicationTarget(
        key=str(entry["key"]),
        platform=str(entry.get("platform", BLOG_PLATFORM)),
        display_name=str(entry["display_name"]),
        site_url=site_url,
        api_base_url=str(entry.get("api_base_url", site_url)).rstrip("/"),
        authors=_authors(entry.get("authors")),
    )


def _authors(value: object) -> Mapping[str, str]:
    """Read 作者映射 as {email: author name}, refusing an unusable entry.

    Blog requires a non-empty `author.name`, so a blank name here would only
    fail at submission time. Rejecting it while reading configuration means an
    operator learns about it at startup instead of from a user's failed 发布任务.
    """
    if not isinstance(value, dict) or not value:
        raise ValueError("A publication target must map at least one email to an author.")
    authors: dict[str, str] = {}
    for email, author in value.items():
        name = str(author).strip()
        if not name:
            raise ValueError(f"Publication target author for {email!r} is empty.")
        authors[str(email).strip().casefold()] = name
    return MappingProxyType(authors)


def configured_targets(settings: Settings) -> tuple[PublicationTarget, ...]:
    """Every target the operator configured, whoever they belong to."""
    return _parsed(settings.publication_targets)


def targets_for(settings: Settings, email: str) -> tuple[PublicationTarget, ...]:
    return tuple(
        target for target in configured_targets(settings) if target.authorizes(email)
    )


def target_for(settings: Settings, email: str, key: str) -> PublicationTarget | None:
    """The one target this user may publish to under `key`, if any.

    An unauthorized target is indistinguishable from an unknown one on purpose:
    a caller must not be able to enumerate destinations that are not theirs.
    """
    for target in targets_for(settings, email):
        if target.key == key:
            return target
    return None
