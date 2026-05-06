"""RSS feed scraper for Visual Capitalist."""

import hashlib
import re

import feedparser
import requests
from bs4 import BeautifulSoup

FEED_URL = "https://www.visualcapitalist.com/feed/"


def _table_to_markdown(table_tag: BeautifulSoup) -> str:
    """Convert an HTML <table> to Markdown table format."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        rows.append(cells)
    if not rows:
        return ""

    col_count = max(len(r) for r in rows)
    for r in rows:
        while len(r) < col_count:
            r.append("")

    header = rows[0]
    separator = ["---"] * col_count
    body = rows[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_tables(html_content: str) -> str:
    """Extract all <table> elements from HTML and convert to Markdown."""
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
    if tables:
        parts = [_table_to_markdown(t) for t in tables]
        return "\n\n".join(p for p in parts if p)
    return ""


def _extract_text_and_lists(html_content: str) -> str:
    """Extract core text and <ul> lists from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")
    parts = []
    for elem in soup.find_all(["p", "ul", "ol"]):
        if elem.name in ("ul", "ol"):
            for li in elem.find_all("li"):
                parts.append(f"- {li.get_text(strip=True)}")
        else:
            text = elem.get_text(strip=True)
            if text:
                parts.append(text)
    return "\n".join(parts)


def _get_image_url(entry) -> str | None:
    """Extract image URL from media:content or content:encoded."""
    media_content = entry.get("media_content")
    if media_content:
        for media in media_content:
            url = media.get("url")
            if url:
                return url

    content_encoded = entry.get("content", [{}])[0].get("value", "")
    if content_encoded:
        soup = BeautifulSoup(content_encoded, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]

    return None


def _generate_stable_id(url: str) -> str:
    """Generate a stable article ID from the URL using MD5 hash."""
    # Normalize URL: strip trailing slash and query params for stability
    normalized = url.split("?")[0].rstrip("/")
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


MAX_PAGES = 10


def _parse_entry(entry) -> dict:
    """Parse a single feed entry into an article dict."""
    url = entry.get("link", "")
    article_id = _generate_stable_id(url)

    content_encoded = ""
    if entry.get("content"):
        content_encoded = entry["content"][0].get("value", "")

    tables_md = _extract_tables(content_encoded)
    text_content = _extract_text_and_lists(content_encoded)
    extracted_content = tables_md if tables_md else text_content

    image_url = _get_image_url(entry)

    return {
        "id": article_id,
        "title": entry.get("title", "Untitled"),
        "original_url": url,
        "pub_date": entry.get("published", ""),
        "image_url": image_url,
        "content_md": extracted_content,
    }


def fetch_articles(existing_urls: set[str] | None = None) -> list[dict]:
    """Fetch articles from RSS, paginating until all new articles are collected.

    Uses original_url for deduplication (stable across runs).
    Stops when a page returns only articles already in existing_urls.
    """
    if existing_urls is None:
        existing_urls = set()

    all_articles = []
    seen_urls: set[str] = set()

    for page in range(1, MAX_PAGES + 1):
        url = FEED_URL if page == 1 else f"{FEED_URL}?paged={page}"
        feed = feedparser.parse(url)

        if not feed.entries:
            break

        page_all_known = True
        for entry in feed.entries:
            article = _parse_entry(entry)
            article_url = article["original_url"]
            if article_url not in existing_urls and article_url not in seen_urls:
                all_articles.append(article)
                page_all_known = False
            seen_urls.add(article_url)

        if page_all_known:
            break

    return all_articles
