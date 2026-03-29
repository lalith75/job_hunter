"""
Link utilities for the job automation pipeline.
Shared helpers: hashing, dealbreaker checks, careers site URL rewriting,
aggregator detection, and link validation.
"""

import hashlib
import re
import requests
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── Shared helpers ──────────────────────────────────────────────

def job_hash(url):
    """Generate a dedup hash from a URL."""
    normalized = url.lower().strip().rstrip("/")
    parsed = urlparse(normalized)
    path = parsed.path + ('?' + parsed.query if parsed.query else '')
    clean = f"{parsed.scheme}://{parsed.netloc}{path}"
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def has_dealbreaker(text, dealbreakers):
    """Check if text contains any dealbreaker keywords (word-boundary aware)."""
    if not text:
        return False
    lower = text.lower()
    for db in dealbreakers:
        # Multi-word phrases are specific enough for substring match
        if ' ' in db or '/' in db:
            if db in lower:
                return True
        else:
            # Single words use word boundaries to avoid false positives
            if re.search(r'\b' + re.escape(db) + r'\b', lower):
                return True
    return False

# ── Careers site search URL templates ──────────────────────────
# Key = normalized company substring, Value = search URL template
CAREERS_SITES = {
    # FAANG / Big Tech
    "amazon":     "https://www.amazon.jobs/en/search?base_query={query}",
    "apple":      "https://jobs.apple.com/en-us/search?search={query}",
    "google":     "https://www.google.com/about/careers/applications/jobs/results?q={query}",
    "meta":       "https://www.metacareers.com/jobs?q={query}",
    "microsoft":  "https://careers.microsoft.com/us/en/search-results?keywords={query}",
    # Semiconductor
    "nvidia":     "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q={query}",
    "qualcomm":   "https://careers.qualcomm.com/careers?query={query}",
    "intel":      "https://jobs.intel.com/en/search-jobs?keywords={query}",
    "amd":        "https://careers.amd.com/careers-home/jobs?keywords={query}",
    "broadcom":   "https://careers.broadcom.com/jobs?keyword={query}",
    "texas instruments": "https://careers.ti.com/search-jobs?keywords={query}",
    "ti":               "https://careers.ti.com/search-jobs?keywords={query}",
    "micron":     "https://careers.micron.com/careers?query={query}",
    "cadence":    "https://cadence.wd1.myworkdayjobs.com/External_Careers?q={query}",
    "nxp":        "https://nxp.wd3.myworkdayjobs.com/careers?q={query}",
    "marvell":    "https://marvell.wd1.myworkdayjobs.com/MarvellCareers2?q={query}",
    # Automotive / Robotics
    "tesla":      "https://www.tesla.com/careers/search?query={query}",
    "rivian":     "https://careers.rivian.com/search?q={query}",
    # Networking / Enterprise
    "cisco":      "https://jobs.cisco.com/jobs/SearchJobs?search={query}",
    "bosch":      "https://www.bosch.com/careers/search/?keywords={query}",
    "honeywell":  "https://careers.honeywell.com/us/en/search-results?keywords={query}",
    "siemens":    "https://jobs.siemens.com/careers?query={query}",
}

# ── Known aggregator domains ──────────────────────────────────
AGGREGATOR_DOMAINS = {
    "learn4good.com", "snagajob.com", "recruit.net", "jooble.org",
    "trabajo.org", "us.trabajo.org", "climatetechlist.com", "theladders.com",
    "echojobs.io", "jobs.digitalhire.com", "simplyhired.com",
    "careerbuilder.com", "monster.com", "talent.com", "jobrapido.com",
    "adzuna.com", "salary.com", "jobtome.com", "lensa.com",
    "jobs.stevenagefc.com",
}

# ── Company name aliases ──────────────────────────────────────
COMPANY_ALIASES = {
    "amazon web services": "amazon", "aws": "amazon",
    "annapurna labs": "amazon", "ring": "amazon",
    "lab126": "amazon", "amazon.com": "amazon",
    "meta platforms": "meta", "facebook": "meta",
    "alphabet": "google", "general motors": "gm",
    "texas instruments": "ti",
}

# Suffixes to strip from company names
_COMPANY_SUFFIXES = re.compile(
    r',?\s*\b(inc\.?|llc\.?|corp\.?|corporation|ltd\.?|co\.?|'
    r'technologies|technology|solutions|services|group|'
    r'systems|enterprises?|international|worldwide|global)\b\.?',
    re.IGNORECASE
)

# Parenthetical suffixes like "(US)" or "(Remote)"
_COMPANY_PARENS = re.compile(r'\s*\(.*?\)\s*')


