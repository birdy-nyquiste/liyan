import asyncio
import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass

from liyan_server.url_fetch_worker import UrlExtraction, UrlFetchFailure


@dataclass(frozen=True)
class Crawl4AiPolicy:
    cache: str = "bypass"
    max_retries: int = 0
    fallback_enabled: bool = False
    llm_extraction_enabled: bool = False
    page_timeout_ms: int = 60_000


@dataclass(frozen=True)
class Crawl4AiPage:
    success: bool
    raw_markdown: str
    metadata: dict[str, object]
    error_message: str | None


CrawlPage = Callable[[str, Crawl4AiPolicy], Crawl4AiPage]


class Crawl4AiUrlFetcher:
    def __init__(
        self,
        *,
        crawl: CrawlPage | None = None,
        base_directory: str = "/tmp/liyan-crawl4ai",
        page_timeout_ms: int = 60_000,
    ) -> None:
        self._crawl = crawl or self._crawl_page
        self._base_directory = base_directory
        self._policy = Crawl4AiPolicy(page_timeout_ms=page_timeout_ms)

    def fetch(self, url: str) -> UrlExtraction:
        page = self._crawl(url, self._policy)
        if not page.success:
            raise UrlFetchFailure(
                "inaccessible_url",
                "The article is not publicly accessible. Replace this source or try another URL.",
                internal_error=page.error_message,
            )
        return UrlExtraction(
            title=_metadata_text(page.metadata, "title"),
            body=page.raw_markdown,
            metadata=page.metadata,
        )

    def _crawl_page(self, url: str, policy: Crawl4AiPolicy) -> Crawl4AiPage:
        os.environ["CRAWL4_AI_BASE_DIRECTORY"] = self._base_directory
        _require_public_network_target(url)
        return asyncio.run(_crawl_page(url, policy))


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _require_public_network_target(url: str) -> None:
    from urllib.parse import urlsplit

    hostname = urlsplit(url).hostname
    if hostname is None:
        raise UrlFetchFailure("unsupported_url", "This URL is not a supported public article.")
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as error:
        raise UrlFetchFailure(
            "inaccessible_url",
            "The article is not publicly accessible. Replace this source or try another URL.",
            internal_error=repr(error),
        ) from error
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise UrlFetchFailure("unsupported_url", "This URL is not a supported public article.")


async def _crawl_page(url: str, policy: Crawl4AiPolicy) -> Crawl4AiPage:
    from crawl4ai import (  # type: ignore[import-untyped]
        AsyncWebCrawler,
        BrowserConfig,
        CacheMode,
        CrawlerRunConfig,
    )

    browser_config = BrowserConfig(
        headless=True,
        text_mode=True,
        verbose=False,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=1,
        excluded_tags=["nav", "footer", "form"],
        remove_forms=True,
        remove_overlay_elements=True,
        check_robots_txt=True,
        page_timeout=policy.page_timeout_ms,
        max_retries=policy.max_retries,
        fallback_fetch_function=None,
        verbose=False,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
    markdown = result.markdown.raw_markdown if result.markdown else ""
    metadata = dict(result.metadata or {})
    return Crawl4AiPage(
        success=bool(result.success),
        raw_markdown=markdown,
        metadata=metadata,
        error_message=result.error_message,
    )
