#!/usr/bin/env python3
"""Build a client-side search index from AI-generated brief Markdown files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


DEFAULT_INPUT_DIR = Path("content/briefs")
DEFAULT_OUTPUT = Path("assets/search-index.json")
DEFAULT_RAW_OUTPUT = Path("assets/raw-search-index.json")


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^\*\s+\*\*(.+?)\*\*:\s*(.+?)\s*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(markdown)
    if match is None:
        return {}, markdown

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, markdown[match.end() :]


def clean_inline(value: str) -> str:
    value = value.strip()
    link = LINK_RE.search(value)
    if link:
        return link.group(2).strip()
    return re.sub(r"\*\*|`", "", value).strip()


def parse_heading_title(value: str) -> tuple[str, str]:
    link = LINK_RE.fullmatch(value.strip())
    if link:
        return link.group(1).strip(), link.group(2).strip()
    return value.strip(), ""


def item_url(date_range: str, item_index: int) -> str:
    return f"/content/briefs/{date_range}/#item-{item_index}"


def raw_slug(source_url: str, fallback: str) -> str:
    stable = source_url or fallback
    return hashlib.sha1(stable.encode("utf-8", errors="replace")).hexdigest()[:16]


def raw_item_path(source_url: str, fallback: str) -> Path:
    return Path("content/raw/items") / f"{raw_slug(source_url, fallback)}.md"


def raw_url(source_url: str, fallback: str) -> str:
    slug = raw_slug(source_url, fallback)
    path = Path("content/raw/items") / f"{slug}.md"
    if not path.exists():
        return ""
    return f"/content/raw/items/{slug}/"


def raw_text(source_url: str, fallback: str) -> str:
    path = raw_item_path(source_url, fallback)
    if not path.exists():
        return ""
    markdown = path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(markdown)
    return re.sub(r"\s+", " ", body).strip()


def parse_brief(path: Path) -> list[dict[str, str]]:
    markdown = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(markdown)
    date_range = meta.get("date_range") or path.stem
    page_url = f"/content/briefs/{path.stem}/"

    category = "其他"
    current: dict[str, str] | None = None
    items: list[dict[str, str]] = []

    def finish_current() -> None:
        if current is None:
            return
        current["text"] = " ".join(
            [
                current.get("title", ""),
                current.get("category", ""),
                current.get("audience", ""),
                current.get("keywords", ""),
                current.get("summary", ""),
            ]
        )
        if current.get("raw_text"):
            current["raw_index_url"] = "/assets/raw-search-index.json"
        items.append(current.copy())

    item_index = 0
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level, title = heading.groups()
            if level == "##":
                finish_current()
                current = None
                category = title.strip()
            elif level == "###":
                finish_current()
                item_index += 1
                item_title, source_url = parse_heading_title(title)
                current = {
                    "id": f"{date_range}-{item_index}",
                    "date_range": date_range,
                    "category": category,
                    "title": item_title,
                    "published_at": "",
                    "audience": "",
                    "keywords": "",
                    "summary": "",
                    "source_url": source_url,
                    "raw_url": raw_url(source_url, f"{date_range}-{item_index}"),
                    "raw_text": raw_text(source_url, f"{date_range}-{item_index}"),
                    "page_url": page_url,
                    "item_url": item_url(path.stem, item_index),
                }
            continue

        if current is None:
            continue

        field = FIELD_RE.match(line)
        if not field:
            continue

        name, value = field.groups()
        value = clean_inline(value)
        if name == "发布时间":
            current["published_at"] = value
        elif name == "适用对象":
            current["audience"] = value
        elif name == "关键词":
            current["keywords"] = value
        elif name == "摘要":
            current["summary"] = value
        elif name == "原文链接":
            current["source_url"] = value

    finish_current()
    return items


def build_index(input_dir: Path) -> list[dict[str, str]]:
    if not input_dir.exists():
        return []

    items: list[dict[str, str]] = []
    for path in sorted(input_dir.glob("*.md")):
        items.extend(parse_brief(path))
    items.sort(key=lambda item: (item["published_at"], item["title"]), reverse=True)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a JSON search index from content/briefs.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    args = parser.parse_args()

    try:
        items = build_index(args.input_dir)
        raw_items = {
            item["id"]: item.pop("raw_text", "")
            for item in items
            if item.get("raw_text")
        }
        content = json.dumps(items, ensure_ascii=False, indent=2) + "\n"
        raw_content = json.dumps(raw_items, ensure_ascii=False, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists() and args.output.read_text(encoding="utf-8") == content:
            changed = False
        else:
            args.output.write_text(content, encoding="utf-8")
            changed = True
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        if args.raw_output.exists() and args.raw_output.read_text(encoding="utf-8") == raw_content:
            raw_changed = False
        else:
            args.raw_output.write_text(raw_content, encoding="utf-8")
            raw_changed = True
    except OSError as exc:
        print(f"Cannot build search index: {exc}", file=sys.stderr)
        return 1

    print(f"Items: {len(items)}")
    print(f"Raw text items: {len(raw_items)}")
    print(f"Index: {args.output} ({'updated' if changed else 'unchanged, skipped duplicate write'})")
    print(f"Raw index: {args.raw_output} ({'updated' if raw_changed else 'unchanged, skipped duplicate write'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
