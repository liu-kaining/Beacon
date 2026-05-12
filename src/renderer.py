"""Static page renderer using Jinja2."""

import json
import os
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring

import markdown

# Register atom namespace so output uses "atom:" prefix instead of "ns0:"
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_MD_EXTENSIONS = ["tables", "fenced_code", "nl2br"]

# Placeholder when AI analysis fails; such posts must not be persisted or rendered.
INVALID_AI_CORE_INSIGHT = "暂无分析数据"


def has_valid_ai_analysis(post: dict) -> bool:
    """True if the post has real AI content (not the pipeline failure placeholder)."""
    ai = post.get("ai_analysis") or {}
    return (ai.get("core_insight") or "") != INVALID_AI_CORE_INSIGHT


def has_valid_hero_image(post: dict) -> bool:
    """True if the post has an R2 hero chart URL (posts without one stay in JSON but are not shown)."""
    return bool((post.get("r2_image_url") or "").strip())


def is_post_visible(post: dict) -> bool:
    """Shown on the site and RSS only when analysis and hero image are both present."""
    return has_valid_ai_analysis(post) and has_valid_hero_image(post)


def _markdown_to_html(text: str) -> str:
    if not (text or "").strip():
        return ""
    return markdown.markdown(text, extensions=_MD_EXTENSIONS)


def _enrich_post(post: dict) -> dict:
    """Attach pre-rendered HTML and search blob for the template / client JS."""
    p = dict(post)
    p["content_html"] = _markdown_to_html(p.get("content_md") or "")

    ai = dict(p.get("ai_analysis") or {})
    ai.setdefault("data_tables", [])
    dd = ai.get("deep_dive") or ""
    ai["deep_dive_html"] = _markdown_to_html(dd)
    p["ai_analysis"] = ai

    parts: list[str] = [
        str(p.get("title") or ""),
        str(ai.get("core_insight") or ""),
        str(dd),
        " ".join(str(x) for x in (ai.get("data_highlights") or [])),
    ]
    for g in ai.get("glossary") or []:
        if isinstance(g, dict):
            parts.append(str(g.get("term") or ""))
            parts.append(str(g.get("explanation") or ""))
    for t in ai.get("data_tables") or []:
        if isinstance(t, dict):
            parts.append(str(t.get("caption") or ""))
            parts.extend(str(x) for x in (t.get("headers") or []))
            for row in t.get("rows") or []:
                if isinstance(row, list):
                    parts.extend(str(c) for c in row)
    blob = " ".join(parts).lower()
    p["search_text"] = blob[:12000]
    return p


def render_site() -> None:
    """Read posts.json and render the static HTML site."""
    data_path = os.path.join(PROJECT_ROOT, "data", "posts.json")
    template_dir = os.path.join(PROJECT_ROOT, "templates")
    output_dir = os.path.join(PROJECT_ROOT, "docs")
    output_path = os.path.join(output_dir, "index.html")

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if not isinstance(posts, list):
            print(f"[renderer] Invalid posts format in {data_path}, expected list.")
            posts = []
    except FileNotFoundError:
        posts = []
    except json.JSONDecodeError as e:
        print(f"[renderer] Failed to parse {data_path}: {e}")
        posts = []

    posts = [
        _enrich_post(p)
        for p in posts
        if isinstance(p, dict) and is_post_visible(p)
    ]

    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("index.jinja2")

    html = template.render(posts=posts)

    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[renderer] Generated {output_path} with {len(posts)} posts.")


def _parse_pub_date(raw: str) -> datetime | None:
    """Try to parse the RFC 2822 pub_date string into a datetime."""
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def render_rss() -> None:
    """Read posts.json and generate an RSS 2.0 feed at docs/feed.xml."""
    data_path = os.path.join(PROJECT_ROOT, "data", "posts.json")
    output_dir = os.path.join(PROJECT_ROOT, "docs")
    output_path = os.path.join(output_dir, "feed.xml")

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if not isinstance(posts, list):
            posts = []
    except (FileNotFoundError, json.JSONDecodeError):
        posts = []

    site_url = "https://beacon.thetamind.ai"
    feed_url = f"{site_url}/feed.xml"

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = "Beacon - Decoding Global Trends"
    SubElement(channel, "link").text = site_url
    SubElement(channel, "description").text = (
        "全球宏观经济数据可视化与 AI 深度解读"
    )
    SubElement(channel, "language").text = "zh-CN"
    SubElement(channel, "generator").text = "Beacon RSS Generator"

    # atom:link for self-reference (RSS best practice)
    SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        href=feed_url,
        rel="self",
        type="application/rss+xml",
    )

    # lastBuildDate
    now = datetime.now(timezone.utc)
    SubElement(channel, "lastBuildDate").text = format_datetime(now)

    # Sort posts by pub_date descending, take latest 50
    def sort_key(p: dict) -> datetime:
        dt = _parse_pub_date(p.get("pub_date", ""))
        return dt if dt else datetime.min.replace(tzinfo=timezone.utc)

    sorted_posts = sorted(
        (p for p in posts if isinstance(p, dict) and is_post_visible(p)),
        key=sort_key,
        reverse=True,
    )[:50]

    for post in sorted_posts:
        ai = post.get("ai_analysis") or {}
        core_insight = ai.get("core_insight") or ""
        highlights = ai.get("data_highlights") or []
        deep_dive = ai.get("deep_dive") or ""

        # Build description from AI analysis
        desc_parts: list[str] = []
        if core_insight and core_insight != INVALID_AI_CORE_INSIGHT:
            desc_parts.append(f"**{core_insight}**")
        if highlights:
            desc_parts.append("\n".join(f"- {h}" for h in highlights))
        if deep_dive:
            desc_parts.append(deep_dive)

        description_md = "\n\n".join(desc_parts) if desc_parts else post.get("title", "")
        description_html = markdown.markdown(description_md, extensions=_MD_EXTENSIONS)

        item = SubElement(channel, "item")
        SubElement(item, "title").text = post.get("title", "")
        SubElement(item, "link").text = post.get("original_url", "")
        SubElement(item, "description").text = description_html
        SubElement(item, "guid", isPermaLink="false").text = post.get("id", "")

        pub_date = post.get("pub_date", "")
        if pub_date:
            SubElement(item, "pubDate").text = pub_date

        # Include image as enclosure if available
        r2_url = post.get("r2_image_url", "")
        if r2_url:
            SubElement(
                item,
                "enclosure",
                url=r2_url,
                type="image/webp",
                length="0",
            )

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_output)

    print(f"[renderer] Generated {output_path} with {len(sorted_posts)} items in RSS feed.")
