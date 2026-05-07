"""RSS feed scraper for Visual Capitalist."""

import hashlib

import feedparser
import requests
from bs4 import BeautifulSoup

FEED_URL = "https://www.visualcapitalist.com/feed/"


def _pick_best_image_from_content_encoded(content_encoded: str) -> str | None:
    """Pick the best (largest) visualization image from RSS content:encoded HTML.

    Visual Capitalist's feed often includes:
    - a 1200x628 "SHARE" card in media:content/enclosure
    - a larger "SITE/website" visualization image inside content:encoded
    We prefer the SITE/website visualization when available.
    """
    if not content_encoded:
        return None

    soup = BeautifulSoup(content_encoded, "html.parser")
    imgs: list[str] = []

    # Prefer the RSS visualization block if present.
    rss_block = soup.find("div", class_="rss-image")
    roots = [rss_block] if rss_block else [soup]

    deny_substrings = (
        "voronoi",
        "cropped-logo",
        "logo",
        "icon",
        "app-store",
        "google-play",
        "webinar",
        "register",
        "banner",
        "sponsor",
        "doubleclick",
        "adserver",
    )

    for root in roots:
        if not root:
            continue
        for img in root.find_all("img"):
            src = img.get("src") or ""
            if not src:
                continue
            if "wp-content/uploads/" not in src:
                continue
            low = src.lower()
            if any(bad in low for bad in deny_substrings):
                continue
            imgs.append(src)

    if not imgs:
        return None

    def score(u: str) -> tuple[int, int]:
        uu = u.lower()
        bonus = 0
        if "_site" in uu or "website" in uu:
            bonus += 100
        if "share" in uu:
            bonus -= 50
        if any(k in uu for k in ("webinar", "register", "banner", "sponsor", "doubleclick", "adserver")):
            bonus -= 200
        # Prefer webp/png over jpg when otherwise equal
        if uu.endswith(".webp"):
            bonus += 5
        return (bonus, len(u))

    return sorted(imgs, key=score, reverse=True)[0]


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


def _get_image_url(entry, article_url: str) -> str | None:
    """Get the best image URL for an article.

    Priority: content:encoded SITE/website img > RSS media:content (usually SHARE) > og:image from page.
    """
    # Best source: content:encoded often includes the real visualization image (SITE/website)
    content_encoded = ""
    if entry.get("content"):
        content_encoded = entry["content"][0].get("value", "")
    best_from_content = _pick_best_image_from_content_encoded(content_encoded)
    if best_from_content:
        return best_from_content

    # RSS media:content is the most reliable source for the article hero image
    media_content = entry.get("media_content")
    if media_content:
        for media in media_content:
            url = media.get("url")
            if url:
                return url

    # Fallback: fetch article page and try og:image
    try:
        resp = requests.get(article_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BeaconBot/1.0)"
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
    except Exception as e:
        print(f"[scraper] Failed to fetch og:image from {article_url}: {e}")

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

    image_url = _get_image_url(entry, url)

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

        if getattr(feed, "bozo", False):
            err = getattr(feed, "bozo_exception", None)
            print(f"[scraper] Feed parse warning on page {page}: {err}")

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
