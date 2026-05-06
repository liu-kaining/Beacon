"""RSS feed scraper for Visual Capitalist."""

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

    # Determine column count
    col_count = max(len(r) for r in rows)
    # Pad short rows
    for r in rows:
        while len(r) < col_count:
            r.append("")

    # First row as header
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
    # Try media:content first
    media_content = entry.get("media_content")
    if media_content:
        for media in media_content:
            url = media.get("url")
            if url:
                return url

    # Fallback: extract first <img> from content:encoded
    content_encoded = entry.get("content", [{}])[0].get("value", "")
    if content_encoded:
        soup = BeautifulSoup(content_encoded, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]

    return None


def fetch_articles() -> list[dict]:
    """Parse RSS feed and return a list of raw article dicts."""
    feed = feedparser.parse(FEED_URL)
    articles = []

    for entry in feed.entries:
        guid = entry.get("id", entry.get("link", ""))
        # Extract numeric ID from guid or link
        id_match = re.search(r"/(\d+)/?$", guid)
        article_id = id_match.group(1) if id_match else str(abs(hash(guid)) % 10**8)

        content_encoded = ""
        if entry.get("content"):
            content_encoded = entry["content"][0].get("value", "")

        tables_md = _extract_tables(content_encoded)
        text_content = _extract_text_and_lists(content_encoded)

        # Use tables if available, otherwise fall back to text/lists
        extracted_content = tables_md if tables_md else text_content

        image_url = _get_image_url(entry)

        articles.append({
            "id": article_id,
            "title": entry.get("title", "Untitled"),
            "original_url": entry.get("link", ""),
            "pub_date": entry.get("published", ""),
            "image_url": image_url,
            "content_md": extracted_content,
        })

    return articles