def normalize_company(name):
    """Normalize company name: lowercase, strip suffixes, resolve aliases."""
    if not name:
        return ""
    n = name.lower().strip()
    # Replace pipe with space (common in staffing names)
    n = n.replace("|", " ").strip()
    # Check aliases BEFORE stripping suffixes (so "Amazon Web Services" matches)
    for alias, canonical in COMPANY_ALIASES.items():
        if alias in n:
            return canonical
    # Remove parentheticals
    n = _COMPANY_PARENS.sub("", n).strip()
    # Strip corporate suffixes
    n = _COMPANY_SUFFIXES.sub("", n).strip()
    return n


def is_aggregator(url):
    """Check if URL domain is a known aggregator site."""
    if not url:
        return False
    try:
        domain = urlparse(url).netloc.lower()
        # Strip www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain in AGGREGATOR_DOMAINS
    except Exception:
        return False


def is_indeed_link(url):
    """Check if URL is an Indeed link (ephemeral)."""
    if not url:
        return False
    try:
        domain = urlparse(url).netloc.lower()
        return "indeed.com" in domain
    except Exception:
        return False


def build_careers_search_url(company, title):
    """Build a careers site search URL for a company + job title.
    Returns the search URL or None if company isn't in CAREERS_SITES."""
    norm = normalize_company(company)
    if not norm:
        return None
    # Try exact match first, then substring (min 3 chars to avoid spurious matches)
    template = CAREERS_SITES.get(norm)
    if not template and len(norm) >= 3:
        for key, tmpl in CAREERS_SITES.items():
            if key in norm or norm in key:
                template = tmpl
                break
    if not template:
        return None
    # Use a simplified title as query (strip level markers)
    query = re.sub(r'\s*[-–]\s*(US|Remote|Hybrid|Jr\.?|Sr\.?|II|III|IV)$', '', title, flags=re.IGNORECASE)
    return template.format(query=quote_plus(query))


def rewrite_link(job):
    """Augment a job dict with apply_url and link_flags.
    Does NOT modify the original 'url' field."""
    url = job.get("url") or ""
    title = job.get("jd_title") or job.get("title_hint") or ""
    company = job.get("jd_company") or ""
    flags = []

    # Detect issues
    if is_indeed_link(url):
        flags.append("indeed_ephemeral")
    if is_aggregator(url):
        flags.append("aggregator")

    # Try to build a careers site search URL
    careers_url = build_careers_search_url(company, title)
    if careers_url:
        flags.append("has_careers_search")

    # Determine best apply URL
    if careers_url and ("indeed_ephemeral" in flags or "aggregator" in flags):
        # Prefer careers site over broken/aggregator links
        job["apply_url"] = careers_url
        job["link_status"] = "rewritten"
    elif careers_url and not url:
        # No original URL at all — use careers search
        job["apply_url"] = careers_url
        job["link_status"] = "rewritten"
    else:
        # Keep original URL (it may still be validated later)
        job["apply_url"] = url
        if not url:
            job["link_status"] = "missing"

    job["link_flags"] = flags
    return job


def validate_link(url, timeout=5):
    """Validate a single URL. Returns status string:
    'ok', 'dead:CODE', 'error:REASON', 'skip'"""
    if not url:
        return "skip"

    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return "error:bad_url"

    # LinkedIn returns 999 for non-browser agents — skip
    if "linkedin.com" in domain:
        return "ok"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        # Try HEAD first (lightweight)
        resp = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if resp.status_code == 405:
            # Server doesn't support HEAD — fall back to GET with stream
            resp = requests.get(url, timeout=timeout, allow_redirects=True,
                                headers=headers, stream=True)
            resp.close()

        if resp.status_code < 400:
            return "ok"
        else:
            return f"dead:{resp.status_code}"

    except requests.exceptions.Timeout:
        return "error:timeout"
    except requests.exceptions.ConnectionError:
        return "error:connection"
    except requests.exceptions.TooManyRedirects:
        return "error:too_many_redirects"
    except Exception as e:
        return f"error:{type(e).__name__}"


def validate_links_batch(jobs, max_workers=10, timeout=5):
    """Validate links for a batch of jobs concurrently.
    Updates each job's link_status in place. Returns summary counts."""
    counts = {"ok": 0, "dead": 0, "error": 0, "skip": 0, "rewritten": 0}

    # Collect jobs that need validation (not already rewritten/missing)
    to_validate = []
    for job in jobs:
        status = job.get("link_status", "")
        if status in ("rewritten", "missing"):
            counts["rewritten" if status == "rewritten" else "skip"] += 1
            continue
        url = job.get("apply_url") or job.get("url") or ""
        to_validate.append((job, url))

    if not to_validate:
        return counts

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {
            executor.submit(validate_link, url, timeout): job
            for job, url in to_validate
        }
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                status = future.result()
            except Exception:
                status = "error:unknown"
            job["link_status"] = status

            if status == "ok":
                counts["ok"] += 1
            elif status.startswith("dead"):
                counts["dead"] += 1
            elif status == "skip":
                counts["skip"] += 1
            else:
                counts["error"] += 1

    return counts
