"""Stage 1 (scope) + page fetch/strip helpers — all free of LLM tokens.

Selects upgrade-relevant URLs from a sitemap and turns fetched HTML into plain
text for chunking. Network I/O uses ``httpx`` (already a project dependency);
parsing uses the stdlib only.
"""
from __future__ import annotations

import logging
from html.parser import HTMLParser
from typing import List
from xml.etree import ElementTree

import httpx

from .schema import is_upgrade_url

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
_SKIP_TEXT_TAGS = {"script", "style", "noscript", "head"}


def fetch_text(url: str, client: httpx.Client) -> str:
    response = client.get(url, follow_redirects=True, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.text


def _locs(xml_text: str) -> List[str]:
    """Return all <loc> values regardless of sitemap namespace."""
    root = ElementTree.fromstring(xml_text)
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


def iter_sitemap_urls(sitemap_url: str, client: httpx.Client, max_depth: int = 2) -> List[str]:
    """Collect page URLs from a sitemap, recursing into nested sitemap indexes."""
    try:
        locs = _locs(fetch_text(sitemap_url, client))
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
        logger.warning("Sitemap fetch/parse failed for %s: %s", sitemap_url, exc)
        return []
    pages: List[str] = []
    for loc in locs:
        if loc.endswith(".xml") and max_depth > 0:
            pages.extend(iter_sitemap_urls(loc, client, max_depth - 1))
        else:
            pages.append(loc)
    return pages


def scope_urls(sitemap_url: str, limit: int = 0) -> List[str]:
    """Return upgrade-relevant page URLs from a sitemap (stage 1 filter)."""
    with httpx.Client() as client:
        pages = iter_sitemap_urls(sitemap_url, client)
    scoped = [url for url in dict.fromkeys(pages) if is_upgrade_url(url)]
    return scoped[:limit] if limit else scoped


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._parts)


def html_to_text(html: str) -> str:
    """Strip tags (and script/style/head) to plain text for chunking."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()
