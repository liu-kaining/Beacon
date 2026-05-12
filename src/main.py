"""Main orchestrator for Project Beacon pipeline."""

import json
import os
import time

from dotenv import load_dotenv

from scraper import fetch_articles
from storage import process_image
from ai_processor import generate_analysis
from renderer import render_rss, render_site

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "posts.json")

FALLBACK_INSIGHT = "暂无分析数据"


def load_existing_posts() -> list[dict]:
    """Load existing posts from JSON file."""
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_posts(posts: list[dict]) -> None:
    """Save posts to JSON file."""
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def _has_fallback_analysis(post: dict) -> bool:
    """Check if a post has fallback (failed) AI analysis."""
    ai = post.get("ai_analysis", {})
    return ai.get("core_insight") == FALLBACK_INSIGHT


def main() -> None:
    """Run the full pipeline: scrape -> process -> store -> render."""
    load_dotenv()

    print("[beacon] Starting pipeline...")

    # Load existing posts
    existing_posts = load_existing_posts()
    print(f"[beacon] Found {len(existing_posts)} existing posts.")

    # Separate successful posts from failed ones
    successful_posts = [p for p in existing_posts if not _has_fallback_analysis(p)]
    failed_urls = {p["original_url"] for p in existing_posts if _has_fallback_analysis(p)}

    if failed_urls:
        print(f"[beacon] Found {len(failed_urls)} posts with failed AI analysis, will retry.")

    # existing_urls only includes successfully analyzed posts
    # so fallback posts will be re-fetched from RSS
    existing_urls = {p["original_url"] for p in successful_posts}

    # Fetch new + retry articles from RSS
    articles = fetch_articles(existing_urls)
    print(f"[beacon] Fetched {len(articles)} articles from RSS.")

    new_posts = []

    for article in articles:
        is_retry = article["original_url"] in failed_urls
        action = "Retrying" if is_retry else "Processing"
        print(f"[beacon] {action}: {article['title'][:60]}...")

        try:
            # Process image (skip re-upload if already exists)
            r2_image_url = ""
            base64_blur = ""
            if is_retry:
                # Find existing post to reuse image
                existing = next(
                    (p for p in existing_posts if p["original_url"] == article["original_url"]),
                    None,
                )
                if existing:
                    r2_image_url = existing.get("r2_image_url", "")
                    base64_blur = existing.get("base64_blur", "")

            if not r2_image_url and article.get("image_url"):
                result = process_image(article["image_url"], article["id"])
                if result:
                    r2_image_url, base64_blur = result
                    image_version = int(time.time())
                else:
                    image_version = None
            else:
                image_version = None

            # Generate AI analysis
            ai_analysis = None
            if article.get("content_md"):
                ai_analysis = generate_analysis(article["title"], article["content_md"])

            if not ai_analysis:
                print(f"[beacon] AI analysis failed for {article['id']}, will retry next run.")
                ai_analysis = {
                    "core_insight": FALLBACK_INSIGHT,
                    "data_highlights": [],
                    "data_tables": [],
                    "deep_dive": "内容暂不可用。",
                    "glossary": [],
                }

            post = {
                "id": article["id"],
                "title": article["title"],
                "original_url": article["original_url"],
                "r2_image_url": r2_image_url,
                "base64_blur": base64_blur,
                "image_version": image_version,
                "pub_date": article["pub_date"],
                "content_md": article.get("content_md") or "",
                "ai_analysis": ai_analysis,
            }

            new_posts.append(post)
            status = "retried" if is_retry else "processed"
            print(f"[beacon] Successfully {status}: {article['id']}")

        except Exception as e:
            print(f"[beacon] Error processing article {article['id']}: {e}")
            continue

    # Deduplicate by original_url, keep first occurrence (newest)
    seen_urls: set[str] = set()
    deduped_posts = []

    for post in new_posts + existing_posts:
        url = post["original_url"]
        if url not in seen_urls:
            seen_urls.add(url)
            deduped_posts.append(post)

    removed = len(new_posts) + len(existing_posts) - len(deduped_posts)
    if removed > 0:
        print(f"[beacon] Removed {removed} duplicate posts.")

    if new_posts or removed > 0:
        save_posts(deduped_posts)
        print(f"[beacon] Total posts: {len(deduped_posts)}")
    else:
        print("[beacon] No new posts to add.")

    # Render the static site and RSS feed
    render_site()
    render_rss()
    print("[beacon] Pipeline complete!")


if __name__ == "__main__":
    main()
