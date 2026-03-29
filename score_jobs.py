"""
Job Scoring Script — Data Analyst Edition
Scores jobs from pending-review.json using weighted rubric:
  Role (0-40) + Skills (0-25) + Level (0-15) + Company (0-10) + Location (0-5) + Salary (0-5) = max 100
Output: scored-jobs/YYYY-MM-DD.md
"""

import argparse
import json
import os
import re
import sys
import io
from datetime import date
from difflib import SequenceMatcher
from link_utils import normalize_company, is_aggregator, rewrite_link, validate_links_batch

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TODAY = date.today().isoformat()

# ── Dealbreakers (loaded from config.json, with fallback) ────
_DEALBREAKERS_FALLBACK = [
    "cryptocurrency", "crypto", "web3", "blockchain", "defi",
    "security clearance", "clearance required", "ts/sci",
    "secret clearance", "top secret",
    # Uncomment the lines below if you're on a work visa:
    # "export control", "itar", "must be a u.s. citizen",
    # "must be a us citizen", "must be us citizen",
    # "u.s. person", "us person",
    # "must be a united states citizen", "united states citizenship required",
]
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), encoding="utf-8") as _cf:
        DEALBREAKERS = json.load(_cf).get("scoring", {}).get("dealbreakers", _DEALBREAKERS_FALLBACK)
except Exception:
    DEALBREAKERS = _DEALBREAKERS_FALLBACK

# ── Role scoring (0-40) ──────────────────────────────────────
# Exact title matches get highest scores
ROLE_EXACT = {
    # Core data analyst titles
    "data analyst": 40, "senior data analyst": 40,
    "business analyst": 38, "business data analyst": 38,
    "bi analyst": 37, "business intelligence analyst": 37,
    "analytics engineer": 38, "data analytics engineer": 38,
    "reporting analyst": 35, "insights analyst": 35,
    "product analyst": 36, "product data analyst": 36,
    "marketing analyst": 33, "marketing data analyst": 33,
    "financial analyst": 30, "finance analyst": 30,
    "operations analyst": 32, "strategy analyst": 30,
    "research analyst": 30, "quantitative analyst": 34,
    "analytics consultant": 33, "data analytics consultant": 33,
    "analytics manager": 35,
    # Adjacent strong roles
    "data engineer": 30, "analytics developer": 32,
    "bi developer": 30, "business intelligence developer": 30,
    "data visualization engineer": 32,
    "decision scientist": 30, "data scientist": 28,
    "revenue analyst": 33, "growth analyst": 33,
    "sql analyst": 35, "database analyst": 30,
}

ROLE_PARTIAL_KEYWORDS = {
    "analyst": 25, "analytics": 28,
    "data": 15, "business intelligence": 25,
    "reporting": 18, "visualization": 18,
    "dashboard": 16, "insights": 16,
    "bi ": 18, "metrics": 14,
    "forecasting": 16, "modeling": 12,
    "sql": 12, "etl": 12,
}

# Negative role signals — reduce score for unrelated roles
ROLE_NEGATIVE = {
    # Hardware / Embedded (completely unrelated)
    "firmware": -25, "embedded": -25, "asic": -25, "fpga": -25,
    "rtl": -25, "verilog": -25, "vhdl": -25,
    "hardware engineer": -20, "hardware design": -20,
    "silicon": -20, "board bring-up": -20,
    # Other unrelated
    "frontend": -15, "backend": -10, "full stack": -15, "fullstack": -15,
    "web developer": -20, "ios developer": -20, "android developer": -20,
    "mobile developer": -20,
    "product manager": -20, "project manager": -20,
    "scrum master": -25, "ui/ux": -25,
    "sales engineer": -15, "solutions architect": -10,
    "marketing manager": -20, "recruiter": -25,
    "java developer": -15, "node.js": -15,
    ".net developer": -18, "ruby": -15,
    "react": -15, "angular": -15, "vue": -15,
    "network engineer": -15, "systems administrator": -18,
    "database administrator": -10, "dba": -10,
    "help desk": -25, "it support": -25,
    "sap ": -15, "salesforce admin": -15,
    "mainframe": -20, "cobol": -25,
    "accounting": -15, "bookkeeper": -25,
    "mechanical engineer": -20, "civil engineer": -25,
    "chemical engineer": -20, "biomedical engineer": -15,
    "pharmacist": -25, "nurse": -25, "physician": -25,
    "teacher": -25, "professor": -25,
}

