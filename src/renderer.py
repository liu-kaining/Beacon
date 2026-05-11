"""Static page renderer using Jinja2."""

import json
import os

import markdown
from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_MD_EXTENSIONS = ["tables", "fenced_code", "nl2br"]


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

    posts = [_enrich_post(p) for p in posts if isinstance(p, dict)]

    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("index.jinja2")

    html = template.render(posts=posts)

    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[renderer] Generated {output_path} with {len(posts)} posts.")
