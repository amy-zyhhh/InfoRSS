#!/usr/bin/env python3
"""Export saved RSS items to a daily Markdown file, writing only when changed."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import html
import re
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path("data/rss.sqlite3")
DEFAULT_OUTPUT_DIR = Path("content/daily")


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


def local_time(value: str) -> str:
    if not value:
        return ""
    with contextlib.suppress(Exception):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return value


def plain_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def escape_md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def fetch_items(db_path: Path, since: dt.datetime, until: dt.datetime) -> list[sqlite3.Row]:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                """
                SELECT id, unique_key_type, unique_key_value, title, link, guid,
                       published_at, updated_at, author, summary, content,
                       first_seen_at, last_seen_at
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


def render_markdown(rows: list[sqlite3.Row], label: str) -> str:
    generated_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "---",
        f"title: 清华信息门户原始通知 {label}",
        f"date_range: {label}",
        f"generated_at: {generated_at}",
        f"items_count: {len(rows)}",
        "---",
        "",
        f"# 清华信息门户原始通知 {label}",
        "",
        f"- 生成时间：{generated_at}",
        f"- 条目数量：{len(rows)}",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        title = row["title"] or "(无标题)"
        published = local_time(row["published_at"] or row["updated_at"])
        body = plain_text(row["content"] or row["summary"])
        lines.extend(
            [
                f"## {index}. {title}",
                "",
                f"- 发布时间：{published}",
                f"- 原文链接：[{escape_md(row['link'])}]({row['link']})",
                f"- 唯一标记：`{row['unique_key_type']}:{row['unique_key_value']}`",
                f"- 本地 ID：`{row['id']}`",
                "",
            ]
        )
        if body:
            lines.extend(["### 原始内容", "", body, ""])
        else:
            lines.extend(["> 暂无摘要或正文。", ""])

    return "\n".join(lines).rstrip() + "\n"


def comparable_markdown(value: str) -> str:
    value = re.sub(r"generated_at: .+", "generated_at: <ignored>", value)
    value = re.sub(r"- 生成时间：.+", "- 生成时间：<ignored>", value)
    return value


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if comparable_markdown(old) == comparable_markdown(content):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export saved RSS items to Markdown.")
    parser.add_argument("date_range", help="Date or date range, e.g. 20260713 or 20260712-20260713.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path, help="Write to a specific Markdown file.")
    args = parser.parse_args()

    try:
        since, until, label = parse_date_range(args.date_range)
        rows = fetch_items(args.db, since, until)
        output_path = args.output or args.output_dir / f"{label}.md"
        changed = write_if_changed(output_path, render_markdown(rows, label))
    except (ValueError, FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"Cannot export Markdown: {exc}", file=sys.stderr)
        return 1

    print(f"Date range: {label}")
    print(f"Items: {len(rows)}")
    print(f"Markdown: {output_path} ({'updated' if changed else 'unchanged, skipped duplicate write'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
