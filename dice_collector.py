"""
Dice Job Collector -- searches Dice.com via their official MCP server and feeds
results into the same pending-review.json pipeline used by jobspy_collector.py.

Usage:
    python dice_collector.py                    # all target roles
    python dice_collector.py --role "data analyst"  # single role
    python dice_collector.py --dry-run          # preview without writing
"""

import argparse
import json
import re
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

from link_utils import job_hash, has_dealbreaker
from scrapling_fetcher import fetch_dice_jd, HAS_SCRAPLING

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
SEEN_JOBS_PATH = SCRIPT_DIR / "seen-jobs.json"
PENDING_REVIEW_PATH = SCRIPT_DIR / "pending-review.json"

DICE_MCP_URL = "https://mcp.dice.com/mcp"
INTER_ROLE_DELAY = 3  # seconds between role queries


def load_json(path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)



def _parse_sse_json(response_text):
    """Parse a JSON-RPC result from an SSE response body.

    Dice MCP returns Server-Sent Events format:
        event: message
        data: {"jsonrpc":"2.0", ...}

    Returns the parsed JSON dict or None.
    """
    for line in response_text.strip().split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    return None


def search_dice_mcp(role, session_id=None):
    """Call the Dice MCP server's search_jobs tool via Streamable HTTP.

    The MCP Streamable HTTP transport uses JSON-RPC 2.0 over HTTP POST,
    with responses in SSE (Server-Sent Events) format.
    Returns the tool result or None on failure.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    try:
        # Initialize the MCP session if no session_id yet
        if not session_id:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "dice-collector", "version": "1.0.0"}
                }
            }
            resp = requests.post(DICE_MCP_URL, json=init_payload, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"    Dice MCP init failed: HTTP {resp.status_code}")
                return None, session_id
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                headers["Mcp-Session-Id"] = session_id

        # JSON-RPC 2.0 request to call the search_jobs tool
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_jobs",
                "arguments": {
                    "keyword": role,
                    "employment_types": ["FULLTIME"],
                    "posted_date": "THREE",  # last 3 days
                    "jobs_per_page": 20,
                }
            }
        }

        resp = requests.post(DICE_MCP_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"    Dice API error: HTTP {resp.status_code}")
            return None, session_id

        data = _parse_sse_json(resp.text)
        if not data:
            print(f"    Dice: empty SSE response")
            return None, session_id
        if "error" in data:
            print(f"    Dice API error: {data['error']}")
            return None, session_id

        return data.get("result"), session_id

    except requests.exceptions.Timeout:
        print(f"    Dice request timed out")
        return None, session_id
    except requests.exceptions.ConnectionError as e:
        print(f"    Dice connection error: {e}")
        return None, session_id
    except Exception as e:
        print(f"    Dice request error: {e}")
        return None, session_id


def parse_dice_results(result, role, dealbreakers):
    """Convert Dice MCP search_jobs result to pending-review.json format.

    Dice MCP returns content blocks where the text is a JSON string with structure:
        {"data": [list of JobDisplayFields], "meta": {...}, "_links": {...}}
    Each job object has: title, companyName, detailsPageUrl, salary,
    jobLocation (object with displayName), isRemote, summary, postedDate, etc.
    """
    jobs = []
    now_iso = datetime.now(timezone.utc).isoformat()

    if not result or "content" not in result:
        return jobs

    for content_block in result.get("content", []):
        if content_block.get("type") != "text":
            continue
        text = content_block.get("text", "")

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue

        # Extract job list from Dice's response structure
        if isinstance(parsed, dict):
            items = parsed.get("data") or parsed.get("jobs") or parsed.get("results") or []
        elif isinstance(parsed, list):
            items = parsed
        else:
            continue

        for item in items:
            url = item.get("detailsPageUrl") or item.get("url") or ""
            title = item.get("title") or ""
            if not url or not title:
                continue

            company = item.get("companyName") or ""
            # Location is nested: jobLocation.displayName
            job_location = item.get("jobLocation") or {}
            if isinstance(job_location, dict):
                location = job_location.get("displayName") or ""
            else:
                location = str(job_location) if job_location else ""
            description = item.get("summary") or item.get("description") or ""
            salary = item.get("salary") or ""
            date_posted = item.get("postedDate") or ""
            is_remote = item.get("isRemote", False)

            if has_dealbreaker(title, dealbreakers) or has_dealbreaker(description, dealbreakers):
                continue

            jobs.append({
                "title_hint": title,
                "url": url,
                "source": "Dice",
                "jd_text": description[:5000],
                "jd_title": title,
                "jd_company": company,
                "jd_location": location,
                "salary": salary if isinstance(salary, str) else "",
                "is_remote": is_remote or ("remote" in location.lower() if location else False),
                "email_subject": f"Dice: {role}",
                "email_date": date_posted,
                "email_label": "Dice",
                "collected_at": now_iso,
                "dedup_hash": job_hash(url),
                "fetch_error": "",
            })

    return jobs


DICE_BACKFILL_DELAY = 1.5  # seconds between JD fetches


def backfill_dice_descriptions(jobs, dealbreakers):
    """For Dice jobs with short/summary JDs, fetch the full JD from the job page.

    Dice MCP returns summaries (~200 chars). This fetches the real JD using
    lightweight HTTP (no browser needed — Dice pages are server-rendered).

    Modifies job dicts in-place.  Returns (filled_count, error_count).
    """
    if not HAS_SCRAPLING:
        return 0, 0

    # Find Dice jobs with short descriptions (MCP summaries are ~200 chars)
    short_jd = [
        j for j in jobs
        if "dice.com" in (j.get("url") or "")
        and len((j.get("jd_text") or "").strip()) < 300
    ]
    if not short_jd:
        return 0, 0

    print(f"\n{'='*50}")
    print(f"Dice JD Backfill (Scrapling Fetcher)")
    print(f"{'='*50}")
    print(f"  {len(short_jd)} Dice jobs with short/missing descriptions")

    filled = 0
    errors = 0

    for i, job in enumerate(short_jd):
        url = job["url"]
        print(f"  [{i+1}/{len(short_jd)}] Fetching: {job.get('title_hint', '')[:50]}...", end=" ")

        jd_text, err = fetch_dice_jd(url)

        if err:
            print(f"error: {err}")
            job["fetch_error"] = err
            errors += 1
            continue
        elif not jd_text:
            print("empty")
            continue

        # Check for dealbreakers in the newly fetched JD
        combined = f"{job.get('jd_title', '')} {jd_text} {job.get('jd_company', '')}"
        if has_dealbreaker(combined, dealbreakers):
            db_match = next(
                (db for db in dealbreakers
                 if ((' ' in db or '/' in db) and db in combined.lower())
                 or re.search(r'\b' + re.escape(db) + r'\b', combined.lower())),
                "unknown"
            )
            print(f"DEALBREAKER ({db_match})")
            job["jd_text"] = jd_text[:5000]
            job["fetch_error"] = f"dealbreaker:{db_match}"
            continue

        job["jd_text"] = jd_text[:5000]
        filled += 1
        print(f"OK ({len(jd_text)} chars)")

        # Rate limit between fetches
        if i < len(short_jd) - 1:
            time.sleep(DICE_BACKFILL_DELAY)

    print(f"  Backfilled: {filled}/{len(short_jd)} jobs")
    return filled, errors


def run_dice_collector(config, dry_run=False, role_filter=None):
    """Main Dice collection pipeline."""
    target_roles = config["scoring"]["target_roles"]
    dealbreakers = config["scoring"]["dealbreakers"]

    if role_filter:
        target_roles = [role_filter]

    seen = load_json(SEEN_JOBS_PATH, {})
    existing_pending = load_json(PENDING_REVIEW_PATH, [])
    all_new_jobs = []
    total_found = 0
    total_new = 0
    total_dupes = 0

    print(f"Dice Job Collector")
    print(f"{'='*50}")
    print(f"Roles:     {len(target_roles)}")
    print(f"Source:    Dice MCP ({DICE_MCP_URL})")
    if dry_run:
        print(f"Mode:      DRY RUN")
    print()

    session_id = None

    for i, role in enumerate(target_roles, 1):
        print(f"[{i}/{len(target_roles)}] Searching Dice: {role}...")

        result, session_id = search_dice_mcp(role, session_id)
        if result is None:
            print(f"  No results")
            continue

        jobs = parse_dice_results(result, role, dealbreakers)
        total_found += len(jobs)

        new_for_role = 0
        for job in jobs:
            h = job["dedup_hash"]
            if h in seen:
                total_dupes += 1
                continue

            all_new_jobs.append(job)
            seen[h] = {
                "url": job["url"],
                "first_seen": job["collected_at"],
                "source": "Dice",
            }
            new_for_role += 1
            total_new += 1

        print(f"  Found {len(jobs)}, new {new_for_role}")

        if i < len(target_roles):
            time.sleep(INTER_ROLE_DELAY)

    # Backfill short JDs with full descriptions from Dice pages
    backfill_count = 0
    if not dry_run and all_new_jobs:
        backfill_count, _ = backfill_dice_descriptions(all_new_jobs, dealbreakers)

    # Save
    if not dry_run and all_new_jobs:
        all_pending = existing_pending + all_new_jobs
        save_json(PENDING_REVIEW_PATH, all_pending)
        save_json(SEEN_JOBS_PATH, seen)

    # Summary
    print(f"\n{'='*50}")
    print(f"Dice Collection Summary")
    print(f"{'='*50}")
    print(f"Roles searched:  {len(target_roles)}")
    print(f"Jobs found:      {total_found}")
    print(f"New jobs:        {total_new}")
    print(f"Duplicates:      {total_dupes}")
    if backfill_count:
        print(f"JDs backfilled:  {backfill_count}")

    if dry_run:
        print(f"\n[DRY RUN] No files written.")
        if all_new_jobs:
            print(f"\nPreview -- would add {len(all_new_jobs)} jobs:")
            for j in all_new_jobs[:10]:
                print(f"  {j['jd_company']:30s} | {j['title_hint'][:50]}")
    else:
        if all_new_jobs:
            print(f"\nSaved to: pending-review.json")
            print(f"Total pending: {len(existing_pending) + len(all_new_jobs)}")
        else:
            print(f"\nNo new jobs to add.")

    return all_new_jobs


def main():
    parser = argparse.ArgumentParser(description="Collect jobs from Dice via MCP")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--role", type=str, help="Search a single role")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found at {CONFIG_PATH}")
        return 1

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    run_dice_collector(config, dry_run=args.dry_run, role_filter=args.role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