# Domain penalties — "analyst" in wrong domains
NON_DATA_ANALYST_SIGNALS = [
    "clinical trial", "pharmaceutical", "pharma",
    "biotech", "drug delivery", "biologics",
    "food safety", "usda", "haccp",
    "process validation", "equipment qualification",
    "quality assurance inspector", "qc analyst",
    "compliance analyst", "regulatory analyst",
]

# ── Skills scoring (0-25) ────────────────────────────────────
SKILLS_KEYWORDS = {
    # Core data analyst tools
    "\\bsql\\b": 5, "\\bsql server\\b": 3, "mysql": 3, "postgresql": 3,
    "tableau": 5, "power bi": 5, "powerbi": 5, "looker": 4,
    "python": 4, "\\br\\b": 3, "r programming": 3,
    "excel": 3, "google sheets": 2, "spreadsheet": 2,
    # Data analysis libraries
    "pandas": 4, "numpy": 3, "scipy": 3, "matplotlib": 3,
    "seaborn": 3, "plotly": 3, "scikit-learn": 3,
    # Statistical / analytical
    "statistical analysis": 4, "statistics": 3,
    "a/b testing": 4, "ab testing": 4,
    "regression": 3, "hypothesis testing": 3,
    "predictive modeling": 3, "machine learning": 2,
    "forecasting": 3, "time series": 3,
    # Data engineering adjacent
    "etl": 4, "elt": 4, "data pipeline": 4,
    "data warehouse": 4, "data modeling": 4,
    "snowflake": 4, "bigquery": 4, "redshift": 4,
    "databricks": 4, "dbt": 4, "airflow": 3,
    "spark": 3, "pyspark": 3,
    # BI / Visualization
    "data visualization": 4, "dashboard": 3,
    "reporting": 2, "kpi": 2, "metrics": 2,
    "google analytics": 3, "ga4": 3, "adobe analytics": 3,
    # Tools
    "jupyter": 2, "\\bgit\\b": 1, "jira": 1,
    "google data studio": 3, "data studio": 3,
    "alteryx": 3, "sas": 3, "spss": 3,
}

# ── Level scoring (0-15) ─────────────────────────────────────
LEVEL_SENIOR_WORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "director", "manager", "vp ", "vice president",
    "8+ years", "10+ years", "12+ years", "15+ years", "7+ years",
]
LEVEL_JUNIOR_WORDS = [
    "new grad", "entry level", "entry-level", "junior", "jr.",
    "associate", "co-op", "early career",
    "0-2 years", "1-3 years", "0-1 years",
    "recent grad",
]
# These need word-boundary matching (regex) to avoid substring false positives
LEVEL_JUNIOR_REGEX = [
    r'\bintern\b',       # matches "intern" but NOT "internship" or "non-internship"
    r'\bgraduate\b',     # matches "graduate" but NOT "graduated" or "undergraduate"
]
LEVEL_MID_WORDS = [
    "2-5 years", "3-5 years", "2-4 years", "2+ years", "3+ years",
    "4+ years", "mid-level", "mid level",
    " ii", " iii", "level 2", "level 3",
]

