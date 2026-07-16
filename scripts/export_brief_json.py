#!/usr/bin/env python3
"""Export structured JSON sidecars from AI brief Markdown files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_search_index import parse_brief, parse_frontmatter


DEFAULT_INPUT_DIR = Path("content/briefs")


def export_one(path: Path) -> bool:
    markdown = path.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(markdown)
    items = parse_brief(path)
    public_items = []
    for item in items:
        public_items.append(
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "source_url": item.get("source_url", ""),
                "raw_url": item.get("raw_url", ""),
                "page_url": item.get("page_url", ""),
                "item_url": item.get("item_url", ""),
                "published_at": item.get("published_at", ""),
                "category": item.get("category", ""),
                "audience": item.get("audience", ""),
                "keywords": item.get("keywords", ""),
                "summary": item.get("summary", ""),
            }
        )

    content = json.dumps(
        {
            "title": meta.get("title") or path.stem,
            "date_range": meta.get("date_range") or path.stem,
            "generated_at": meta.get("generated_at", ""),
            "items_count": len(public_items),
            "items": public_items,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    output = path.with_suffix(".json")
    if output.exists() and output.read_text(encoding="utf-8") == content:
        return False
    output.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export JSON sidecars from content/briefs Markdown.")
    parser.add_argument("date_range", nargs="?", help="Optional date range stem, e.g. 20260713.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    args = parser.parse_args()

    if args.date_range:
        paths = [args.input_dir / f"{args.date_range}.md"]
    else:
        paths = sorted(args.input_dir.glob("*.md"))

    changed = 0
    exported = 0
    for path in paths:
        if not path.exists():
            continue
        exported += 1
        if export_one(path):
            changed += 1

    print(f"JSON sidecars: {exported}")
    print(f"Changed files: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
