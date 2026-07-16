#!/usr/bin/env python3
"""Incrementally summarize and classify saved RSS items with an OpenAI-compatible API."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_DB = Path("data/rss.sqlite3")
DEFAULT_OUTPUT_DIR = Path("content/briefs")
DEFAULT_FAILURE_DIR = Path("data/ai_failures")
DEFAULT_MAX_CHARS = 12000
CATEGORIES = ["教务", "科研", "行政", "学工", "讲座活动", "招聘", "其他"]


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


def init_ai_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_item_briefs (
            item_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            category TEXT NOT NULL,
            audience TEXT NOT NULL,
            importance TEXT NOT NULL,
            keywords_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES feed_items(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_item_briefs_category ON ai_item_briefs(category)")
    conn.commit()


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_ai_db(conn)
    return conn


def fetch_items(conn: sqlite3.Connection, since: dt.datetime, until: dt.datetime) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, unique_key_type, unique_key_value, title, link, guid,
                   published_at, updated_at, author, summary, content,
                   first_seen_at, last_seen_at, content_hash
            FROM feed_items
            WHERE COALESCE(NULLIF(published_at, ''), updated_at) >= ?
              AND COALESCE(NULLIF(published_at, ''), updated_at) <= ?
            ORDER BY published_at ASC, first_seen_at ASC
            """,
            (since.isoformat(), until.isoformat()),
        )
    )


def cached_brief(conn: sqlite3.Connection, row: sqlite3.Row, model: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM ai_item_briefs
        WHERE item_id = ?
          AND content_hash = ?
          AND model = ?
        """,
        (row["id"], row["content_hash"], model),
    ).fetchone()


def build_item_prompt(row: sqlite3.Row, max_chars: int) -> str:
    body = plain_text(row["content"] or row["summary"])[:max_chars]
    return json.dumps(
        {
            "task": "请整理这条清华大学信息门户通知，输出严格 JSON。",
            "schema": {
                "category": f"只能从这些类别选择：{', '.join(CATEGORIES)}",
                "audience": "适用对象，尽量简短",
                "keywords": "3-5 个关键词数组",
                "summary": "2-4 句中文摘要，不编造正文中没有的信息",
            },
            "item": {
                "id": row["id"],
                "title": row["title"],
                "published_at": local_time(row["published_at"] or row["updated_at"]),
                "link": row["link"],
                "unique_key": f"{row['unique_key_type']}:{row['unique_key_value']}",
                "content": body,
            },
        },
        ensure_ascii=False,
    )


def call_openai_compatible_api(base_url: str, api_key: str, model: str, prompt: str, timeout: int) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的信息整理助手。只输出一个 JSON 对象，不要输出 Markdown 或代码块。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def parse_ai_json(value: str) -> dict[str, object]:
    cleaned = value.strip()
    cleaned = re.sub(r"\A```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\Z", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("AI output is not a JSON object")
    return data


def save_failure(failure_dir: Path, row: sqlite3.Row, response: str, error: Exception) -> Path:
    failure_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", row["id"])[:80]
    path = failure_dir / f"{safe_id}.txt"
    path.write_text(
        "\n".join(
            [
                f"title: {row['title']}",
                f"id: {row['id']}",
                f"error: {error}",
                "",
                "raw_response:",
                response,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def normalize_brief(data: dict[str, object]) -> dict[str, object]:
    category = str(data.get("category") or "其他").strip()
    if category not in CATEGORIES:
        category = "其他"

    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [part.strip() for part in re.split(r"[，,、]", keywords) if part.strip()]
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(item).strip() for item in keywords if str(item).strip()][:5]

    return {
        "category": category,
        "audience": str(data.get("audience") or "未标注").strip(),
        "keywords": keywords,
        "summary": str(data.get("summary") or "").strip(),
    }


def save_brief(conn: sqlite3.Connection, row: sqlite3.Row, model: str, brief: dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO ai_item_briefs (
            item_id, content_hash, model, processed_at, category,
            audience, importance, keywords_json, summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            content_hash = excluded.content_hash,
            model = excluded.model,
            processed_at = excluded.processed_at,
            category = excluded.category,
            audience = excluded.audience,
            importance = excluded.importance,
            keywords_json = excluded.keywords_json,
            summary = excluded.summary
        """,
        (
            row["id"],
            row["content_hash"],
            model,
            dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            brief["category"],
            brief["audience"],
            "",
            json.dumps(brief["keywords"], ensure_ascii=False),
            brief["summary"],
        ),
    )
    conn.commit()


def process_items(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    base_url: str,
    api_key: str,
    model: str,
    max_chars: int,
    timeout: int,
    force: bool,
    failure_dir: Path,
    stop_on_error: bool,
) -> tuple[int, int]:
    processed = 0
    skipped = 0
    failed = 0
    for index, row in enumerate(rows, start=1):
        if not force and cached_brief(conn, row, model) is not None:
            skipped += 1
            print(f"[{index}/{len(rows)}] Skip duplicate AI item: {row['title']}")
            continue

        print(f"[{index}/{len(rows)}] Process AI item: {row['title']}")
        prompt = build_item_prompt(row, max_chars)
        response = ""
        try:
            response = call_openai_compatible_api(base_url, api_key, model, prompt, timeout)
            brief = normalize_brief(parse_ai_json(response))
            save_brief(conn, row, model, brief)
            processed += 1
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, ValueError) as exc:
            failed += 1
            failure_path = save_failure(failure_dir, row, response, exc)
            print(f"[{index}/{len(rows)}] AI item failed, saved response: {failure_path}", file=sys.stderr)
            if stop_on_error:
                raise
    return processed, skipped, failed


