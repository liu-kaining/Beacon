"""Static page renderer using Jinja2."""

import json
import os

from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("index.jinja2")

    html = template.render(posts=posts)

    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[renderer] Generated {output_path} with {len(posts)} posts.")