# ── Company scoring (0-10) ───────────────────────────────────
TIER1_COMPANIES = {
    # Big Tech (strong data/analytics culture)
    "google": 10, "meta": 10, "apple": 10, "amazon": 9,
    "microsoft": 9, "netflix": 10,
    # Data-first companies
    "snowflake": 9, "databricks": 9, "palantir": 8,
    "tableau": 8, "dbt labs": 8, "fivetran": 8,
    "looker": 8,
    # Tech / SaaS with strong analytics
    "uber": 9, "lyft": 9, "airbnb": 9, "stripe": 9,
    "doordash": 8, "instacart": 8, "coinbase": 7,
    "salesforce": 8, "adobe": 8, "intuit": 8,
    "slack": 8, "square": 8, "block": 8,
    "spotify": 9, "twitter": 7, "linkedin": 8,
    "nvidia": 8, "intel": 7, "qualcomm": 7,
    # Finance (strong quant/data culture)
    "jp morgan": 8, "jpmorgan": 8, "goldman sachs": 8,
    "morgan stanley": 8, "capital one": 7,
    "visa": 7, "mastercard": 7, "paypal": 7,
    "robinhood": 7, "sofi": 6,
    # Consulting
    "mckinsey": 8, "bcg": 8, "bain": 8,
    "deloitte": 7, "accenture": 6, "kpmg": 6,
    # Healthcare / Biotech
    "unitedhealth": 7, "optum": 7, "anthem": 6,
    # Consumer / Retail
    "walmart": 7, "target": 7, "nike": 7,
    "costco": 6, "procter": 7,
    # Other notable
    "tesla": 8, "spacex": 8, "boeing": 7,
    "cisco": 7, "ibm": 7, "oracle": 7,
    "twilio": 7, "datadog": 8, "splunk": 7,
    "elastic": 7, "confluent": 7,
    "roku": 6, "pinterest": 7, "snap": 7,
    "reddit": 7, "discord": 7,
}

# ── Location scoring (0-5) ───────────────────────────────────
# UPDATE these to match your preferred locations
LOCATION_SCORES = {
    "remote": 5,
    # Bay Area
    "san jose": 5, "sunnyvale": 5, "santa clara": 5, "mountain view": 5,
    "cupertino": 5, "palo alto": 5, "fremont": 5, "milpitas": 5,
    "san francisco": 5,
    # Major tech hubs
    "new york": 5, "nyc": 5, "manhattan": 5, "brooklyn": 5,
    "seattle": 4, "redmond": 4,
    "austin": 4, "dallas": 3, "plano": 3,
    "los angeles": 4, "irvine": 4, "san diego": 4,
    "chicago": 4, "boston": 4,
    # Secondary hubs
    "denver": 3, "boulder": 3, "colorado": 3,
    "portland": 3, "raleigh": 3, "durham": 3,
    "atlanta": 3, "nashville": 3, "miami": 3,
    "phoenix": 3, "minneapolis": 3,
    "pittsburgh": 2, "detroit": 2,
    "washington": 3, "dc": 3,
}

# ── Salary scoring (0-5) ─────────────────────────────────────
def score_salary(salary_str):
    if not salary_str:
        return 2  # Unknown salary gets neutral score
    salary_str = salary_str.lower().replace(",", "").replace("$", "")
    nums = re.findall(r'[\d]+(?:\.[\d]+)?', salary_str.replace(",", ""))
    if not nums:
        return 2
    amounts = [float(n) for n in nums]
    if "/hour" in salary_str or "hourly" in salary_str:
        top = max(amounts)
        annual = top * 2080
    elif "/year" in salary_str or "yearly" in salary_str or "annual" in salary_str:
        annual = max(amounts)
    else:
        top = max(amounts)
        if top < 200:
            annual = top * 2080
        elif top < 20000:
            annual = top * 12
        else:
            annual = top

    if annual >= 150000: return 5
    if annual >= 120000: return 4
    if annual >= 90000: return 3
    if annual >= 65000: return 2
    if annual >= 50000: return 1
    return 0


def check_dealbreakers(text):
    text_lower = text.lower()
    for db in DEALBREAKERS:
        if ' ' in db or '/' in db:
            if db in text_lower:
                return db
        else:
            if re.search(r'\b' + re.escape(db) + r'\b', text_lower):
                return db
    return None


