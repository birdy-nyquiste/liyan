import socket

import pytest

from liyan_server.crawl4ai_adapter import (
    Crawl4AiPage,
    Crawl4AiPolicy,
    Crawl4AiUrlFetcher,
    _require_public_network_target,
)
from liyan_server.url_fetch_worker import UrlFetchFailure


def test_crawl4ai_adapter_uses_deterministic_non_llm_extraction() -> None:
    def crawl(url: str, policy: Crawl4AiPolicy) -> Crawl4AiPage:
        assert url == "https://example.com/article"
        assert policy.cache == "bypass"
        assert policy.max_retries == 0
        assert policy.fallback_enabled is False
        assert policy.llm_extraction_enabled is False
        return Crawl4AiPage(
            success=True,
            raw_markdown="# Full article\n\nBody text.",
            metadata={"title": "Page title", "author": "Author"},
            error_message=None,
        )

    extraction = Crawl4AiUrlFetcher(crawl=crawl).fetch("https://example.com/article")

    assert extraction.title == "Page title"
    assert extraction.body == "# Full article\n\nBody text."
    assert extraction.metadata == {"title": "Page title", "author": "Author"}


def test_crawl4ai_adapter_returns_actionable_failure_without_fallback() -> None:
    fetcher = Crawl4AiUrlFetcher(
        crawl=lambda _url, _policy: Crawl4AiPage(
            success=False,
            raw_markdown="",
            metadata={},
            error_message="net::ERR_NAME_NOT_RESOLVED",
        )
    )

    try:
        fetcher.fetch("https://unavailable.example/article")
    except UrlFetchFailure as error:
        assert error.code == "inaccessible_url"
        assert "publicly accessible" in str(error)
        assert "ERR_NAME_NOT_RESOLVED" not in str(error)
    else:
        raise AssertionError("Expected inaccessible Crawl4AI result to fail.")


def test_hostname_resolving_to_private_network_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0))
        ],
    )

    with pytest.raises(UrlFetchFailure) as failure:
        _require_public_network_target("https://internal.example/article")

    assert failure.value.code == "unsupported_url"
