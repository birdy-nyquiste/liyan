"""Reading 发布目标 out of operator configuration."""

import json

import pytest

from liyan_server.publication.targets import configured_targets, target_for, targets_for
from liyan_server.settings import Settings


def _settings(*entries: dict[str, object]) -> Settings:
    return Settings(publication_targets=json.dumps(list(entries)))


ENTRY: dict[str, object] = {
    "key": "lsforum",
    "display_name": "LSForum Blog",
    "site_url": "https://blog-lsforum.vercel.app/",
    "emails": ["Writer@Example.com"],
}


def test_no_configuration_leaves_every_user_with_nowhere_to_publish() -> None:
    assert configured_targets(Settings(publication_targets="")) == ()
    assert targets_for(Settings(publication_targets=""), "writer@example.com") == ()


def test_a_target_grants_access_without_naming_anyone_as_the_author() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.authorizes("writer@example.com")
    assert not target.authorizes("stranger@example.com")
    assert not hasattr(target, "author")


def test_an_address_matches_however_the_token_happened_to_spell_it() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.authorizes("  WRITER@EXAMPLE.COM  ")


def test_one_destination_serves_several_writers(tmp_path: object) -> None:
    target = configured_targets(
        _settings({**ENTRY, "emails": ["a@example.com", "b@example.com"]})
    )[0]

    assert target.authorizes("a@example.com")
    assert target.authorizes("b@example.com")


def test_an_unauthorized_user_cannot_reach_a_target_by_knowing_its_key() -> None:
    settings = _settings(ENTRY)

    assert target_for(settings, "writer@example.com", "lsforum") is not None
    assert target_for(settings, "stranger@example.com", "lsforum") is None


def test_the_api_path_is_derived_from_the_site_when_it_is_not_given() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.site_url == "https://blog-lsforum.vercel.app"
    assert target.api_base_url == "https://blog-lsforum.vercel.app"


@pytest.mark.parametrize(
    "emails", [[], None, [""], ["   "]], ids=["empty", "absent", "blank", "whitespace"]
)
def test_a_target_nobody_can_reach_is_refused_while_reading_config(
    emails: object,
) -> None:
    # An unreachable target is always a mistake, and an operator should find out
    # at startup rather than from a user who cannot see their destination.
    with pytest.raises(ValueError):
        configured_targets(_settings({**ENTRY, "emails": emails}))


def test_a_target_no_signed_in_user_can_reach_is_named_out_loud() -> None:
    from liyan_server.publication.targets import unreachable_targets

    # The address is authorized on the target but cannot sign in, so the target
    # would simply never appear for anyone.
    settings = Settings(
        publication_targets=json.dumps([{**ENTRY, "emails": ["nobody@example.com"]}]),
        allowed_emails="writer@example.com",
    )

    assert unreachable_targets(settings) == ("lsforum",)


def test_a_target_someone_can_actually_use_is_not_reported() -> None:
    from liyan_server.publication.targets import unreachable_targets

    settings = Settings(
        publication_targets=json.dumps(ENTRY and [ENTRY]),
        allowed_emails="Writer@Example.com",
    )

    assert unreachable_targets(settings) == ()