def score_role(title, jd_text):
    title_lower = title.lower().strip()
    jd_lower = (jd_text or "").lower()

    score = 0

    # Check exact title matches
    best_exact = 0
    for role, pts in ROLE_EXACT.items():
        if role in title_lower:
            best_exact = max(best_exact, pts)
    score = best_exact

    # If no exact match, check partial keywords in title
    if score == 0:
        best_partial = 0
        for kw, pts in ROLE_PARTIAL_KEYWORDS.items():
            if kw in title_lower:
                best_partial = max(best_partial, pts)
        score = best_partial

    # If still 0, check JD text for role keywords (reduced weight)
    if score == 0:
        best_jd = 0
        for kw, pts in ROLE_PARTIAL_KEYWORDS.items():
            if kw in jd_lower:
                best_jd = max(best_jd, int(pts * 0.4))
        score = best_jd

    # Apply negative signals from title
    for neg, penalty in ROLE_NEGATIVE.items():
        if neg in title_lower:
            score = max(0, score + penalty)

    return min(40, score)


def score_skills(jd_text):
    if not jd_text:
        return 5
    jd_lower = jd_text.lower()
    total = 0
    for pattern, pts in SKILLS_KEYWORDS.items():
        if re.search(pattern, jd_lower):
            total += pts
    return min(25, total)


def score_level(title, jd_text):
    title_lower = title.lower()
    jd_lower = (jd_text or "").lower()
    combined = title_lower + " " + jd_lower

    year_matches = re.findall(r'(\d+)\+?\s*(?:years?|yrs?)', jd_lower)
    max_years = 0
    if year_matches:
        max_years = max(int(y) for y in year_matches)

    senior_count = 0
    for w in LEVEL_SENIOR_WORDS:
        if w in combined:
            senior_count += 1

    if max_years >= 8 or (senior_count >= 2 and max_years >= 5):
        return 3
    if max_years >= 7 or senior_count >= 2:
        return 4
    if max_years >= 5 or senior_count == 1:
        return 7

    for w in LEVEL_JUNIOR_WORDS:
        if w in combined:
            return 14
    for pattern in LEVEL_JUNIOR_REGEX:
        if re.search(pattern, combined):
            return 14

    for w in LEVEL_MID_WORDS:
        if w in combined:
            return 13

    if max_years <= 3 and max_years > 0:
        return 14
    elif max_years <= 5:
        return 11

    return 10


def score_company(company):
    if not company:
        return 4
    company_lower = company.lower()
    for name, pts in TIER1_COMPANIES.items():
        if len(name) <= 3:
            if re.search(r'\b' + re.escape(name) + r'\b', company_lower):
                return pts
        elif name in company_lower:
            return pts
    staffing = ["jobot", "dice", "staffing", "recruiting", "recruit",
                "talent", "hirequest", "manpower", "adecco", "insight global",
                "tek systems", "teksystems", "apex systems", "randstad",
                "robert half", "modis", "hays", "kforce", "kelly services",
                "motion recruitment", "yoh", "spectraforce"]
    for s in staffing:
        if s in company_lower:
            return 3
    return 5


def score_location(location, is_remote):
    if not location:
        return 2
    loc_lower = location.lower()
    if is_remote or "remote" in loc_lower:
        return 5
    best = 1
    for loc, pts in LOCATION_SCORES.items():
        if loc in loc_lower:
            best = max(best, pts)
    return best


