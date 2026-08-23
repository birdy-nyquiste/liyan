"""发布目标: server configuration, never user data.

A target names a destination and the author identity 立言阁 publishes under. The
MVP gives the user no way to create, bind, or authorize one, so the whole set
lives in server configuration and a user simply sees the subset naming them.
The ingest credential is deliberately absent from this record: it is read from
settings at submission time and never travels with a target.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from liyan_server.settings import Settings

BLOG_PLATFORM = "lsforum_blog"


@dataclass(frozen=True)
class PublicationTarget:
    key: str
    platform: str
    display_name: str
    site_url: str
    api_base_url: str
    author: str
    emails: frozenset[str]

    def authorizes(self, email: str) -> bool:
        return email.strip().casefold() in self.emails


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
        author=str(entry["author"]),
        emails=frozenset(str(email).strip().casefold() for email in entry.get("emails", ())),
    )


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
