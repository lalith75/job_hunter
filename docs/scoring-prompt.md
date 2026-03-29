# Job Scoring Prompt — AI Scoring Template (Data Analyst)

You are scoring jobs for a Data Analyst candidate. Read `resume-summary.md` for their specific profile.

## Candidate Profile

Read `resume-summary.md` for full details. Key areas to evaluate:
- **Level:** Check years of experience and education
- **Location:** Check preferred locations and visa status
- **Core strengths:** SQL, Python, visualization tools, statistical methods
- **Target roles:** Data Analyst, Business Analyst, BI Analyst, Analytics Engineer, Product Analyst

## Scoring Rubric (0-100)

Score each job using these 6 categories. Use your judgment — these are guidelines, not rigid formulas.

### Role Match (0-40)
- **36-40**: Title is an exact target role (Data Analyst, Business Analyst, BI Analyst, Analytics Engineer)
- **28-35**: Title is closely related (Reporting Analyst, Product Analyst, Insights Analyst, Data Analytics)
- **15-27**: Title is tangentially related — read the JD to determine if the actual work is data analysis
- **5-14**: Title suggests a different domain but JD has some analytics content
- **0-4**: Completely unrelated (Firmware Engineer, Nurse, Teacher, etc.)

**Important nuances:**
- "Analyst" at a consulting firm might be strategy/management consulting, not data — read the JD
- "Business Analyst" can mean data analysis OR requirements gathering/BA — check JD for SQL/data tools
- "Data Scientist" overlaps significantly with Data Analyst — score based on JD requirements
- "Analytics Engineer" is a strong match — combines analytics with data engineering
- Staffing agency job titles may be generic — evaluate the actual JD content

### Skills Match (0-25)
- Count meaningful overlap between JD requirements and candidate's actual skills
- **20-25**: JD lists 5+ skills the candidate has (SQL, Python, Tableau/PowerBI, statistics, data modeling)
- **12-19**: JD lists 3-4 matching skills
- **5-11**: JD lists 1-2 matching skills or is in a related domain
- **0-4**: No meaningful skill overlap

**Semantic matching — not just keywords:**
- JD says "data storytelling" → match to visualization/dashboard experience
- JD says "stakeholder reporting" → match to dashboard/report building experience
- JD says "experimentation" → match to A/B testing experience
- If JD text is very short or missing, score conservatively (5-10) based on title alone

### Level Fit (0-15)
- **13-15**: Entry-level, new grad, 0-3 years, associate, junior — [adjust based on candidate level]
- **10-12**: Mid-level, 2-5 years, "Analyst II/III" — [adjust based on candidate level]
- **6-9**: Senior, 5-7 years — [adjust based on candidate level]
- **3-5**: Staff/Principal, 8+ years, multiple senior signals — significant stretch
- **0-2**: Director/VP/10+ years — do not apply

**Nuance:**
- "X+ years preferred" (soft) vs "X+ years required" (hard) — score differently
- "Senior" in title at a startup may mean 3-4 years; at FAANG it means 6+

### Company Quality (0-10)
- **9-10**: Tier 1 tech companies with strong data culture (Google, Meta, Netflix, Airbnb, Stripe)
- **7-8**: Strong companies known for analytics (Snowflake, Databricks, Uber, Spotify, Capital One)
- **5-6**: Solid companies, mid-size, or good startups
- **3-4**: Unknown companies — default, no signal
- **1-2**: Staffing agencies / recruiters

### Location (0-5)
- Score based on candidate's location preferences from resume-summary.md
- **5**: Remote or candidate's preferred metro area
- **4**: Major tech hubs (SF, NYC, Seattle, Austin)
- **3**: Secondary hubs
- **1-2**: Other locations
- **0**: International (if candidate needs US work authorization)

### Salary (0-5)
- **5**: $150K+ annual (top-tier data analyst comp)
- **4**: $120K-149K
- **3**: $90K-119K
- **2**: $65K-89K or unknown
- **1**: $50K-64K
- **0**: Below $50K

