"""Shared heuristics for picking the best Visual Capitalist chart image URL.

WordPress/RSS often exposes multiple sizes (src, srcset). We prefer full "SITE"
visualizations over 1200×628 share cards and merge srcset candidates.
"""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

# Do not exclude "voronoi" — many full infographics use that in the filename.
_DENY_SUBSTRINGS = (
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

_WP_SIZE_RE = re.compile(r"-(\d{2,5})x(\d{2,5})\.(?:jpe?g|png|webp|gif)(?:\?|#|$)", re.I)


def _deny_url(url: str) -> bool:
    low = url.lower()
    return any(b in low for b in _DENY_SUBSTRINGS)


def _parse_srcset_urls(srcset: str) -> list[str]:
    if not srcset:
        return []
    out: list[str] = []
    for part in srcset.split(","):
        url_part = part.strip().split()[0] if part.strip() else ""
        if url_part and "wp-content/uploads/" in url_part:
            out.append(url_part)
    return out


def _wp_pixel_area(url: str) -> int | None:
    m = _WP_SIZE_RE.search(url)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return w * h


def _size_score(url: str) -> int:
    """Higher is better: prefer large dimensions; penalize typical OG/share crop."""
    area = _wp_pixel_area(url)
    if area is not None:
        m = _WP_SIZE_RE.search(url)
        assert m
        w, h = int(m.group(1)), int(m.group(2))
        # Open Graph / social share cards are often ~1200×628 and crop tall charts.
        if 1080 <= w <= 1400 and 560 <= h <= 720:
            return max(0, area - 350_000)
        return area
    if "wp-content/uploads/" in url.lower():
        # No explicit WxH in URL — often the canonical / larger asset.
        return 1_500_000
    return 0


def _score_tuple(url: str) -> tuple[int, int, int, int]:
    u = url.lower()
    if _deny_url(url):
        return (-10_000, -1, -1, -1)

    bonus = 0
    if "_site" in u or "website" in u:
        bonus += 120
    if "share" in u:
        bonus -= 60
    if u.endswith(".webp"):
        bonus += 8
    if "voronoi" in u:
        # Full Voronoi treemaps are valid hero art; slight nudge if other signals tie.
        bonus += 5

    size = _size_score(url)
    return (bonus, size, len(url), hash(url) % 997)


def collect_wp_image_urls_from_soup(soup: BeautifulSoup) -> list[str]:
    """Collect candidate image URLs from rss-image block (if any) else whole document."""
    rss_block = soup.find("div", class_="rss-image")
    roots: list = [rss_block] if rss_block else [soup]

    candidates: list[str] = []
    for root in roots:
        if not root:
            continue
        for img in root.find_all("img"):
            src = (img.get("src") or "").strip()
            if src and "wp-content/uploads/" in src:
                candidates.append(src)
            for u in _parse_srcset_urls(img.get("srcset") or ""):
                candidates.append(u)

    # Dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return [u for u in uniq if not _deny_url(u)]


def pick_best_image_url_from_html(html: str) -> str | None:
    """Pick best chart image from HTML (RSS content:encoded fragment or full page)."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates = collect_wp_image_urls_from_soup(soup)
    if candidates:
        return max(candidates, key=_score_tuple)

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def pick_best_from_candidates(urls: Iterable[str]) -> str | None:
    good = [u.strip() for u in urls if u and "wp-content/uploads/" in u and not _deny_url(u)]
    if not good:
        return None
    return max(good, key=_score_tuple)
