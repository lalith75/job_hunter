"""
JobSpy Collector — searches job boards via python-jobspy and feeds results
into the same pending-review.json pipeline used by score_jobs.py.

Usage:
    python jobspy_collector.py                        # all target roles, last 48h
    python jobspy_collector.py --hours 24             # last 24 hours only
    python jobspy_collector.py --role "data analyst"  # single role
    python jobspy_collector.py --dry-run              # preview without writing
    python jobspy_collector.py --results 15           # results per role (default 30)
    python jobspy_collector.py --no-google            # skip Google Jobs scraping
"""

import argparse
import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from link_utils import job_hash, has_dealbreaker

try:
    from jobspy import scrape_jobs
    HAS_JOBSPY = True
except ImportError:
    HAS_JOBSPY = False

from scrapling_fetcher import (
    HAS_SCRAPLING,
    create_stealthy_session, fetch_google_jobs_html, fetch_indeed_jd,
)

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
SEEN_JOBS_PATH = SCRIPT_DIR / "seen-jobs.json"
PENDING_REVIEW_PATH = SCRIPT_DIR / "pending-review.json"

INTER_SITE_DELAY = 3   # seconds between site calls within a role
INTER_ROLE_DELAY = 5   # seconds between role queries
RETRY_DELAY = 5        # seconds before retrying a failed site


def load_seen_jobs():
    if SEEN_JOBS_PATH.exists():
        with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen_jobs(seen):
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)