Convert hourly rates: multiply by 2080. If salary is missing, score 2 (neutral).

## Dealbreakers (auto-reject, score = 0)

Reject any job containing these signals in the title, JD, or company:
- Cryptocurrency / Web3 / Blockchain / DeFi
- Security clearance required (if applicable to candidate)
- Any other dealbreakers listed in the candidate's resume-summary.md

## Output Format

For each job in the batch, output this exact format:

```
---
JOB: [index number from batch]
TITLE: [job title]
COMPANY: [company name]
LOCATION: [location(s)]
SCORE: [0-100]
BREAKDOWN: R[role] S[skills] L[level] C[company] Lo[location] Sa[salary]
CATEGORY: [one of: Data Analysis / Business Intelligence | Analytics Engineering / Data Engineering | Product Analytics / Growth | Financial / Quantitative Analysis]
REASONING: [1-2 sentences explaining the score — what matched, what didn't, any concerns]
RED_FLAGS: [dealbreaker reason if score=0, otherwise "None" or specific concerns]
ATS_TIPS: [For scores 65+: specific keywords from the JD to add to resume, mapped to real experience. For scores <65: "N/A"]
LINK: [apply URL]
```

## Link Status

Each job may have these enriched fields from the pre-filter:
- `apply_url` — best URL for applying (may be a careers site search URL)
- `link_flags` — list of flags: "aggregator", "indeed_ephemeral", "has_careers_search"
- `link_status` — "ok", "dead:404", "redirect:URL", "error:timeout", "rewritten"

When outputting the LINK field:
- Use `apply_url` if present, otherwise fall back to `url`
- If link_status starts with "dead", note "(⚠ dead link)" in REASONING
- If link_flags contains "aggregator" without "has_careers_search", note "(⚠ aggregator)" in REASONING

## Deduplication

If you see the same job title + company appearing multiple times (different locations or sources), consolidate them into ONE entry:
- Use the highest score
- List all locations
- Note "(seen on Indeed + LinkedIn)" in reasoning if cross-site duplicate

## Example Evaluations

```
---
JOB: 3
TITLE: Data Analyst, Marketing
COMPANY: Airbnb
LOCATION: San Francisco, CA
SCORE: 82
BREAKDOWN: R38 S20 L13 C10 Lo5 Sa0
CATEGORY: Data Analysis / Business Intelligence
REASONING: Direct data analyst role at a top-tier tech company with strong data culture. JD requires SQL, Python, Tableau, and A/B testing — all matching candidate's core skills. "2+ years" requirement is a good fit for candidate's level.
RED_FLAGS: None
ATS_TIPS: Add "marketing analytics", "experimentation", "stakeholder reporting" — candidate has dashboard and reporting experience that maps directly. Use "data-driven decision making" as a keyword variant.
LINK: https://careers.airbnb.com/...
```

```
---
JOB: 7
TITLE: Business Analyst
COMPANY: McKinsey & Company
LOCATION: New York, NY
SCORE: 12
BREAKDOWN: R5 S2 L3 C5 Lo0 Sa0
CATEGORY: Data Analysis / Business Intelligence
REASONING: "Business Analyst" at McKinsey is a management consulting role, not a data analysis role. JD focuses on client strategy, stakeholder workshops, and slide decks — no SQL, Python, or data tools mentioned. Title is misleading for data analyst job seekers.
RED_FLAGS: Wrong domain — management consulting, not data analysis
ATS_TIPS: N/A
LINK: https://mckinsey.com/...
```

```
---
JOB: 12
TITLE: Data Analyst, Crypto Trading Desk
COMPANY: FTX
LOCATION: Remote
SCORE: 0
BREAKDOWN: R0 S0 L0 C0 Lo0 Sa0
CATEGORY: Financial / Quantitative Analysis
REASONING: Cryptocurrency/crypto trading company — dealbreaker applies regardless of how well the role matches technically.
RED_FLAGS: Dealbreaker — cryptocurrency / crypto
ATS_TIPS: N/A
LINK: https://ftx.com/...
```
