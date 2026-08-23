"""Reading 作者映射 out of operator configuration."""

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
    "authors": {"Writer@Example.com": "Zeng Zong"},
}


def test_no_configuration_leaves_every_user_with_nowhere_to_publish() -> None:
    assert configured_targets(Settings(publication_targets="")) == ()
    assert targets_for(Settings(publication_targets=""), "writer@example.com") == ()


def test_the_mapping_is_the_authorization_and_the_author_name_at_once() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.author_for("writer@example.com") == "Zeng Zong"
    assert target.authorizes("writer@example.com")
    assert target.author_for("stranger@example.com") is None
    assert not target.authorizes("stranger@example.com")


def test_an_address_matches_however_the_token_happened_to_spell_it() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.author_for("  WRITER@EXAMPLE.COM  ") == "Zeng Zong"


def test_one_target_names_several_users_under_their_own_names() -> None:
    target = configured_targets(
        _settings({**ENTRY, "authors": {"a@example.com": "甲", "b@example.com": "乙"}})
    )[0]

    assert target.author_for("a@example.com") == "甲"
    assert target.author_for("b@example.com") == "乙"


def test_an_unnamed_user_cannot_reach_a_target_by_knowing_its_key() -> None:
    settings = _settings(ENTRY)

    assert target_for(settings, "writer@example.com", "lsforum") is not None
    assert target_for(settings, "stranger@example.com", "lsforum") is None


def test_the_api_path_is_derived_from_the_site_when_it_is_not_given() -> None:
    target = configured_targets(_settings(ENTRY))[0]

    assert target.site_url == "https://blog-lsforum.vercel.app"
    assert target.api_base_url == "https://blog-lsforum.vercel.app"


@pytest.mark.parametrize(
    "authors",
    [{}, None, {"writer@example.com": "   "}],
    ids=["empty", "absent", "blank name"],
)
def test_a_target_nobody_can_publish_under_is_refused_while_reading_config(
    authors: object,
) -> None:
    # Blog requires a non-empty author.name, so an operator should learn this
    # here rather than from a user's failed 发布任务.
    with pytest.raises(ValueError):
        configured_targets(_settings({**ENTRY, "authors": authors}))
