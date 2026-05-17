# Job Filtering Preferences

These are the criteria for filtering scraped job postings before they reach the daily email digest. The AI reads this file verbatim as part of its system prompt.

## About the candidate

- Student / early-career professional based in Madrid.
- Targeting **first job, internship, off-cycle, or summer programs**. Not targeting mid-senior or senior roles.
- Open to roles in **Madrid AND London** (the scraper already filters location upstream — this file is about role/sector fit, not geography).

## STRONG KEEP — clear matches

These should always be kept. Look for these signals in the title, department, or company context:

**Sectors / industries (strong match):**
- Investment Banking (IB) — M&A, ECM, DCM, Leveraged Finance, Coverage teams
- Private Equity (PE), Venture Capital (VC), Hedge Funds (HF)
- Asset Management, Wealth Management, Investment Funds
- Global Markets — Sales & Trading, Equity Research, Fixed Income, FX, Derivatives, Structured Products
- Management Consulting (MBB and tier-2: McKinsey, BCG, Bain, Oliver Wyman, A.T. Kearney, etc.) — strategy, financial advisory, restructuring
- Corporate & Investment Banking (CIB)
- Real Estate Investment / REITs

**Functions / roles (strong match):**
- Investment Analyst, Equity Analyst, Credit Analyst, Research Analyst
- Business Analyst, Strategy Analyst, M&A Analyst
- Trader, Quant, Sales (markets), Structurer
- Financial Advisor, Corporate Finance, Transaction Services
- Risk, Compliance, AML — within banks / funds / consulting
- Data Analyst, Data Scientist, Quantitative Researcher — at finance or consulting firms
- AI / ML Engineer — at finance, consulting, or fintech firms

**Programs (strong match — keep even if title is generic):**
- Off-Cycle Internship (any function) — **highest priority**
- Summer Internship / Summer Analyst Program
- Graduate Program / Analyst Program / Rotational Program
- Spring Insight / Spring Week / Discovery Program
- Cadetship / Trainee Program — only if at a finance/consulting firm

## KEEP IF UNCERTAIN — borderline cases I want surfaced

When the title is ambiguous or the firm is in scope but the function is unusual, **lean toward KEEP**. I'd rather see it in the email and decide myself.

- Tech / Software Engineering / Data roles **at a finance, consulting, or asset-management firm** (e.g. "Software Engineer at BlackRock", "Data Engineer at Goldman Sachs") — KEEP. These firms' tech orgs are often a viable career entry point.
- Operations, Middle Office, Back Office at IBs / banks — KEEP, even if not the most prestigious.
- Internal Audit / Internal Consulting at Big 4 (Deloitte, KPMG, EY, PwC) — KEEP.
- "Compliance Officer", "Risk Analyst", etc. at any in-scope firm — KEEP.
- Foreign-language roles (French, German, Italian) — KEEP if the function matches; the language requirement is my decision to make.
- Roles labeled "VIE" (Volontariat International en Entreprise) — KEEP, these are early-careers programs.
- Generic titles like "Intern", "Praktikant", "Stagiaire", "Becario" at an in-scope firm — KEEP, the function is just not in the title.

## DROP — clearly outside scope

Drop these even with the "when in doubt keep" rule, because they're unambiguously not a fit:

- **Retail / floor staff / sales clerk** — "Dependiente", "Sales Associate at Mango/Zara", "Cashier", "Customer Service Rep".
- **Blue-collar / manual labor** — warehouse, logistics floor, manufacturing line, driving, security guard.
- **Senior / C-level / VP+ roles** — "Director with 15+ years", "VP", "Senior Manager", "Head of …", "CFO", "Partner", "Managing Director". I'm early-career; these are out of reach and out of scope.
  - ⚠️ **"Associate" is NOT a senior signal — it is an entry-level title at IBs / funds / consultancies and must be KEPT.** Same for "Analyst", "Intern", "Trainee", "Junior", "Becario", "Stagiaire", "Praktikant", "Graduate". Only the explicit senior labels above (VP / Director / Head / Partner / MD / CXO / Senior X) are DROP signals — never apply the seniority rule to junior titles.
- **Roles in clearly unrelated industries** — agriculture, fashion design, food service, hospitality, healthcare clinical, education teaching, NGO field work — **unless** explicitly at a finance/consulting firm (e.g. "Healthcare Sector Analyst at BCG" → KEEP because it's consulting).
- **Pure HR / Recruiting / Talent Acquisition** roles — unless explicitly part of a finance/consulting graduate program.
- **Pure Marketing / Communications / PR** roles — unless they're at a fund or for an investor-relations function.
- **Engineering** roles at non-finance firms (industrial engineer, mechanical engineer, civil engineer at a construction company, etc.).

## Hard rule

**When in doubt, KEEP the job.** False negatives (dropping a relevant role) are MUCH worse than false positives (keeping a marginal one). The candidate can scan a longer email in 30 seconds; missing a posting can mean missing an entire application cycle.

If a job *might* match the candidate's interests — keep it. Only drop jobs that are clearly and unambiguously in the DROP list above.
