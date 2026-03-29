# Job Automation — Claude Code Instructions

## "Score my jobs" Workflow

When the user says "score my jobs", follow these steps exactly:

### Step 1: Pre-filter
Run: `python score_jobs.py --pre-filter`

This eliminates obvious junk (hardware, firmware, PM, nurse, etc.) using the fast keyword scorer.
It reads `pending-review.json` and writes `filtered-jobs.json` with jobs scoring >= 30.

If pending-review.json is empty or has 0 jobs, tell the user "No jobs to score — run the collectors first."

### Step 2: Load context
Read these files:
- `filtered-jobs.json` — the jobs to score
- `resume-summary.md` — candidate profile
- `docs/scoring-prompt.md` — scoring rubric, output format, examples

Note: Jobs in filtered-jobs.json now include link metadata:
- `apply_url` — best URL for applying (may be a careers site search URL)
- `link_flags` — list: "aggregator", "indeed_ephemeral", "has_careers_search"
- `link_status` — "ok", "dead:CODE", "error:REASON", "rewritten"
Use `apply_url` instead of `url` when writing the Link column.
Flag dead/aggregator links with ⚠ in the report.

### Step 3: Score in batches
Process `filtered-jobs.json` in batches of 15-20 jobs:

For each batch:
1. Read the next 15-20 jobs from filtered-jobs.json
2. For each job, evaluate against the rubric in scoring-prompt.md
3. Output the structured format defined in scoring-prompt.md
4. Accumulate all scored results

While scoring, deduplicate: if you see the same (title, company) pair appearing multiple times (different locations or scraped from different sites), consolidate into one entry with all locations listed.

### Step 4: Write the report
Write `scored-jobs/YYYY-MM-DD.md` (using today's date) with this structure:

```
# Job Scoring Summary — YYYY-MM-DD

**N unique jobs scored** | X Tier A | Y Tier B | Z skipped
Scoring: Role(0-40) + Skills(0-25) + Level(0-15) + Company(0-10) + Location(0-5) + Salary(0-5) = max 100

---

## TIER A — Apply ASAP (score 65+)

### [Subcategory: Data Analysis / Business Intelligence]

| Score | Breakdown | Title | Company | Location(s) | Why | ATS Tips | Link |
|-------|-----------|-------|---------|-------------|-----|----------|------|

[Repeat for each subcategory that has jobs: Analytics Engineering / Data Engineering, Product Analytics / Growth, Financial / Quantitative Analysis]

> **Advisory notes** — write 3-5 natural-language observations about this batch:
> top picks, company clusters, remote opportunities, notable trends

---

## TIER B — Worth Applying (score 45-64)

| Score | Title | Company | Location | Link |
|-------|-------|---------|----------|------|

---

## Skipped (score < 45)

<details>
<summary>Click to expand (N skipped jobs)</summary>

| # | Title | Company | Reason |
|---|-------|---------|--------|

</details>
```

### Step 5: Clean up
- Clear pending-review.json: write `[]` to it
- Delete filtered-jobs.json (temporary file)
- Print summary: "Scored X unique jobs -> Y Tier A, Z Tier B, W skipped. Report: scored-jobs/YYYY-MM-DD.md"

---

## "Tailor my resumes" Workflow

When the user says "tailor my resumes", follow these steps:

### Step 1: Find the scored report
Find the latest file in `scored-jobs/` (by date in filename).
If the user specifies a date, use that instead.
If no scored report exists, tell the user to run "score my jobs" first.

### Step 2: Parse Tier A jobs
Read the scored report and extract every Tier A row:
- Score, Title, Company, Subcategory, ATS Tips (keywords), Apply Link
The ATS Tips column contains comma-separated quoted strings like: "keyword1", "keyword2", "keyword3"

### Step 3: Cluster by keyword profile
Group the Tier A jobs into 4-8 keyword profiles based on ATS keyword similarity.
Each profile should have a short name (e.g., "Product_Analytics", "BI_Reporting").
Jobs with very similar keyword sets share the same profile.

Print the proposed clusters and job counts for the user to see, then proceed.

### Step 4: Read base resume
Read the base resume docx from the path in config.json `resume.base_docx_path`.
Identify the paragraph structure (summary, skills, work experience bullets, projects, education).

### Step 5: Generate tailored resumes
For each keyword profile, create a tailored resume by modifying the base resume using python-docx:

**Tailoring rules:**
- **One-page constraint:** The base resume is one page. All tailored variants MUST stay one page.
  Only REFRAME existing text — never add new paragraphs, bullets, or sections.
  Keep replacement text at similar or shorter length than the original.
- **Summary:** Rewrite opening to lead with the profile's keywords.
- **Skills:** Reorder items to put most relevant first.
- **Work Experience bullets:** Reframe existing achievements using target keywords.
  NEVER fabricate experience. Only rephrase what the candidate actually did.
- **Projects:** Rename titles and reframe descriptions using domain language.
- **Education coursework:** Reorder to emphasize most relevant courses.

**Truthfulness rule:** If a keyword doesn't map to any real experience, DO NOT add it.
Note which keywords were skipped and why in the mapping file.

Save each variant to: `tailored-resumes/YYYY-MM-DD/ProfileName.docx`

### Step 6: Write the mapping file
Write `tailored-resumes/YYYY-MM-DD/MAPPING.md` with this format:

```
# Resume Tailoring Map — YYYY-MM-DD

**N tailored resume variants** generated from M Tier A jobs

## Product_Analytics.docx
Keywords: "product analytics", "A/B testing", "SQL", ...
Use for:
- (91) Product Data Analyst | Google | [Apply](link)
- (88) Product Analyst | Uber | [Apply](link)
- ...

## BI_Reporting.docx
Keywords: "Tableau", "Power BI", "dashboard", ...
Use for:
- (84) BI Analyst | Microsoft | [Apply](link)
- ...
```

Repeat for each profile.

### Step 7: Summary
Print: "Generated N tailored resumes for M Tier A jobs. See tailored-resumes/YYYY-MM-DD/MAPPING.md"

---

## Important Rules
- Only suggest ATS keyword additions that are truthful — the candidate must actually have the experience
- Dealbreakers are absolute — score 0, no exceptions
- When JD text is missing or very short, score conservatively and note "sparse JD" in reasoning
- Pipe characters (|) in company names break markdown tables — replace with parentheses
- Do NOT ask the user to review each batch — score all batches autonomously and write the final report

## File Locations
- Jobs to score: `pending-review.json` -> `filtered-jobs.json` (after pre-filter)
- Resume: `resume-summary.md`
- Scoring rubric: `docs/scoring-prompt.md`
- Output: `scored-jobs/YYYY-MM-DD.md`
- Tailored resumes: `tailor_resumes.py` (generates `tailored-resumes/YYYY-MM-DD/*.docx`)
- Link utilities: `link_utils.py` (URL rewriting, aggregator detection, validation)
- Dedup database: `seen-jobs.json` (read-only during scoring)
- Config: `config.json` (has dealbreakers list, resume path, link validation settings)
