#!/usr/bin/env python3
"""Fetch an RSS feed, store raw snapshots, and index items in SQLite."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import email.utils
import hashlib
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_DB = Path("data/rss.sqlite3")
DEFAULT_RAW_DIR = Path("data/raw")
USER_AGENT = "InfoRSS/0.1 (+local archiver)"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = hostname
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"

    path = parsed.path or "/"
    query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)))
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def text_or_empty(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def child_text(parent: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(parent):
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names:
            return text_or_empty(child)
    return ""


def parse_datetime(value: str) -> str:
    if not value:
        return ""
    with contextlib.suppress(Exception):
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC).isoformat()
    with contextlib.suppress(Exception):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC).isoformat()
    return value.strip()


def parse_compact_date(value: str) -> dt.date:
    raw = value.strip()
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"expected YYYYMMDD, got {value!r}")
    return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def local_day_bounds(value: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(value, dt.time.min).astimezone()
    end = dt.datetime.combine(value, dt.time.max).astimezone()
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


def parse_date_range(value: str | None) -> tuple[dt.datetime, dt.datetime, str]:
    if value is None:
        yesterday = dt.datetime.now().astimezone().date() - dt.timedelta(days=1)
        since, until = local_day_bounds(yesterday)
        return since, until, yesterday.strftime("%Y%m%d")

    raw = value.strip()
    if not raw:
        raise ValueError("empty date range")

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


def item_datetime(item: dict[str, str]) -> dt.datetime | None:
    value = item["published_at"] or item["updated_at"]
    if not value:
        return None
    with contextlib.suppress(Exception):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    return None


def filter_items_by_time_range(
    items: list[dict[str, str]],
    since: dt.datetime | None,
    until: dt.datetime | None,
) -> tuple[list[dict[str, str]], int]:
    if since is None and until is None:
        return items, 0

    filtered: list[dict[str, str]] = []
    skipped = 0
    for item in items:
        value = item_datetime(item)
        if value is None:
            skipped += 1
            continue
        if since is not None and value < since:
            skipped += 1
            continue
        if until is not None and value > until:
            skipped += 1
            continue
        filtered.append(item)
    return filtered, skipped


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS feed_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            raw_path TEXT NOT NULL,
            headers_json TEXT NOT NULL,
            byte_length INTEGER NOT NULL,
            UNIQUE(content_hash)
        );

        CREATE TABLE IF NOT EXISTS feed_items (
            id TEXT PRIMARY KEY,
            unique_key_type TEXT NOT NULL,
            unique_key_value TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            feed_url TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            guid TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            author TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_xml TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_feed_items_published_at
            ON feed_items(published_at);
        CREATE INDEX IF NOT EXISTS idx_feed_items_last_seen_at
            ON feed_items(last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_feed_items_link
            ON feed_items(link);

        CREATE VIRTUAL TABLE IF NOT EXISTS feed_items_fts
            USING fts5(title, summary, content, link, content='feed_items', content_rowid='rowid');

        CREATE TRIGGER IF NOT EXISTS feed_items_ai AFTER INSERT ON feed_items BEGIN
            INSERT INTO feed_items_fts(rowid, title, summary, content, link)
            VALUES (new.rowid, new.title, new.summary, new.content, new.link);
        END;

        CREATE TRIGGER IF NOT EXISTS feed_items_ad AFTER DELETE ON feed_items BEGIN
            INSERT INTO feed_items_fts(feed_items_fts, rowid, title, summary, content, link)
            VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.link);
        END;

        CREATE TRIGGER IF NOT EXISTS feed_items_au AFTER UPDATE ON feed_items BEGIN
            INSERT INTO feed_items_fts(feed_items_fts, rowid, title, summary, content, link)
            VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.link);
            INSERT INTO feed_items_fts(rowid, title, summary, content, link)
            VALUES (new.rowid, new.title, new.summary, new.content, new.link);
        END;
        """
    )
    ensure_feed_items_columns(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feed_items_unique_key
            ON feed_items(unique_key_type, unique_key_value)
        """
    )
    return conn


def ensure_feed_items_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(feed_items)")}
    if "unique_key_type" not in columns:
        conn.execute("ALTER TABLE feed_items ADD COLUMN unique_key_type TEXT NOT NULL DEFAULT ''")
    if "unique_key_value" not in columns:
        conn.execute("ALTER TABLE feed_items ADD COLUMN unique_key_value TEXT NOT NULL DEFAULT ''")


def fetch(url: str, timeout: int) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        status_code = getattr(response, "status", 200)
        headers = {key.lower(): value for key, value in response.headers.items()}
        body = response.read()
    return status_code, headers, body


def save_snapshot(
    conn: sqlite3.Connection,
    raw_dir: Path,
    url: str,
    status_code: int,
    headers: dict[str, str],
    body: bytes,
    fetched_at: dt.datetime,
) -> Path:
    content_hash = sha256_bytes(body)
    existing = conn.execute(
        "SELECT raw_path FROM feed_snapshots WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if existing is not None:
        return Path(existing[0])

    day_dir = raw_dir / fetched_at.strftime("%Y") / fetched_at.strftime("%m") / fetched_at.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    raw_path = day_dir / f"{fetched_at.strftime('%H%M%S')}_{content_hash[:12]}.xml"
    if not raw_path.exists():
        raw_path.write_bytes(body)

    conn.execute(
        """
        INSERT OR IGNORE INTO feed_snapshots
            (fetched_at, url, status_code, content_hash, raw_path, headers_json, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fetched_at.isoformat(),
            url,
            status_code,
            content_hash,
            str(raw_path),
            json.dumps(headers, ensure_ascii=False, sort_keys=True),
            len(body),
        ),
    )
    return raw_path