def rows_with_briefs(conn: sqlite3.Connection, since: dt.datetime, until: dt.datetime, model: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT f.id, f.title, f.link, f.published_at, f.updated_at,
                   f.summary AS raw_summary, f.content AS raw_content,
                   b.category, b.audience, b.keywords_json, b.summary AS ai_summary
            FROM feed_items f
            LEFT JOIN ai_item_briefs b
              ON b.item_id = f.id
             AND b.model = ?
             AND b.content_hash = f.content_hash
            WHERE COALESCE(NULLIF(f.published_at, ''), f.updated_at) >= ?
              AND COALESCE(NULLIF(f.published_at, ''), f.updated_at) <= ?
            ORDER BY f.published_at ASC, f.first_seen_at ASC
            """,
            (model, since.isoformat(), until.isoformat()),
        )
    )


def render_markdown(rows: list[sqlite3.Row], label: str) -> str:
    generated_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "---",
        f"title: 清华信息门户摘要 {label}",
        f"date_range: \"{label}\"",
        f"generated_at: {generated_at}",
        f"items_count: {len(rows)}",
        "---",
        "",
    ]

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["category"] or "未分析", []).append(row)

    for category in [*CATEGORIES, "未分析"]:
        category_rows = grouped.get(category, [])
        if not category_rows:
            continue
        lines.extend([f"## {category}", "---"])
        for row in category_rows:
            keywords = "，".join(json.loads(row["keywords_json"] or "[]")) if row["keywords_json"] else "未分析"
            summary = row["ai_summary"] or plain_text(row["raw_content"] or row["raw_summary"])[:1200]
            audience = row["audience"] or "未分析"
            lines.extend(
                [
                    f"### [{row['title']}]({row['link']})",
                    f"*   **发布时间**: {local_time(row['published_at'] or row['updated_at'])}",
                    f"*   **适用对象**: {audience}",
                    f"*   **关键词**: {keywords}",
                    f"*   **摘要**: {summary}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def render_json(rows: list[sqlite3.Row], label: str) -> str:
    generated_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    items = []
    for index, row in enumerate(rows, start=1):
        keywords = json.loads(row["keywords_json"] or "[]") if row["keywords_json"] else []
        summary = row["ai_summary"] or plain_text(row["raw_content"] or row["raw_summary"])[:1200]
        items.append(
            {
                "id": f"{label}-{index}",
                "title": row["title"],
                "source_url": row["link"],
                "published_at": local_time(row["published_at"] or row["updated_at"]),
                "category": row["category"] or "未分析",
                "audience": row["audience"] or "未分析",
                "keywords": keywords,
                "summary": summary,
            }
        )
    return json.dumps(
        {
            "date_range": label,
            "generated_at": generated_at,
            "items_count": len(items),
            "items": items,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        old = path.read_text(encoding="utf-8")
        comparable_old = re.sub(r"generated_at: .+", "generated_at: <ignored>", old)
        comparable_new = re.sub(r"generated_at: .+", "generated_at: <ignored>", content)
        comparable_old = re.sub(r'"generated_at": ".+?"', '"generated_at": "<ignored>"', comparable_old)
        comparable_new = re.sub(r'"generated_at": ".+?"', '"generated_at": "<ignored>"', comparable_new)
        if comparable_old == comparable_new:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(description="Incrementally summarize saved RSS items.")
    parser.add_argument("date_range", help="Date or date range, e.g. 20260713 or 20260712-20260713.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path, help="Write to a specific Markdown file.")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--force", action="store_true", help="Reprocess items even if cached AI output exists.")
    parser.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)
    parser.add_argument("--stop-on-error", action="store_true", help="Stop when one AI item fails.")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        print("Missing OPENAI_API_KEY or OPENAI_MODEL in .env.", file=sys.stderr)
        return 2

    conn: sqlite3.Connection | None = None
    try:
        since, until, label = parse_date_range(args.date_range)
        conn = open_db(args.db)
        rows = fetch_items(conn, since, until)
    except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
        print(f"Cannot process items: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print(f"No items found for {label}.", file=sys.stderr)
        if conn is not None:
            conn.close()
        return 1

    try:
        processed, skipped, failed = process_items(
            conn,
            rows,
            base_url,
            api_key,
            model,
            args.max_chars,
            args.timeout,
            args.force,
            args.failure_dir,
            args.stop_on_error,
        )
        brief_rows = rows_with_briefs(conn, since, until, model)
        output_path = args.output or args.output_dir / f"{label}.md"
        changed = write_if_changed(output_path, render_markdown(brief_rows, label))
        json_path = output_path.with_suffix(".json")
        json_changed = write_if_changed(json_path, render_json(brief_rows, label))
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, ValueError, sqlite3.Error) as exc:
        print(f"AI processing failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    subprocess.run([sys.executable, "scripts/build_search_index.py"], check=False)

    print(f"Date range: {label}")
    print(f"Items: {len(rows)}")
    print(f"AI processed: {processed}")
    print(f"AI skipped duplicates: {skipped}")
    print(f"AI failed items: {failed}")
    print(f"Markdown: {output_path} ({'updated' if changed else 'unchanged'})")
    print(f"JSON: {json_path} ({'updated' if json_changed else 'unchanged'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
