"""Main orchestrator for Project Beacon pipeline."""

import json
import os
import sys

from dotenv import load_dotenv

from scraper import fetch_articles
from storage import process_image
from ai_processor import generate_analysis
from renderer import render_site

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "posts.json")


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


def main() -> None:
    """Run the full pipeline: scrape -> process -> store -> render."""
    load_dotenv()

    print("[beacon] Starting pipeline...")

    # Load existing posts for idempotency
    existing_posts = load_existing_posts()
    existing_ids = {p["id"] for p in existing_posts}
    print(f"[beacon] Found {len(existing_posts)} existing posts.")

    # Fetch new articles from RSS
    articles = fetch_articles()
    print(f"[beacon] Fetched {len(articles)} articles from RSS.")

    new_posts = []

    for article in articles:
        article_id = article["id"]

        # Skip if already processed
        if article_id in existing_ids:
            print(f"[beacon] Skipping existing article: {article_id}")
            continue

        print(f"[beacon] Processing article: {article_id} - {article['title'][:50]}...")

        try:
            # Process image
            r2_image_url = ""
            base64_blur = ""
            if article.get("image_url"):
                result = process_image(article["image_url"], article_id)
                if result:
                    r2_image_url, base64_blur = result

            # Generate AI analysis
            ai_analysis = None
            if article.get("content_md"):
                ai_analysis = generate_analysis(article["title"], article["content_md"])

            if not ai_analysis:
                print(f"[beacon] AI analysis failed for {article_id}, using fallback.")
                ai_analysis = {
                    "core_insight": "暂无分析数据",
                    "data_highlights": [],
                    "deep_dive": "内容暂不可用。",
                    "glossary": [],
                }

            post = {
                "id": article_id,
                "title": article["title"],
                "original_url": article["original_url"],
                "r2_image_url": r2_image_url,
                "base64_blur": base64_blur,
                "pub_date": article["pub_date"],
                "ai_analysis": ai_analysis,
            }

            new_posts.append(post)
            print(f"[beacon] Successfully processed: {article_id}")

        except Exception as e:
            print(f"[beacon] Error processing article {article_id}: {e}")
            continue

    # Prepend new posts to existing posts
    if new_posts:
        all_posts = new_posts + existing_posts
        save_posts(all_posts)
        print(f"[beacon] Added {len(new_posts)} new posts. Total: {len(all_posts)}")
    else:
        print("[beacon] No new posts to add.")

    # Render the static site
    render_site()
    print("[beacon] Pipeline complete!")


if __name__ == "__main__":
    main()