def item_identity_marker(item: dict[str, str]) -> tuple[str, str]:
    canonical_url = normalize_url(item["link"])
    if canonical_url:
        return "url", canonical_url
    if item["guid"]:
        return "guid", item["guid"].strip()
    return "title_published_at", f"{item['title'].strip()}|{item['published_at'].strip()}"


def item_identity(item: dict[str, str]) -> str:
    key_type, key_value = item_identity_marker(item)
    return sha256_text(f"{key_type}:{key_value}")


def parse_items(body: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(body)
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name == "rss":
        containers = root.findall("./channel/item")
    elif root_name == "feed":
        containers = [child for child in list(root) if child.tag.rsplit("}", 1)[-1].lower() == "entry"]
    else:
        raise ValueError(f"Unsupported feed root element: {root.tag}")

    items: list[dict[str, str]] = []
    for container in containers:
        link = child_text(container, ("link",))
        if not link:
            for child in list(container):
                if child.tag.rsplit("}", 1)[-1].lower() == "link":
                    link = child.attrib.get("href", "").strip()
                    if link:
                        break

        raw_xml = ET.tostring(container, encoding="unicode")
        summary = child_text(container, ("description", "summary"))
        content = child_text(container, ("encoded", "content"))
        published = child_text(container, ("pubdate", "published", "issued", "date"))
        updated = child_text(container, ("updated", "modified"))
        item = {
            "title": child_text(container, ("title",)),
            "link": link,
            "guid": child_text(container, ("guid", "id")),
            "published_at": parse_datetime(published),
            "updated_at": parse_datetime(updated),
            "author": child_text(container, ("author", "creator")),
            "summary": summary,
            "content": content,
            "raw_xml": raw_xml,
        }
        item["unique_key_type"], item["unique_key_value"] = item_identity_marker(item)
        item["content_hash"] = sha256_text(
            "\n".join(
                [
                    item["title"],
                    item["link"],
                    item["guid"],
                    item["published_at"],
                    item["summary"],
                    item["content"],
                ]
            )
        )
        item["id"] = item_identity(item)
        items.append(item)
    return items


def upsert_items(conn: sqlite3.Connection, feed_url: str, items: list[dict[str, str]], seen_at: str) -> tuple[int, int, int]:
    inserted = 0
    updated = 0
    unchanged = 0
    for item in items:
        existing = conn.execute(
            "SELECT content_hash FROM feed_items WHERE id = ?",
            (item["id"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO feed_items (
                    id, unique_key_type, unique_key_value,
                    first_seen_at, last_seen_at, feed_url, title, link, guid,
                    published_at, updated_at, author, summary, content, raw_xml, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["unique_key_type"],
                    item["unique_key_value"],
                    seen_at,
                    seen_at,
                    feed_url,
                    item["title"],
                    item["link"],
                    item["guid"],
                    item["published_at"],
                    item["updated_at"],
                    item["author"],
                    item["summary"],
                    item["content"],
                    item["raw_xml"],
                    item["content_hash"],
                ),
            )
            inserted += 1
            conn.commit()
            print(f"Inserted: {item['title']}")
        elif existing[0] == item["content_hash"]:
            unchanged += 1
            print(f"Skipped duplicate: {item['title']}")
        else:
            conn.execute(
                """
                UPDATE feed_items
                SET last_seen_at = ?,
                    unique_key_type = ?,
                    unique_key_value = ?,
                    title = ?,
                    link = ?,
                    guid = ?,
                    published_at = ?,
                    updated_at = ?,
                    author = ?,
                    summary = ?,
                    content = ?,
                    raw_xml = ?,
                    content_hash = ?
                WHERE id = ?
                """,
                (
                    seen_at,
                    item["unique_key_type"],
                    item["unique_key_value"],
                    item["title"],
                    item["link"],
                    item["guid"],
                    item["published_at"],
                    item["updated_at"],
                    item["author"],
                    item["summary"],
                    item["content"],
                    item["raw_xml"],
                    item["content_hash"],
                    item["id"],
                ),
            )
            updated += 1
            conn.commit()
            print(f"Updated changed item: {item['title']}")
    return inserted, updated, unchanged


def main() -> int:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(description="Fetch and index an RSS/Atom feed.")
    parser.add_argument(
        "date_range",
        nargs="?",
        help="Date or date range to save, e.g. 20260712 or 20260712-20260713. Defaults to yesterday.",
    )
    parser.add_argument("--url", default=os.getenv("INFORS_RSS_URL"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    if not args.url:
        print("Missing RSS URL. Set INFORS_RSS_URL or pass --url.", file=sys.stderr)
        return 2

    try:
        since, until, date_range_label = parse_date_range(args.date_range)
    except ValueError as exc:
        print(f"Invalid date range: {exc}", file=sys.stderr)
        return 2

    fetched_at = utc_now()
    conn = init_db(args.db)
    try:
        status_code, headers, body = fetch(args.url, args.timeout)
        if status_code < 200 or status_code >= 300:
            print(f"Fetch failed: HTTP {status_code}", file=sys.stderr)
            return 1
        raw_path = save_snapshot(conn, args.raw_dir, args.url, status_code, headers, body, fetched_at)
        conn.commit()
        all_items = parse_items(body)
        items, skipped_by_time = filter_items_by_time_range(all_items, since, until)
        inserted, updated, unchanged = upsert_items(conn, args.url, items, fetched_at.isoformat())
    except urllib.error.URLError as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"XML parse failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"Fetched: {len(body)} bytes")
    print(f"Date range: {date_range_label}")
    print(f"Raw snapshot: {raw_path}")
    print(f"Parsed items: {len(all_items)}")
    print(f"Saved items after time filter: {len(items)}")
    print(f"Skipped by time filter: {skipped_by_time}")
    print(f"New items: {inserted}")
    print(f"Updated changed items: {updated}")
    print(f"Skipped duplicate items: {unchanged}")
    print(f"Database: {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