def categorize_job(title, jd_text):
    """Categorize into subcategory for organizing output."""
    title_lower = title.lower()
    jd_lower = (jd_text or "").lower()

    # Analytics Engineering / Data Engineering
    if any(k in title_lower for k in ["analytics engineer", "data engineer",
                                        "etl", "data pipeline", "bi developer"]):
        return "Analytics Engineering / Data Engineering"

    # Product / Growth Analytics
    if any(k in title_lower for k in ["product analyst", "growth analyst",
                                        "product analytics", "growth analytics"]):
        return "Product Analytics / Growth"

    # Financial / Quantitative
    if any(k in title_lower for k in ["financial analyst", "finance analyst",
                                        "quantitative", "revenue analyst",
                                        "investment analyst"]):
        return "Financial / Quantitative Analysis"

    # Default: core data analysis / BI
    return "Data Analysis / Business Intelligence"


def format_location(location, is_remote):
    if not location:
        return "TBD"
    loc = location.strip()
    if is_remote:
        if "remote" not in loc.lower():
            loc += " (remote)"
    return loc


def score_job(job):
    """Score a single job, returns (score, breakdown, category, dealbreaker_reason)."""
    title = job.get("jd_title") or job.get("title_hint") or ""
    jd_text = job.get("jd_text") or ""
    company = job.get("jd_company") or ""
    location = job.get("jd_location") or ""
    salary = job.get("salary") or ""
    is_remote = job.get("is_remote", False)

    combined_text = f"{title} {jd_text} {company}".lower()
    db = check_dealbreakers(combined_text)
    if db:
        return (0, {}, categorize_job(title, jd_text), db)

    role = score_role(title, jd_text)
    skills = score_skills(jd_text)
    level = score_level(title, jd_text)
    comp = score_company(company)
    loc = score_location(location, is_remote)
    sal = score_salary(salary)

    # Domain penalty for "analyst" roles in wrong domain (pharma/QC/regulatory)
    if any(w in title.lower() for w in ["analyst", "validation", "quality"]):
        domain_hits = sum(1 for sig in NON_DATA_ANALYST_SIGNALS if sig in combined_text)
        if domain_hits >= 2:
            role = max(0, role - 25)
        elif domain_hits == 1:
            role = max(0, role - 15)

    # Boost skills when title is a strong match but JD is sparse
    if 20 < len(jd_text) < 200 and role >= 35:
        skills = max(skills, 10)

    # Penalize completely empty JDs
    if len(jd_text.strip()) == 0:
        skills = min(skills, 3)
        level = min(level, 6)

    total = role + skills + level + comp + loc + sal
    breakdown = {
        "role": role, "skills": skills, "level": level,
        "company": comp, "location": loc, "salary": sal
    }

    return (total, breakdown, categorize_job(title, jd_text), None)


# ── Fuzzy dedup utilities ─────────────────────────────────────

_TITLE_STRIP = re.compile(
    r'\s*[-–—]\s*(US|USA|Remote|Hybrid|Onsite|On-site)$'
    r'|\s*\(.*?\)\s*$'
    r'|\s*,?\s*(II|III|IV|Jr\.?|Sr\.?|Senior|Junior)$',
    re.IGNORECASE
)


def normalize_title(title):
    if not title:
        return ""
    t = title.lower().strip()
    t = _TITLE_STRIP.sub("", t).strip()
    return t


def title_similarity(t1, t2):
    n1, n2 = normalize_title(t1), normalize_title(t2)
    if not n1 or not n2:
        return 0.0
    seq_ratio = SequenceMatcher(None, n1, n2).ratio()
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if tokens1 or tokens2:
        jaccard = len(tokens1 & tokens2) / len(tokens1 | tokens2)
    else:
        jaccard = 0.0
    return 0.6 * seq_ratio + 0.4 * jaccard


def get_source_priority(job):
    site = (job.get("site") or "").lower()
    url = (job.get("url") or "").lower()
    if site in ("company", "employer", "direct"):
        return 10
    if "linkedin" in site or "linkedin.com" in url:
        return 8
    if "dice" in site or "dice.com" in url:
        return 6
    if "indeed" in site or "indeed.com" in url:
        return 4
    if "glassdoor" in site or "glassdoor.com" in url:
        return 5
    if "ziprecruiter" in site or "ziprecruiter.com" in url:
        return 5
    if is_aggregator(url):
        return 1
    return 5


