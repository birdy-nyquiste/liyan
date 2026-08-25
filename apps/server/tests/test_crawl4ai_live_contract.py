"""A real page, extracted by the real browser, normalized the way 来源 intake does.

The deterministic adapter test hands `Crawl4AiUrlFetcher` a page object a test
wrote, which proves the normalization rules and nothing about crawl4ai. What it
cannot see is the failure this project has already met once: the browser is not
a Python dependency, so a deployment can install every package and still have no
Chromium to drive, and every URL 来源 then fails with a message about an
executable rather than about a page.

Opt-in, because it launches a browser and fetches a public page:

    LIYAN_LIVE_CRAWL4AI=1 .venv/bin/python -m pytest \\
        apps/server/tests/test_crawl4ai_live_contract.py

Point `LIYAN_LIVE_CRAWL4AI_URL` at something stable and boring. The default is
`example.com`, which is small, public, and has no reason to change.
"""

import os

import pytest

from liyan_server.crawl4ai_adapter import Crawl4AiUrlFetcher
from liyan_server.settings import Settings
from liyan_server.url_fetch_worker import UrlFetchFailure

pytestmark = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_CRAWL4AI") != "1",
    reason="Set LIYAN_LIVE_CRAWL4AI=1 to run the live crawl4ai contract check.",
)

PUBLIC_URL = os.environ.get("LIYAN_LIVE_CRAWL4AI_URL", "https://example.com/")


@pytest.fixture
def fetcher() -> Crawl4AiUrlFetcher:
    settings = Settings()
    return Crawl4AiUrlFetcher(
        base_directory=settings.crawl4ai_base_directory,
        page_timeout_ms=settings.url_fetch_timeout_seconds * 1000,
    )


def test_a_real_page_becomes_a_titled_body_of_markdown(fetcher: Crawl4AiUrlFetcher) -> None:
    """What intake needs from a URL 来源: a title, a body, and the page's metadata."""
    extraction = fetcher.fetch(PUBLIC_URL)

    assert extraction.body.strip(), "The extraction returned an empty body."
    assert extraction.title, "The extraction returned no title."
    assert isinstance(extraction.metadata, dict)


def test_a_private_address_is_refused_before_a_browser_opens(
    fetcher: Crawl4AiUrlFetcher,
) -> None:
    """The guard that keeps a 来源 URL from becoming a request to our own network.

    Deterministic elsewhere too, and repeated here because it is the one rule
    whose failure is a security problem rather than a broken 来源, and this is
    the only place it runs against the real resolver.
    """
    with pytest.raises(UrlFetchFailure):
        fetcher.fetch("http://localhost:8000/health/ready")
