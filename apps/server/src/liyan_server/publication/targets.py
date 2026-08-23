"""发布目标: server configuration, never user data.

A target is a destination and the set of users allowed to reach it. It says
nothing about who the article is by: the author name is the user's to type at
confirmation, so the same Blog serves every writer without configuration
changing. What stays configuration is access — a user may publish to a target
exactly when it lists their address.

The MVP gives the user no way to create, bind, or authorize one, so the whole
set lives in server configuration. The ingest credential is deliberately absent
from this record: it is read from settings at submission time and never travels
with a target.
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
    #: Verified addresses, folded for comparison, allowed to publish here.
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
        emails=_emails(entry.get("emails")),
    )


def _emails(value: object) -> frozenset[str]:
    """Read the addresses allowed to publish, refusing a target nobody can use.

    A target reaching nobody is always a configuration mistake, and finding out
    at startup beats finding out from a user who cannot see their destination.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("A publication target must authorize at least one email.")
    emails = frozenset(str(email).strip().casefold() for email in value)
    if "" in emails:
        raise ValueError("A publication target email is empty.")
    return emails


def configured_targets(settings: Settings) -> tuple[PublicationTarget, ...]:
    """Every target the operator configured, whoever they belong to."""
    return _parsed(settings.publication_targets)


def targets_for(settings: Settings, email: str) -> tuple[PublicationTarget, ...]:
    return tuple(
        target for target in configured_targets(settings) if target.authorizes(email)
    )


def unreachable_targets(settings: Settings) -> tuple[str, ...]:
    """Keys of targets no one who can sign in is authorized to use.

    Authorization and the sign-in allowlist are separate settings, so an
    address that is named here but cannot log in makes a target invisible with
    nothing to see anywhere. That is always a configuration mistake, and it is
    quiet enough to be worth saying out loud at startup.
    """
    allowed = settings.normalized_allowed_emails
    if not allowed:
        return ()
    return tuple(
        target.key
        for target in configured_targets(settings)
        if not (target.emails & allowed)
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