def fuzzy_dedup(jobs, threshold=0.75):
    if not jobs:
        return jobs, 0
    company_groups = {}
    no_company = []
    for job in jobs:
        company = job.get("jd_company") or job.get("company") or ""
        norm_co = normalize_company(company)
        if not norm_co:
            no_company.append(job)
        else:
            company_groups.setdefault(norm_co, []).append(job)

    deduped = list(no_company)
    total_removed = 0

    for norm_co, group in company_groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        clusters = []
        for job in group:
            title = job.get("jd_title") or job.get("title_hint") or ""
            placed = False
            for cluster in clusters:
                rep_title = cluster[0].get("jd_title") or cluster[0].get("title_hint") or ""
                if title_similarity(title, rep_title) >= threshold:
                    cluster.append(job)
                    placed = True
                    break
            if not placed:
                clusters.append([job])
        for cluster in clusters:
            if len(cluster) == 1:
                deduped.append(cluster[0])
            else:
                def job_quality(j):
                    jd_len = len(j.get("jd_text") or "")
                    source_pri = get_source_priority(j)
                    return (jd_len, source_pri)
                cluster.sort(key=job_quality, reverse=True)
                best = cluster[0]
                all_locations = set()
                for j in cluster:
                    loc = j.get("jd_location") or ""
                    if loc:
                        all_locations.add(loc.strip())
                if len(all_locations) > 1:
                    best["jd_location"] = " / ".join(sorted(all_locations))
                deduped.append(best)
                total_removed += len(cluster) - 1

    return deduped, total_removed


