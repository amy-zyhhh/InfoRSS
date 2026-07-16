#!/usr/bin/env python3
"""Validate generated public site data before publishing."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


SEARCH_INDEX = Path("assets/search-index.json")
RAW_INDEX = Path("assets/raw-search-index.json")
BRIEF_DIR = Path("content/briefs")
RAW_ITEM_DIR = Path("content/raw/items")


def frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text[4:end], re.M)
    return match.group(1).strip().strip('"').strip("'") if match else ""


def tracked_forbidden_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", ".env", "data", "content/daily", "*.sqlite3", "*.sqlite3-shm", "*.sqlite3-wal"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def check() -> list[str]:
    errors: list[str] = []

    if not SEARCH_INDEX.exists():
        errors.append(f"missing {SEARCH_INDEX}")
        return errors
    if not RAW_INDEX.exists():
        errors.append(f"missing {RAW_INDEX}")
        return errors

    items = json.loads(SEARCH_INDEX.read_text(encoding="utf-8"))
    raw_texts = json.loads(RAW_INDEX.read_text(encoding="utf-8"))

    if not isinstance(items, list):
        errors.append("search index must be a list")
        return errors
    if not isinstance(raw_texts, dict):
        errors.append("raw search index must be an object")
        return errors

    seen_ids: set[str] = set()
    for item in items:
        item_id = item.get("id", "")
        if not item_id:
            errors.append("search item without id")
            continue
        if item_id in seen_ids:
            errors.append(f"duplicate search item id: {item_id}")
        seen_ids.add(item_id)

        raw_url = item.get("raw_url", "")
        if raw_url:
            raw_path = Path(raw_url.strip("/")).with_suffix(".md")
            if not raw_path.exists():
                errors.append(f"raw_url target missing for {item_id}: {raw_path}")
            if item_id not in raw_texts:
                errors.append(f"raw_text missing for {item_id}")

        page_url = item.get("page_url", "")
        if page_url:
            page_path = Path(page_url.strip("/")).with_suffix(".md")
            if not page_path.exists():
                errors.append(f"page_url target missing for {item_id}: {page_path}")

    for path in sorted(BRIEF_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        count_raw = frontmatter_value(text, "items_count")
        expected = None
        if count_raw:
            expected = int(count_raw)
            actual = len(re.findall(r"^###\s+", text, re.M))
            if expected != actual:
                errors.append(f"{path}: items_count={expected}, headings={actual}")
        if "清华大学信息门户通知整理" in text:
            errors.append(f"{path}: redundant body title remains")
        json_path = path.with_suffix(".json")
        if not json_path.exists():
            errors.append(f"{path}: missing JSON sidecar")
        else:
            sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            sidecar_count = len(sidecar.get("items", []))
            if expected is not None and sidecar_count != expected:
                errors.append(f"{json_path}: items={sidecar_count}, expected={expected}")

    forbidden = tracked_forbidden_files()
    if forbidden:
        errors.append("forbidden tracked files: " + ", ".join(forbidden))

    if not RAW_ITEM_DIR.exists() or not any(RAW_ITEM_DIR.glob("*.md")):
        errors.append(f"no public raw item pages in {RAW_ITEM_DIR}")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("Site check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Site check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
