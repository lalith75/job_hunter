"""
Scrapling Fetcher — shared module for all Scrapling-based page fetching.

Provides browser-based fetching (StealthySession) for Google Jobs and Indeed,
and lightweight HTTP fetching (Fetcher) for Dice JDs.

Usage:
    from scrapling_fetcher import (
        HAS_SCRAPLING, check_scrapling_available,
        create_stealthy_session, fetch_google_jobs_html,
        fetch_indeed_jd, fetch_dice_jd,
    )
"""

from urllib.parse import quote_plus

try:
    from scrapling.fetchers import Fetcher, StealthySession
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False


def check_scrapling_available():
    """Return True if scrapling is installed and importable."""
    return HAS_SCRAPLING


def create_stealthy_session(headless=True):
    """Factory for a configured StealthySession (reusable browser).

    Returns a context manager — use with `with create_stealthy_session() as session:`.
    The session reuses a single browser instance across multiple .fetch() calls,
    avoiding the 1.4GB-per-request memory cost of StealthyFetcher.
    """
    if not HAS_SCRAPLING:
        raise RuntimeError("scrapling is not installed — pip install scrapling[fetchers]")
    return StealthySession(headless=headless)


def fetch_google_jobs_html(query, session):
    """Fetch rendered Google Jobs HTML for a search query.

    Args:
        query: Search string, e.g. "data analyst jobs"
        session: An active StealthySession instance

    Returns:
        (html_string, None) on success
        (None, error_string) on failure
    """
    url = f"https://www.google.com/search?q={quote_plus(query)}&udm=8"
    try:
        page = session.fetch(url, network_idle=True, timeout=15000, wait=3000)

        # page.body returns bytes in Scrapling v0.4+
        body = page.body
        if isinstance(body, bytes):
            html = body.decode("utf-8", errors="replace")
        else:
            html = str(body)

        # Check for rate-limit / CAPTCHA
        if "unusual traffic" in html.lower():
            return None, "blocked"

        return html, None
    except Exception as e:
        return None, str(e)


def fetch_indeed_jd(url, session):
    """Fetch full job description text from an Indeed viewjob page.

    Args:
        url: Indeed job URL
        session: An active StealthySession instance

    Returns:
        (jd_text, None) on success
        (None, error_string) on failure
    """
    try:
        page = session.fetch(url, network_idle=True, timeout=15000, wait=2000)

        body = page.body
        if isinstance(body, bytes):
            html = body.decode("utf-8", errors="replace")
        else:
            html = str(body)

        # Check for rate-limit
        if "unusual traffic" in html.lower() or len(html) < 200:
            return None, "blocked"

        # Try CSS selectors in order (same priority as original seleniumbase version)
        for selector in [
            "#jobDescriptionText",
            ".jobsearch-jobDescriptionText",
            ".jobsearch-JobComponent-description",
            "[id*=jobDescription]",
        ]:
            elements = page.css(selector)
            if elements:
                text = elements[0].get_all_text(separator=" ", strip=True)
                if text:
                    return text, None

        return None, "no-selector-match"
    except Exception as e:
        return None, str(e)


def fetch_dice_jd(url):
    """Fetch full job description text from a Dice job page.

    Uses lightweight HTTP (Fetcher) — no browser needed since Dice pages
    are server-rendered. Much faster and lower memory than StealthySession.

    Args:
        url: Dice job detail URL

    Returns:
        (jd_text, None) on success
        (None, error_string) on failure
    """
    if not HAS_SCRAPLING:
        return None, "scrapling not installed"

    try:
        page = Fetcher.get(url, impersonate="chrome", timeout=15)

        # Try Dice CSS selectors
        for selector in [
            "div.job-description",
            "[data-testid='jobDescriptionHtml']",
            "section.job-description",
        ]:
            elements = page.css(selector)
            if elements:
                text = elements[0].get_all_text(separator=" ", strip=True)
                if text:
                    return text, None

        return None, "no-selector-match"
    except Exception as e:
        return None, str(e)
