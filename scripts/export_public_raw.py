#!/usr/bin/env python3
"""Export captured raw item text to public Markdown pages."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import html
import re
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path("data/rss.sqlite3")
DEFAULT_OUTPUT_DIR = Path("content/raw")


def parse_compact_date(value: str) -> dt.date:
    raw = value.strip()
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"expected YYYYMMDD, got {value!r}")
    return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def local_day_bounds(value: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(value, dt.time.min).astimezone()
    end = dt.datetime.combine(value, dt.time.max).astimezone()
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


def parse_date_range(value: str) -> tuple[dt.datetime, dt.datetime, str]:
    raw = value.strip()
    if "-" in raw:
        start_raw, end_raw = raw.split("-", 1)
        start_date = parse_compact_date(start_raw)
        end_date = parse_compact_date(end_raw)
    else:
        start_date = parse_compact_date(raw)
        end_date = start_date

    if start_date > end_date:
        raise ValueError("start date is later than end date")

    since, _ = local_day_bounds(start_date)
    _, until = local_day_bounds(end_date)
    label = start_date.strftime("%Y%m%d")
    if start_date != end_date:
        label = f"{label}-{end_date.strftime('%Y%m%d')}"
    return since, until, label


def plain_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def local_time(value: str) -> str:
    if not value:
        return ""
    with contextlib.suppress(Exception):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return value


def raw_slug(source_url: str, item_id: str) -> str:
    stable = source_url or item_id
    return hashlib.sha1(stable.encode("utf-8", errors="replace")).hexdigest()[:16]


def fetch_items(db_path: Path, since: dt.datetime, until: dt.datetime) -> list[sqlite3.Row]:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                """
                SELECT id, title, link, published_at, updated_at, summary, content
                FROM feed_items
                WHERE COALESCE(NULLIF(published_at, ''), updated_at) >= ?
                  AND COALESCE(NULLIF(published_at, ''), updated_at) <= ?
                ORDER BY published_at ASC, first_seen_at ASC
                """,
                (since.isoformat(), until.isoformat()),
            )
        )
    finally:
        conn.close()


def yaml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_item(row: sqlite3.Row, label: str) -> str:
    body = plain_text(row["content"] or row["summary"])
    if not body:
        body = "暂无抓取正文。"
    return "\n".join(
        [
            "---",
            "layout: raw_item",
            f"title: {yaml_string(row['title'] or '(无标题)')}",
            f"date_range: {yaml_string(label)}",
            f"published_at: {yaml_string(local_time(row['published_at'] or row['updated_at']))}",
            f"source_url: {yaml_string(row['link'] or '')}",
            f"item_id: {yaml_string(row['id'])}",
            "---",
            "",
            body,
            "",
        ]
    )


def render_day(rows: list[sqlite3.Row], label: str) -> str:
    lines = [
        "---",
        "layout: raw_day",
        f"title: {yaml_string('已抓取的原文 ' + label)}",
        f"date_range: {yaml_string(label)}",
        f"items_count: {len(rows)}",
        "---",
        "",
        f"# 已抓取的原文 {label}",
        "",
    ]
    for row in rows:
        slug = raw_slug(row["link"], row["id"])
        lines.extend(
            [
                f"## [{row['title']}]({{{{ '/content/raw/items/{slug}/' | relative_url }}}})",
                "",
                f"- 发布时间：{local_time(row['published_at'] or row['updated_at'])}",
                f"- 原文网页：[{row['link']}]({row['link']})",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export captured raw item text to public pages.")
    parser.add_argument("date_range", help="Date or date range, e.g. 20260713 or 20260712-20260713.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    try:
        since, until, label = parse_date_range(args.date_range)
        rows = fetch_items(args.db, since, until)
    except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
        print(f"Cannot export public raw pages: {exc}", file=sys.stderr)
        return 1

    changed = 0
    for row in rows:
        slug = raw_slug(row["link"], row["id"])
        item_path = args.output_dir / "items" / f"{slug}.md"
        if write_if_changed(item_path, render_item(row, label)):
            changed += 1

    day_path = args.output_dir / "daily" / f"{label}.md"
    if write_if_changed(day_path, render_day(rows, label)):
        changed += 1

    print(f"Date range: {label}")
    print(f"Raw public items: {len(rows)}")
    print(f"Changed files: {changed}")
    print(f"Raw day page: {day_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