def run_pre_filter(jobs):
    """Fast keyword pre-filter. Eliminates obvious junk (score < 20).
    Then deduplicates, rewrites links, and validates.
    Writes passing jobs to filtered-jobs.json for Claude AI scoring."""
    try:
        with open("config.json", encoding="utf-8") as cf:
            config = json.load(cf)
        link_cfg = config.get("link_validation", {})
    except Exception:
        link_cfg = {}
    link_enabled = link_cfg.get("enabled", True)
    link_timeout = link_cfg.get("timeout_sec", 5)
    link_workers = link_cfg.get("max_workers", 10)

    passed = []
    eliminated = {"dealbreaker": 0, "low_score": 0}

    for job in jobs:
        total, breakdown, category, db_reason = score_job(job)
        if db_reason:
            eliminated["dealbreaker"] += 1
            continue
        if total < 30:
            eliminated["low_score"] += 1
            continue
        job["_prefilter_score"] = total
        job["_prefilter_category"] = category
        passed.append(job)

    deduped, num_dupes = fuzzy_dedup(passed)

    link_stats = {"aggregator": 0, "indeed": 0, "rewritten": 0}
    for job in deduped:
        rewrite_link(job)
        flags = job.get("link_flags", [])
        if "aggregator" in flags:
            link_stats["aggregator"] += 1
        if "indeed_ephemeral" in flags:
            link_stats["indeed"] += 1
        if job.get("link_status") == "rewritten":
            link_stats["rewritten"] += 1

    val_counts = {"ok": 0, "dead": 0, "error": 0, "skip": 0, "rewritten": 0}
    if link_enabled:
        val_counts = validate_links_batch(deduped, max_workers=link_workers, timeout=link_timeout)

    with open("filtered-jobs.json", "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"\nPre-filter complete:")
    print(f"  Total:        {len(jobs)}")
    print(f"  Passed:       {len(passed)}")
    print(f"  Dealbreakers: {eliminated['dealbreaker']}")
    print(f"  Low score:    {eliminated['low_score']}")
    print(f"  Deduped:      {num_dupes} duplicates removed, {len(deduped)} unique")
    print(f"  Links:        {link_stats['aggregator']} aggregator, {link_stats['indeed']} Indeed (ephemeral), {link_stats['rewritten']} rewritten to careers sites")
    if link_enabled:
        print(f"  Link check:   {val_counts['ok']} ok, {val_counts['dead']} dead, {val_counts['error']} errors, {val_counts['skip']} skipped")
    print(f"  Output:       filtered-jobs.json ({len(deduped)} jobs)")


def main():
    parser = argparse.ArgumentParser(description="Job scoring pipeline")
    parser.add_argument("--pre-filter", action="store_true",
                        help="Pre-filter mode: eliminate junk, write filtered-jobs.json for AI scoring")
    args = parser.parse_args()

    with open("pending-review.json", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        print("No jobs in pending-review.json")
        return

    print(f"Loaded {len(jobs)} jobs")

    if args.pre_filter:
        run_pre_filter(jobs)
        return

    scored = []
    dealbreaker_count = 0
    for job in jobs:
        total, breakdown, category, db_reason = score_job(job)
        title = job.get("jd_title") or job.get("title_hint") or "Unknown"
        company = job.get("jd_company") or "Unknown"
        location = format_location(job.get("jd_location"), job.get("is_remote", False))
        url = job.get("url") or ""
        salary = job.get("salary") or ""

        if db_reason:
            dealbreaker_count += 1
            scored.append({
                "score": 0, "title": title, "company": company,
                "location": location, "url": url, "category": category,
                "breakdown": {}, "dealbreaker": db_reason,
                "salary": salary, "skip_reason": f"Dealbreaker: {db_reason}"
            })
        else:
            skip_reason = None
            if total < 45:
                skip_reason = get_skip_reason(title, job.get("jd_text", ""), breakdown)
            scored.append({
                "score": total, "title": title, "company": company,
                "location": location, "url": url, "category": category,
                "breakdown": breakdown, "dealbreaker": None,
                "salary": salary, "skip_reason": skip_reason
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    tier_a = [j for j in scored if j["score"] >= 65]
    tier_b = [j for j in scored if 45 <= j["score"] < 65]
    skipped = [j for j in scored if j["score"] < 45]

    print(f"Tier A: {len(tier_a)}, Tier B: {len(tier_b)}, Skipped: {len(skipped)} ({dealbreaker_count} dealbreakers)")

    md = generate_markdown(tier_a, tier_b, skipped, len(jobs))
    os.makedirs("scored-jobs", exist_ok=True)
    out_path = f"scored-jobs/{TODAY}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Output written to {out_path}")

    with open("pending-review.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    print(f"Cleared pending-review.json ({len(jobs)} jobs scored and archived)")


def get_skip_reason(title, jd_text, breakdown):
    title_lower = title.lower()
    role_score = breakdown.get("role", 0)

    if role_score == 0:
        for category, keywords in [
            ("Hardware/Embedded", ["firmware", "embedded", "asic", "fpga", "rtl", "verilog", "hardware"]),
            ("Web/frontend/backend SWE", ["frontend", "backend", "full stack", "fullstack", "web", "react", "angular", "vue", "node"]),
            ("DevOps/Cloud/SRE", ["devops", "cloud", "sre", "site reliability", "infrastructure"]),
            ("Mobile development", ["ios", "android", "mobile", "swift", "kotlin"]),
            ("Management/PM", ["product manager", "project manager", "scrum master", "program manager"]),
            ("IT/Support", ["help desk", "it support", "systems administrator", "network admin"]),
            ("Sales/Business", ["sales engineer", "business development", "account", "marketing manager"]),
            ("Security/Cyber", ["cybersecurity", "security analyst", "soc analyst", "penetration"]),
        ]:
            for kw in keywords:
                if kw in title_lower:
                    return category
        return "Unrelated role"

    if role_score <= 10:
        return "Weak role match"
    skills_score = breakdown.get("skills", 0)
    if skills_score <= 3:
        return "Low skills overlap"
    return "Below threshold"


def generate_markdown(tier_a, tier_b, skipped, total):
    lines = []
    lines.append(f"\n# Job Scoring Summary - {TODAY}\n")
    lines.append(f"**{total} jobs scored** | {len(tier_a)} Tier A | {len(tier_b)} Tier B | {len(skipped)} skipped/irrelevant")
    lines.append("Scoring: Role (0-40) + Skills (0-25) + Level (0-15) + Company (0-10) + Location (0-5) + Salary (0-5) = max 100\n")
    lines.append("---\n")

    lines.append(f"## TIER A - Apply ASAP ({len(tier_a)} jobs, score 65+)\n")

    categories = ["Data Analysis / Business Intelligence",
                   "Analytics Engineering / Data Engineering",
                   "Product Analytics / Growth",
                   "Financial / Quantitative Analysis"]

    for cat in categories:
        cat_jobs = [j for j in tier_a if j["category"] == cat]
        if not cat_jobs:
            continue
        lines.append(f"### {cat}\n")
        lines.append("| Score | Title | Company | Location | Link |")
        lines.append("|-------|-------|---------|----------|------|")
        for j in cat_jobs:
            link = f"[apply]({j['url']})" if j['url'] else "N/A"
            lines.append(f"| {j['score']} | {j['title']} | {j['company']} | {j['location']} | {link} |")
        lines.append("")

    lines.append(generate_advisory_notes(tier_a, tier_b))
    lines.append("---\n")

    lines.append(f"## TIER B - Worth Applying ({len(tier_b)} jobs, score 45-64)\n")
    lines.append("| Score | Title | Company | Location | Link |")
    lines.append("|-------|-------|---------|----------|------|")
    for j in tier_b:
        link = f"[apply]({j['url']})" if j['url'] else "N/A"
        lines.append(f"| {j['score']} | {j['title']} | {j['company']} | {j['location']} | {link} |")
    lines.append("")

    lines.append("---\n")

    lines.append(f"## Skipped - Irrelevant ({len(skipped)} jobs)\n")
    lines.append("<details>")
    lines.append("<summary>Click to expand skipped jobs</summary>\n")
    lines.append("| # | Title | Company | Reason |")
    lines.append("|---|-------|---------|--------|")
    for i, j in enumerate(skipped, 1):
        reason = j.get("skip_reason") or "Below threshold"
        if j.get("dealbreaker"):
            reason = f"Dealbreaker: {j['dealbreaker']}"
        lines.append(f"| {i} | {j['title']} | {j['company']} | {reason} |")
    lines.append("\n</details>")

    return "\n".join(lines)


def generate_advisory_notes(tier_a, tier_b):
    notes = []

    if tier_a:
        top = tier_a[0]
        notes.append(f"> **Top pick:** {top['title']} at {top['company']} ({top['score']}) in {top['location']}. Highest scoring role this batch.")

    # Company clusters
    company_counts = {}
    for j in tier_a:
        co = j["company"].lower().split()[0] if j["company"] else ""
        if co in ["google", "meta", "amazon", "microsoft", "apple", "uber", "netflix",
                   "snowflake", "databricks", "stripe", "airbnb"]:
            company_counts.setdefault(co.title(), []).append(j)

    for co, jobs_list in sorted(company_counts.items(), key=lambda x: len(x[1]), reverse=True):
        if len(jobs_list) >= 2:
            roles_str = ", ".join(f"{j['title']} ({j['score']})" for j in jobs_list[:5])
            notes.append(f"> **{co} cluster ({len(jobs_list)} roles):** {roles_str}.")

    # Remote opportunities
    remote_a = [j for j in tier_a if "remote" in j["location"].lower()]
    if remote_a:
        remote_str = ", ".join(f"{j['company']} ({j['score']})" for j in remote_a[:6])
        notes.append(f"> **Remote Tier A:** {len(remote_a)} remote-friendly roles — {remote_str}.")

    return "\n\n".join(notes)


if __name__ == "__main__":
    main()
