"""Backfill and overwrite R2 images for existing posts.

This script re-determines the best (full) visualization image for each post and
re-uploads it to Cloudflare R2 using the existing `{post['id']}.webp` key.
That means the public URL stays stable while the underlying object is replaced.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import Image

from storage import process_image


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_PATH = os.path.join(PROJECT_ROOT, "data", "posts.json")
FEED_URL = "https://www.visualcapitalist.com/feed/"


def _score_url(url: str) -> tuple[int, int]:
    u = url.lower()
    score = 0
    if "_site" in u or "website" in u:
        score += 100
    if "share" in u:
        score -= 50
    if any(k in u for k in ("webinar", "register", "banner", "sponsor", "doubleclick", "adserver")):
        score -= 200
    if u.endswith(".webp"):
        score += 5
    return (score, len(url))


def _pick_best_image_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    candidates: list[str] = []

    # Strong preference: rss-image block contains the intended visualization.
    rss_block = soup.find("div", class_="rss-image")
    search_roots = [rss_block] if rss_block else [soup]

    # Prefer content images inside the article.
    for root in search_roots:
        if not root:
            continue
        for img in root.find_all("img"):
            src = img.get("src") or ""
            if not src:
                continue
            if "wp-content/uploads/" not in src:
                continue
            low = src.lower()
            if any(k in low for k in ("voronoi", "cropped-logo", "logo", "icon", "app-store", "google-play")):
                continue
            if any(k in low for k in ("webinar", "register", "banner", "sponsor", "doubleclick", "adserver")):
                continue
            candidates.append(src)

            # Also consider srcset (often contains higher-res variants)
            srcset = img.get("srcset") or ""
            if srcset:
                for part in srcset.split(","):
                    url_part = part.strip().split(" ")[0]
                    if "wp-content/uploads/" in url_part:
                        candidates.append(url_part)

    if not candidates:
        # Fallback: og:image (often a share card)
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
        return None

    return sorted(set(candidates), key=_score_url, reverse=True)[0]


def _build_feed_image_map(max_pages: int, target_count: int | None = None) -> dict[str, str]:
    """Map article original_url -> best image url from RSS pages."""
    mapping: dict[str, str] = {}
    for page in range(1, max_pages + 1):
        url = FEED_URL if page == 1 else f"{FEED_URL}?paged={page}"
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False):
            err = getattr(feed, "bozo_exception", None)
            print(f"[backfill] Feed parse warning on page {page}: {err}")
        if not feed.entries:
            break

        for entry in feed.entries:
            article_url = entry.get("link") or ""
            if not article_url or article_url in mapping:
                continue

            # Prefer the visualization image embedded in content:encoded, otherwise media:content.
            content_encoded = ""
            if entry.get("content"):
                content_encoded = entry["content"][0].get("value", "")
            best = _pick_best_image_from_html(content_encoded) if content_encoded else None
            if not best:
                media_content = entry.get("media_content") or []
                for media in media_content:
                    u = media.get("url")
                    if u:
                        best = u
                        break
            if best:
                mapping[article_url] = best

        if target_count is not None and len(mapping) >= target_count:
            break

    return mapping


def _iter_posts() -> list[dict]:
    with open(POSTS_PATH, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not isinstance(posts, list):
        raise ValueError(f"Invalid posts format in {POSTS_PATH}, expected list")
    return posts


def _validate_image_url(url: str) -> bool:
    """Quick validation that the URL points to a decodable image."""
    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BeaconBot/1.0)"},
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img.load()
        return True
    except Exception as e:
        print(f"[backfill] Image validate failed: {url} ({e})")
        return False


def backfill(
    *,
    limit: int | None,
    max_feed_pages: int,
    dry_run: bool,
    use_feed: bool,
) -> None:
    posts = _iter_posts()
    feed_map: dict[str, str] = {}
    if use_feed:
        feed_map = _build_feed_image_map(max_feed_pages, target_count=len(posts))
    print(f"[backfill] Loaded {len(posts)} posts. Feed map has {len(feed_map)} urls.")

    updated = 0
    processed = 0

    for post in posts:
        if limit is not None and processed >= limit:
            break
        processed += 1

        post_id = post.get("id")
        article_url = post.get("original_url")
        if not post_id or not article_url:
            continue

        best_image_url = feed_map.get(article_url)
        if not best_image_url:
            # Fallback: fetch page and pick best.
            try:
                resp = requests.get(
                    article_url,
                    timeout=30,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; BeaconBot/1.0)"},
                )
                resp.raise_for_status()
                best_image_url = _pick_best_image_from_html(resp.text)
            except Exception as e:
                print(f"[backfill] Failed to fetch page for {article_url}: {e}")
                continue

        if not best_image_url:
            print(f"[backfill] No image found for {article_url}")
            continue

        # Optional sanity check before burning R2 writes.
        if not _validate_image_url(best_image_url):
            continue

        if dry_run:
            print(f"[backfill] (dry-run) {post_id}: {best_image_url}")
            continue

        result = process_image(best_image_url, str(post_id))
        if not result:
            continue

        r2_url, blur = result
        post["r2_image_url"] = r2_url
        post["base64_blur"] = blur
        post["source_image_url"] = best_image_url
        post["image_version"] = int(time.time())
        updated += 1

        if updated % 10 == 0:
            print(f"[backfill] Updated {updated}/{processed}...")
            time.sleep(0.3)

    if dry_run:
        print(f"[backfill] Dry-run complete. Evaluated {processed} posts.")
        return

    with open(POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"[backfill] Complete. Updated {updated} posts and wrote {POSTS_PATH}.")


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="Only process N posts")
    p.add_argument("--max-feed-pages", type=int, default=12, help="RSS pagination depth")
    p.add_argument("--dry-run", action="store_true", help="Print actions without uploading")
    p.add_argument(
        "--no-feed",
        action="store_true",
        help="Skip RSS mapping and fetch each article page directly",
    )
    return p.parse_args(argv)


def main() -> None:
    load_dotenv()
    args = _parse_args()
    backfill(
        limit=args.limit,
        max_feed_pages=args.max_feed_pages,
        dry_run=args.dry_run,
        use_feed=not args.no_feed,
    )


if __name__ == "__main__":
    main()

