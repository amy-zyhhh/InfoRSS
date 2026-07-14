#!/usr/bin/env python3
"""List saved RSS items from the local SQLite database."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path("data/rss.sqlite3")


def parse_compact_date(value: str) -> dt.date:
    raw = value.strip()
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"expected YYYYMMDD, got {value!r}")
    return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def local_day_bounds(value: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(value, dt.time.min).astimezone()
    end = dt.datetime.combine(value, dt.time.max).astimezone()
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


def parse_date_range(value: str | None) -> tuple[dt.datetime | None, dt.datetime | None, str]:
    if value is None:
        return None, None, "all"

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
    if end_date != start_date:
        label = f"{label}-{end_date.strftime('%Y%m%d')}"
    return since, until, label


def local_time(value: str) -> str:
    if not value:
        return ""
    with contextlib.suppress(Exception):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    return value


def short_text(value: str, limit: int = 180) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def fetch_items(
    db_path: Path,
    since: dt.datetime | None,
    until: dt.datetime | None,
) -> list[sqlite3.Row]:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if since is None or until is None:
            return list(
                conn.execute(
                    """
                    SELECT id, unique_key_type, unique_key_value, title, link, guid,
                           published_at, updated_at, first_seen_at, last_seen_at, summary
                    FROM feed_items
                    ORDER BY published_at DESC, first_seen_at DESC
                    """
                )
            )
        return list(
            conn.execute(
                """
                SELECT id, unique_key_type, unique_key_value, title, link, guid,
                       published_at, updated_at, first_seen_at, last_seen_at, summary
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


def main() -> int:
    parser = argparse.ArgumentParser(description="List saved RSS items.")
    parser.add_argument("date_range", nargs="?", help="Date or date range, e.g. 20260713 or 20260712-20260713.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--summary", action="store_true", help="Show a short summary for each item.")
    args = parser.parse_args()

    try:
        since, until, label = parse_date_range(args.date_range)
        rows = fetch_items(args.db, since, until)
    except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
        print(f"Cannot list items: {exc}", file=sys.stderr)
        return 1

    print(f"Date range: {label}")
    print(f"Items: {len(rows)}")
    print()

    for index, row in enumerate(rows, start=1):
        print(f"[{index}] {row['title']}")
        print(f"    Published: {local_time(row['published_at'])}")
        print(f"    Link: {row['link']}")
        print(f"    Unique: {row['unique_key_type']} {row['unique_key_value']}")
        print(f"    ID: {row['id']}")
        if args.summary and row["summary"]:
            print(f"    Summary: {short_text(row['summary'])}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