def load_pending_review():
    if PENDING_REVIEW_PATH.exists():
        with open(PENDING_REVIEW_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_pending_review(jobs):
    with open(PENDING_REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)



def format_salary(row):
    """Build a salary string from JobSpy DataFrame columns."""
    min_amt = row.get("min_amount")
    max_amt = row.get("max_amount")
    currency = row.get("currency", "USD")
    interval = row.get("interval", "")

    # Handle NaN / None
    if min_amt is not None and (isinstance(min_amt, float) and math.isnan(min_amt)):
        min_amt = None
    if max_amt is not None and (isinstance(max_amt, float) and math.isnan(max_amt)):
        max_amt = None

    if min_amt is None and max_amt is None:
        return ""

    parts = []
    if currency:
        parts.append(str(currency))
    if min_amt is not None and max_amt is not None:
        parts.append(f"{int(min_amt):,}--{int(max_amt):,}")
    elif min_amt is not None:
        parts.append(f"{int(min_amt):,}+")
    elif max_amt is not None:
        parts.append(f"up to {int(max_amt):,}")
    if interval:
        parts.append(f"/{interval}")

    return " ".join(parts)



def safe_str(val):
    """Convert pandas value to string, handling NaN/None."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val)


def safe_bool(val):
    """Convert pandas value to bool, handling NaN/None."""
    if val is None:
        return False
    if isinstance(val, float) and math.isnan(val):
        return False
    return bool(val)


def scrape_site_for_role(search_term, site, jobspy_config):
    """Scrape a single site for a single role. Returns a DataFrame or None."""
    results_wanted = jobspy_config.get("results_per_role", 30)
    hours_old = jobspy_config.get("hours_old", 48)
    job_type = jobspy_config.get("job_type", "fulltime")
    country = jobspy_config.get("country", "usa")
    linkedin_fetch_desc = jobspy_config.get("linkedin_fetch_description", False)

    try:
        df = scrape_jobs(
            site_name=[site],
            search_term=search_term,
            results_wanted=results_wanted,
            hours_old=hours_old,
            job_type=job_type,
            country_indeed=country,
            linkedin_fetch_description=linkedin_fetch_desc if site == "linkedin" else False,
        )
        return df
    except Exception as e:
        print(f"    {site}: ERROR - {e}")
        return None


def scrape_role_all_sites(search_term, jobspy_config):
    """Scrape all configured sites for a role, one site at a time with delays.
    Returns a combined DataFrame and a dict of per-site counts."""
    sites = jobspy_config.get("sites", ["indeed", "linkedin"])
    all_dfs = []
    site_counts = {}

    for i, site in enumerate(sites):
        df = scrape_site_for_role(search_term, site, jobspy_config)
        count = len(df) if df is not None and not df.empty else 0

        # Retry once if site returned 0 results
        if count == 0:
            print(f"    {site}: 0 results, retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
            df = scrape_site_for_role(search_term, site, jobspy_config)
            count = len(df) if df is not None and not df.empty else 0

        if df is not None and not df.empty:
            all_dfs.append(df)
        site_counts[site] = count
        print(f"    {site}: {count} results")

        # Delay between sites (not after the last one)
        if i < len(sites) - 1:
            time.sleep(INTER_SITE_DELAY)

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        return combined, site_counts
    return None, site_counts


def df_to_pending_jobs(df, search_term, dealbreakers):
    """Convert a JobSpy DataFrame to pending-review.json format."""
    jobs = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for _, row in df.iterrows():
        url = safe_str(row.get("job_url"))
        if not url:
            continue

        description = safe_str(row.get("description"))

        # Skip dealbreaker jobs early
        title = safe_str(row.get("title"))
        if has_dealbreaker(description, dealbreakers) or has_dealbreaker(title, dealbreakers):
            continue

        site = safe_str(row.get("site"))
        date_posted = safe_str(row.get("date_posted"))

        job = {
            "title_hint": title,
            "url": url,
            "source": site.capitalize() if site else "JobSpy",
            "jd_text": description[:5000] if description else "",
            "jd_title": title,
            "jd_company": safe_str(row.get("company")),
            "jd_location": safe_str(row.get("location")),
            "salary": format_salary(row),
            "is_remote": safe_bool(row.get("is_remote")),
            "email_subject": f"JobSpy: {search_term}",
            "email_date": date_posted,
            "email_label": "JobSpy",
            "collected_at": now_iso,
            "dedup_hash": job_hash(url),
            "fetch_error": "",
        }
        jobs.append(job)

    return jobs


# ---------------------------------------------------------------------------
# Google Jobs scraper — uses Scrapling StealthySession to render JS
# python-jobspy's Google scraper is broken (Google requires JS execution).
# This scraper uses camoufox (via Scrapling) with anti-detection to get job data.
# ---------------------------------------------------------------------------

def _parse_google_job_cards(html):
    """Extract job listings from rendered Google Jobs HTML.

    Google Jobs (udm=8) renders job cards into the DOM after JS execution.
    This parser extracts structured data from the rendered HTML using
    python-jobspy's internal data format (key 520084652) when available,
    falling back to DOM-based extraction.
    """
    from jobspy.google.util import find_job_info_initial_page

    jobs_raw = find_job_info_initial_page(html)
    if jobs_raw:
        return jobs_raw, "json"

    # Fallback: parse job cards from DOM structure
    # Google Jobs cards have a predictable structure with title, company, location
    jobs = []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Google Jobs cards are in li elements with data-ved attributes
        # Each card contains: title (h3/div), company, location, date, link
        for card in soup.select('li[data-ved]'):
            text = card.get_text(separator="\n", strip=True)
            if len(text) < 20:
                continue

            # Find the job URL (first external link in the card)
            link = None
            for a_tag in card.find_all("a", href=True):
                href = a_tag["href"]
                if href.startswith("http") and "google.com" not in href:
                    link = href
                    break
                elif href.startswith("/url?q="):
                    match = re.search(r'q=(https?://[^&]+)', href)
                    if match:
                        link = match.group(1)
                        break

            if not link:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) < 2:
                continue

            jobs.append({
                "title": lines[0] if lines else "",
                "company": lines[1] if len(lines) > 1 else "",
                "location": lines[2] if len(lines) > 2 else "",
                "url": link,
                "description": text,
            })
    except Exception as e:
        print(f"    DOM parse error: {e}")

    return jobs, "dom"


def _google_jobs_to_pending(jobs, parse_mode, search_term, dealbreakers):
    """Convert parsed Google Jobs data to pending-review.json format."""
    pending = []
    now_iso = datetime.now(timezone.utc).isoformat()

    if parse_mode == "json":
        # python-jobspy JSON format (520084652 data)
        for job_raw in jobs:
            try:
                title = job_raw[0] if len(job_raw) > 0 else ""
                company = job_raw[1] if len(job_raw) > 1 else ""
                location = job_raw[2] if len(job_raw) > 2 else ""
                url = job_raw[3][0][0] if job_raw[3] and job_raw[3][0] else ""
                description = job_raw[19] if len(job_raw) > 19 and job_raw[19] else ""

                if not url or not title:
                    continue
                if has_dealbreaker(description, dealbreakers) or has_dealbreaker(title, dealbreakers):
                    continue

                # Parse days ago
                days_ago_str = job_raw[12] if len(job_raw) > 12 else ""
                date_posted = ""
                if isinstance(days_ago_str, str):
                    match = re.search(r"\d+", days_ago_str)
                    if match:
                        days_ago = int(match.group())
                        date_posted = str((datetime.now() - timedelta(days=days_ago)).date())

                pending.append({
                    "title_hint": str(title),
                    "url": str(url),
                    "source": "Google",
                    "jd_text": str(description)[:5000],
                    "jd_title": str(title),
                    "jd_company": str(company),
                    "jd_location": str(location),
                    "salary": "",
                    "is_remote": "remote" in str(description).lower(),
                    "email_subject": f"Google Jobs: {search_term}",
                    "email_date": date_posted,
                    "email_label": "Google Jobs",
                    "collected_at": now_iso,
                    "dedup_hash": job_hash(str(url)),
                    "fetch_error": "",
                })
            except (IndexError, TypeError):
                continue
    else:
        # DOM-parsed format
        for job in jobs:
            url = job.get("url", "")
            title = job.get("title", "")
            desc = job.get("description", "")
            if not url or not title:
                continue
            if has_dealbreaker(desc, dealbreakers) or has_dealbreaker(title, dealbreakers):
                continue

            pending.append({
                "title_hint": title,
                "url": url,
                "source": "Google",
                "jd_text": desc[:5000],
                "jd_title": title,
                "jd_company": job.get("company", ""),
                "jd_location": job.get("location", ""),
                "salary": "",
                "is_remote": "remote" in desc.lower(),
                "email_subject": f"Google Jobs: {search_term}",
                "email_date": "",
                "email_label": "Google Jobs",
                "collected_at": now_iso,
                "dedup_hash": job_hash(url),
                "fetch_error": "",
            })

    return pending


def scrape_google_jobs(target_roles, dealbreakers, hours_old=48, results_per_role=10):
    """Scrape Google Jobs using Scrapling StealthySession.

    Google Jobs (udm=8) requires JavaScript execution and blocks automated
    browsers. Scrapling's StealthySession uses camoufox to bypass detection.

    Returns a list of jobs in pending-review.json format.
    """
    if not HAS_SCRAPLING:
        print("  Google Jobs: scrapling not installed (pip install scrapling[fetchers])")
        return []

    all_jobs = []
    google_blocked = False

    print(f"\n{'='*50}")
    print(f"Google Jobs (Scrapling StealthySession)")
    print(f"{'='*50}")

    try:
        with create_stealthy_session() as session:
            # Warm up: visit google.com first
            session.fetch("https://www.google.com/", timeout=10000, wait=2000)

            for i, role in enumerate(target_roles):
                if google_blocked:
                    break

                print(f"  [{i+1}/{len(target_roles)}] Google: {role}...")

                query = f"{role} jobs"
                # Add time filter to query
                if hours_old <= 24:
                    query += " since yesterday"
                elif hours_old <= 72:
                    query += " in the last 3 days"
                elif hours_old <= 168:
                    query += " in the last week"

                try:
                    html, err = fetch_google_jobs_html(query, session)

                    if err == "blocked":
                        print("    BLOCKED: Google rate limit detected, skipping remaining roles")
                        google_blocked = True
                        continue
                    elif err:
                        print(f"    ERROR: {err}")
                        if i > 0:
                            google_blocked = True
                        continue

                    # Parse job data from rendered HTML
                    jobs_raw, parse_mode = _parse_google_job_cards(html)
                    if not jobs_raw:
                        print(f"    No job cards found (parse_mode={parse_mode})")
                        continue

                    jobs = _google_jobs_to_pending(jobs_raw, parse_mode, role, dealbreakers)
                    print(f"    Found {len(jobs)} jobs (parse_mode={parse_mode})")
                    all_jobs.extend(jobs)

                    # Rate-limit: wait between searches to avoid triggering Google
                    if i < len(target_roles) - 1:
                        delay = 3 + (i % 3)  # 3-5 seconds between searches
                        time.sleep(delay)

                except Exception as e:
                    print(f"    ERROR: {e}")
                    if i > 0:
                        google_blocked = True

    except Exception as e:
        print(f"  Google Jobs browser error: {e}")
        print("  Continuing without Google Jobs results")

    if google_blocked:
        print("  Note: Google rate-limited this IP. Results are partial.")
        print("  This usually clears within 1-2 hours.")

    return all_jobs


# ---------------------------------------------------------------------------
# Indeed JD backfill — fetches full descriptions for Indeed jobs that came
# back with empty JD text from the search API.  Uses Scrapling StealthySession
# (same as the Google Jobs scraper) because Indeed blocks plain requests.
# ---------------------------------------------------------------------------

INDEED_BACKFILL_DELAY = 2  # seconds between page fetches to avoid rate-limiting

def backfill_indeed_descriptions(jobs, dealbreakers):
    """For Indeed jobs with empty jd_text, fetch the full JD from the job page.

    Modifies job dicts in-place.  Returns (filled_count, blocked).
    """
    if not HAS_SCRAPLING:
        return 0, False

    # Find Indeed jobs missing descriptions
    empty_indeed = [
        j for j in jobs
        if "indeed.com" in (j.get("url") or "")
        and not (j.get("jd_text") or "").strip()
    ]
    if not empty_indeed:
        return 0, False

    print(f"\n{'='*50}")
    print(f"Indeed JD Backfill (Scrapling StealthySession)")
    print(f"{'='*50}")
    print(f"  {len(empty_indeed)} Indeed jobs missing descriptions")

    filled = 0
    blocked = False

    try:
        with create_stealthy_session() as session:
            # Warm up
            session.fetch("https://www.indeed.com/", timeout=10000, wait=2000)

            for i, job in enumerate(empty_indeed):
                if blocked:
                    break

                url = job["url"]
                print(f"  [{i+1}/{len(empty_indeed)}] Fetching: {job.get('title_hint', '')[:50]}...", end=" ")

                jd_text, err = fetch_indeed_jd(url, session)

                if err == "blocked":
                    print("BLOCKED")
                    blocked = True
                    continue
                elif err:
                    print(f"error: {err}")
                    job["fetch_error"] = err
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
                if i < len(empty_indeed) - 1:
                    time.sleep(INDEED_BACKFILL_DELAY)

    except Exception as e:
        print(f"  Browser error: {e}")

    if blocked:
        print("  Note: Indeed rate-limited this IP. Some JDs were not fetched.")

    print(f"  Backfilled: {filled}/{len(empty_indeed)} jobs")
    return filled, blocked


def run_collector(config, dry_run=False, role_filter=None, hours_override=None,
                  results_override=None, skip_google=False):
    """Main collection pipeline."""
    target_roles = config["scoring"]["target_roles"]
    dealbreakers = config["scoring"]["dealbreakers"]
    jobspy_config = config.get("jobspy", {})

    if hours_override is not None:
        jobspy_config["hours_old"] = hours_override
    if results_override is not None:
        jobspy_config["results_per_role"] = results_override

    if role_filter:
        target_roles = [role_filter]

    seen = load_seen_jobs()
    existing_pending = load_pending_review()
    all_new_jobs = []

    total_found = 0
    total_new = 0
    total_dupes = 0
    total_dealbreakers = 0
    site_totals = {}

    hours = jobspy_config.get("hours_old", 48)
    results_per = jobspy_config.get("results_per_role", 30)
    sites = jobspy_config.get("sites", ["indeed", "linkedin"])

    print(f"JobSpy Collector")
    print(f"{'='*50}")
    print(f"Roles:     {len(target_roles)}")
    print(f"Sites:     {', '.join(sites)}")
    if not skip_google and HAS_SCRAPLING:
        print(f"Google:    enabled (Scrapling StealthySession)")
    elif skip_google:
        print(f"Google:    skipped (--no-google)")
    else:
        print(f"Google:    unavailable (install scrapling[fetchers])")
    print(f"Hours old: {hours}")
    print(f"Per role:  {results_per}")
    if dry_run:
        print(f"Mode:      DRY RUN (no files written)")
    print()

    # --- Phase 1: JobSpy (Indeed + LinkedIn) ---
    for i, role in enumerate(target_roles, 1):
        print(f"\n[{i}/{len(target_roles)}] Searching: {role}...")

        df, site_counts = scrape_role_all_sites(role, jobspy_config)

        # Track per-site totals
        for site, count in site_counts.items():
            if site not in site_totals:
                site_totals[site] = {"found": 0, "roles_with_zero": 0}
            site_totals[site]["found"] += count
            if count == 0:
                site_totals[site]["roles_with_zero"] += 1

        if df is None or df.empty:
            print(f"  No results from any site")
            continue

        raw_count = len(df)
        jobs = df_to_pending_jobs(df, role, dealbreakers)
        dealbreaker_count = raw_count - len(jobs)
        total_dealbreakers += dealbreaker_count
        total_found += raw_count

        # Dedup against seen jobs
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
                "source": job["source"],
            }
            new_for_role += 1
            total_new += 1

        dupes_for_role = len(jobs) - new_for_role
        print(f"  Total: {raw_count}, new {new_for_role}, dupes {dupes_for_role}, dealbreakers {dealbreaker_count}")

        # Inter-role delay (not after the last role)
        if i < len(target_roles):
            time.sleep(INTER_ROLE_DELAY)

    # --- Phase 2: Google Jobs (Scrapling StealthySession) ---
    google_new = 0
    if not skip_google and HAS_SCRAPLING:
        google_jobs = scrape_google_jobs(
            target_roles, dealbreakers,
            hours_old=hours,
            results_per_role=min(results_per, 10),
        )
        total_found += len(google_jobs)

        for job in google_jobs:
            h = job["dedup_hash"]
            if h in seen:
                total_dupes += 1
                continue

            all_new_jobs.append(job)
            seen[h] = {
                "url": job["url"],
                "first_seen": job["collected_at"],
                "source": "Google",
            }
            google_new += 1
            total_new += 1

        if google_jobs:
            print(f"\n  Google Jobs: {len(google_jobs)} found, {google_new} new")

    # --- Phase 3: Indeed JD backfill ---
    backfill_count = 0
    if not dry_run and HAS_SCRAPLING:
        backfill_count, _ = backfill_indeed_descriptions(all_new_jobs, dealbreakers)

    # Save results
    if not dry_run and all_new_jobs:
        all_pending = existing_pending + all_new_jobs
        save_pending_review(all_pending)
        save_seen_jobs(seen)

    # Summary
    print(f"\n{'='*50}")
    print(f"Collection Summary")
    print(f"{'='*50}")
    print(f"Roles searched:    {len(target_roles)}")
    print(f"Jobs found:        {total_found}")
    print(f"New jobs:          {total_new}")
    if google_new:
        print(f"  (Google Jobs):   {google_new}")
    print(f"Duplicates:        {total_dupes}")
    print(f"Dealbreakers:      {total_dealbreakers}")
    if backfill_count:
        print(f"Indeed backfilled: {backfill_count}")

    # Per-site breakdown
    if site_totals:
        print(f"\nPer-site breakdown:")
        for site, stats in sorted(site_totals.items()):
            status = ""
            if stats["roles_with_zero"] == len(target_roles):
                status = " *** BLOCKED - returned 0 for ALL roles ***"
            elif stats["roles_with_zero"] > len(target_roles) // 2:
                status = " (unreliable - failed for most roles)"
            print(f"  {site:12s}: {stats['found']:4d} found{status}")

    if dry_run:
        print(f"\n[DRY RUN] No files written.")
        if all_new_jobs:
            print(f"\nPreview -- would add {len(all_new_jobs)} jobs:")
            for j in all_new_jobs[:10]:
                print(f"  {j['jd_company']:30s} | {j['title_hint'][:50]}")
            if len(all_new_jobs) > 10:
                print(f"  ... and {len(all_new_jobs) - 10} more")
    else:
        if all_new_jobs:
            print(f"\nResults saved to: pending-review.json")
            print(f"Total pending for review: {len(existing_pending) + len(all_new_jobs)}")
            print(f'\nNext step: Open Claude Code and say "score my jobs"')
        else:
            print(f"\nNo new jobs to add.")

    return all_new_jobs


def main():
    parser = argparse.ArgumentParser(description="Collect jobs from job boards via JobSpy")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--role", type=str, help="Search a single role instead of all target roles")
    parser.add_argument("--hours", type=int, help="Override hours_old filter (default: from config)")
    parser.add_argument("--results", type=int, help="Override results per role (default: from config)")
    parser.add_argument("--no-google", action="store_true", help="Skip Google Jobs scraping")
    args = parser.parse_args()

    if not HAS_JOBSPY:
        print("ERROR: python-jobspy not installed.")
        print("  pip install python-jobspy")
        return 1

    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found at {CONFIG_PATH}")
        return 1

    config = load_config()
    run_collector(
        config,
        dry_run=args.dry_run,
        role_filter=args.role,
        hours_override=args.hours,
        results_override=args.results,
        skip_google=args.no_google,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
