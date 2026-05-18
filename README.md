# Job Tracker

A personal job-listing tracker (Madrid + London) for early-careers profiles targeting finance / IB / consulting / private equity. Every day it scrapes ~50 corporate career portals, filters the results through a local LLM against my own criteria, sends a digest email to my inbox at 07:00, and serves a public Next.js dashboard on Vercel that anyone with the link can browse.

---

## The problem

Looking for internships in investment banking, PE, consulting and markets from Madrid means:

- **~50 different portals** (Workday, Greenhouse, SAP SuccessFactors, TalentLink, Cegid TalentSoft, Yello, Phenom, iCIMS, Pinpoint, custom WordPress…). Each with its own quirks: Cloudflare, HTTP/2 errors, JS-heavy SPAs, weird pagination, inconsistent location filtering.
- **Short recruiting cycles**: many openings close in 3-7 days. If you don't see them in time, they're gone.
- **Lots of noise in every portal**: a careers page can have 500 listings of which 20 are relevant (an IB rejects retail / reception / senior-audit positions).
- **I don't want to spend money**: the AI filter has to be local.
- **I don't want to maintain complex infrastructure**: no remote-server cron, no K8s, etc. Just a Windows PC and a local cron.

---

## The solution

Daily pipeline plus a permanent public dashboard:

```
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌────────────┐    ┌───────┐
│ Scrapers    │ →  │ Supabase │ →  │ AI filter  │ →  │ Email      │ →  │ Inbox │
│ (50 portals)│    │ (Postgres)│   │ (Ollama)   │    │ (Resend)   │    │       │
└─────────────┘    └────┬─────┘    └────────────┘    └────────────┘    └───────┘
                        │
                        └──→ ┌──────────────────┐   ┌─────────┐   ┌─────────┐
                             │ Next.js frontend │ → │ Vercel  │ → │ Browser │
                             │ (ISR every 10m)  │   │ (free)  │   │  (any)  │
                             └──────────────────┘   └─────────┘   └─────────┘
```

1. **Scrape**: per company, a dedicated scraper (or the generic one) extracts titles + URLs + location. Only Madrid matches (or Madrid + London depending on the company).
2. **Upsert to Supabase**: the DB diffs URLs against what it already had. New URLs flow into the filter stage; the rest already have a persisted decision from earlier runs.
3. **Local AI filter**: `qwen2.5:7b` running on Ollama reads `config/preferences.md` and decides KEEP / DROP for every new URL. Decisions are persisted to the DB.
4. **Email digest**: two sections — *New today* (Section A) and *Last 7 days* (Section B). Resend sends the HTML to the inbox.
5. **Public dashboard**: a Next.js 14 app on Vercel reads the same Supabase tables (anon key, RLS-protected) and renders the filtered listings with search and date controls. Auto-revalidates every 10 minutes via ISR — fresh data after each daily run with no manual deploy.

The cron is Windows Task Scheduler, not Railway nor a remote cron. Zero cost — everything local except Supabase (free tier), Resend (free tier), and Vercel (Hobby tier).

---

## Architecture

```
job-tracker/
├── scraper/                    # Everything scraper + filter + email
│   ├── config/
│   │   ├── companies.yaml      # List of companies + URL + ATS type
│   │   └── preferences.md      # Filtering criteria for the AI
│   ├── src/
│   │   ├── main.py             # Orchestration: scrape → upsert → filter → email
│   │   ├── models.py           # Pydantic: CompanyConfig, Job, FilterDecision
│   │   ├── db.py               # Supabase: upsert_jobs, record_filter_decisions, get_jobs_last_n_days
│   │   ├── ai_filter.py        # Ollama call with structured JSON output + batching
│   │   ├── email_digest.py     # HTML render + Resend send
│   │   └── scrapers/           # One scraper per ATS or per company with custom logic
│   │       ├── base.py             # Location matching (multi-city, peer-city rejection)
│   │       ├── playwright_scraper.py  # Generic SPA: captures XHR JSON + DOM heuristics
│   │       ├── workday.py          # Workday CXS API
│   │       ├── greenhouse.py       # Greenhouse JSON API
│   │       ├── lever.py            # Lever JSON API
│   │       ├── html_scraper.py     # BeautifulSoup
│   │       ├── sap_successfactors.py  # For CaixaBank / Deloitte / KPMG
│   │       ├── talentlink.py       # Atom feed + HTML fallback (Evercore, Jefferies, Lazard, Nomura)
│   │       ├── cegid_talentsoft.py # ASP.NET WebForms (Amundi, Credit Agricole)
│   │       ├── alantra.py          # WordPress admin-ajax
│   │       ├── bcg.py              # Phenom People /widgets
│   │       ├── mckinsey.py         # Real-Chrome + stealth bypass
│   │       ├── morgan_stanley.py   # JSON endpoint behind the SPA
│   │       └── (... 8 more scrapers, one per gotcha encountered)
│   ├── run_scrape.ps1          # PowerShell wrapper invoked by Task Scheduler
│   └── pyproject.toml          # uv-managed Python deps
├── supabase/
│   └── schema.sql              # DDL: companies, jobs, scrape_runs
├── frontend/                   # Next.js app reading from Supabase (separate deploy)
├── CLAUDE.md                   # Detailed technical notes (verified scrapers, per-ATS gotchas)
└── README.md                   # This file
```

### DB schema (Supabase)

```sql
companies   (id UUID PK, name UNIQUE, careers_url, ats_platform, created_at)
jobs        (id UUID PK, company_id FK, external_id, title, url, location, department,
             job_type, description,
             is_active, first_seen_at, last_seen_at,
             ai_keep BOOLEAN, ai_reason TEXT,
             UNIQUE (company_id, url))
scrape_runs (id UUID PK, started_at, completed_at, new_jobs_found, status, errors JSONB)
```

`ai_keep` persists filter decisions: `NULL`=pending/passthrough, `true`=keep, `false`=drop. The Section B query uses `ai_keep IS NOT FALSE` (includes NULL and TRUE — lean-inclusive).

---

## Stack

| Layer | Tool | Why |
|---|---|---|
| Scraping | `playwright` + `httpx` + `BeautifulSoup` | Playwright for SPAs (Workday, Phenom, etc.); httpx + BS4 for direct APIs and server-rendered HTML |
| Browser bypass | Playwright real-Chrome channel + stealth init | Some pages (DC Advisory, McKinsey) sit behind Cloudflare; bundled Chromium gets blocked |
| DB | Supabase (Postgres + REST) | Free tier, JS and Python clients, RLS for the frontend |
| Filter LLM | Ollama (`qwen2.5:7b`) running locally | Free, no API key, structured JSON output, sufficient quality for the problem |
| Email | Resend | Free tier (3k/month), verifiable domain, HTML emails |
| Dashboard | Next.js 14 + Tailwind on Vercel | Hobby tier free, auto-deploys on `git push`, ISR keeps pages fresh without rebuilds |
| Orchestration | Python `asyncio` | Async scrapers, async filter, single event loop |
| Scheduling | Windows Task Scheduler | Local, zero infra, `WakeToRun` + `StartWhenAvailable` cover edge cases |
| Package mgmt | `uv` (Python) + `npm` (frontend) | Faster than pip, good lockfile / standard for Next.js |

---

## Daily workflow

### Day 1 (empty DB)

1. **07:00**: Task Scheduler fires `run_scrape.ps1`
2. **07:00-07:20**: scrape of ~50 companies. Returns ~450 listings matching Madrid/London.
3. **07:20-09:40**: `ai_filter` processes the ~450 jobs in chunks of 25, calling Ollama. Each chunk takes ~5-10 min on CPU. Decisions persist to `jobs.ai_keep` / `jobs.ai_reason`.
4. **~09:40**: email arrives with Section A (234 kept today) + Section B (236 = 234 + a handful from earlier).

### Day N (≥2)

1. **07:00**: task fires
2. **07:00-07:20**: same scrape of the ~50 companies. **Crucial**: `upsert_jobs` diffs each URL against the DB. URLs already there don't count as "new".
3. **07:20-07:30**: the filter only processes the **delta** — typically 5-30 net-new jobs per day. Takes ~5-15 min.
4. **~07:30**: email with Section A (the new kept ones) + Section B (everything kept in the last 7 days).

Jobs are never re-filtered. One decision per (URL, model) and it sticks.

---

## AI filter — how it works

The system prompt contains:

1. **Fixed preamble**: model role + the *"when in doubt, KEEP"* rule + description of the output schema (strict JSON with `url`, `keep`, `reason` per job).
2. **Full content of `config/preferences.md`**: the candidate's actual criteria — STRONG KEEP / KEEP IF UNCERTAIN / DROP sections with concrete examples.

The user prompt is the JSON list of jobs to evaluate (title, company, location, department, URL).

### Batching

448 jobs in a single call saturates the model (~14k output tokens, CPU context suffers). It's split into **chunks of 25** processed serially. Each chunk is independent: if one fails, its 25 jobs pass through as `passthrough` (`is_real=False, keep=True`), the others continue.

### Structured output

Ollama supports `format=<json_schema>`, which **guarantees** the response validates against the schema. Without it, the model occasionally emits malformed JSON and you have to retry. With it: clean parsing every time.

### Persistence with retry escape hatch

Only real decisions (`is_real=True`) get saved to `ai_keep`/`ai_reason`. Passthrough rows stay with `ai_keep=NULL` — they still show up in Section B for 7 days, but it's visible they weren't actually filtered (for debugging) and could be retried in a future iteration.

---

## Public dashboard

A read-only Next.js 14 app deployed on Vercel that mirrors what's in Supabase, applying the same filter as the email digest (`is_active = true AND ai_keep IS NOT FALSE`).

**Live URL**: `https://<your-vercel-project>.vercel.app` (set this after your first deploy).

What it shows:
- All active listings, grouped by company, newest first
- Title (linking to the original posting), location, department, badge with job type
- The AI's one-line reason for each job ("Off-Cycle Internship at IB", "Compliance role at PE firm", etc.)
- A "Filter decision pending" badge for jobs with `ai_keep = NULL` (passthrough — model didn't emit a decision)

What it lets you do:
- Full-text search across title, company, location, department, AI reason
- Date filter chips: *Today* / *Last 7 days* / *All*
- Live "showing N of M" counter so it's clear when filters are narrowing the list

How it stays fresh: ISR with `revalidate = 600`. The page is regenerated at most every 10 minutes. After the 07:00 scrape finishes, the next visit (within 10 min) triggers a rebuild and the new jobs appear. No redeploy needed; no `git push` needed. The scraper writes to Supabase, the dashboard reads.

Setup detail: see [`job-tracker/frontend/README.md`](job-tracker/frontend/README.md) for the local dev flow and the Vercel deploy steps (Root Directory must be set to `job-tracker/frontend`; env vars are `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` — the **anon** key, never the service_role key).

---

## Setup (how to reproduce)

### 1. Clone and deps

```bash
git clone https://github.com/hugoragg/job-tracker.git
cd job-tracker/scraper
uv sync
uv run playwright install chromium --with-deps
# For DC Advisory / McKinsey you also need real Chrome:
uv run playwright install chrome
```

### 2. Supabase

Create a project on supabase.com (free tier), apply `job-tracker/supabase/schema.sql` in the SQL Editor.

### 3. Ollama

```bash
# Download from ollama.com/download
ollama pull qwen2.5:7b
```

(Needs ~5GB of RAM at runtime. For CPU-only inference, viable only with ≤8B models.)

### 4. Resend

Account on resend.com, verified domain or use `onboarding@resend.dev` for tests.

### 5. .env

```bash
cp scraper/.env.example scraper/.env
# Fill in: SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, EMAIL_FROM, EMAIL_TO
# Optional: OLLAMA_HOST (default http://localhost:11434), OLLAMA_MODEL (default qwen2.5:7b)
```

### 6. preferences.md

Edit `scraper/config/preferences.md` with your real criteria. Recommended structure:

- "About the candidate" — profile / seniority / geography
- "STRONG KEEP" — sectors and roles that are clearly on target
- "KEEP IF UNCERTAIN" — marginals / borderline / ambiguous
- "DROP" — what to explicitly discard
- "Hard rule" — *"when in doubt, KEEP"*

### 7. Smoke test

```bash
uv run python -m src.smoke_filter   # 5 example jobs, ~2 min
uv run python -m src.e2e_small      # 1 real company, full pipeline without email, ~3 min
uv run scrape                       # full Day 1: scrape + filter + real email, ~2h 30min
```

### 8. Daily schedule (Windows)

```powershell
$ScriptPath = '<absolute path>\job-tracker\scraper\run_scrape.ps1'
$Action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -Daily -At '07:00'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
              -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName 'JobTracker_Daily' -Action $Action -Trigger $Trigger `
                       -Settings $Settings -Principal $Principal -Force
```

---

## Verified scrapers

Per-company detail (with gotchas and specific notes) lives in **`CLAUDE.md`** — a table with ~50 entries and a note on how each particular case was solved (Cloudflare, HTTP/2 errors, slug parsing, etc.).

Aggregate summary:

| ATS | # companies | Approach |
|---|---|---|
| Workday | 5 | Direct `CXS` API, pagination via `appliedFacets` |
| Greenhouse | 1 | JSON API, simple |
| Generic Playwright | ~25 | Capture XHR JSON + scrape DOM with heuristics |
| Dedicated custom scraper | 15+ | One per gotcha (real-Chrome, ASP.NET Forms, MongoDB IDs, etc.) |
| Skipped (revisit) | 4 | Bain, BNP Paribas CIB, Arthur D. Little, Greenhill — non-trivial blockers |

---

## Limitations

### Of the AI filter

- **7B model on CPU is slow**: ~5-10 min per 25-job chunk. Day 1 takes ~2h 30min end-to-end. Acceptable because it's a nightly batch.
- **The model sometimes drops decisions**: on the real Day 1 (448 jobs), 62 jobs (~14%) didn't get a decision in the JSON output. They stay as passthrough (shown in email, not persisted). Lean-inclusive by design.
- **Compliance pattern**: with `qwen2.5:7b`, Compliance roles at banks/funds are occasionally dropped despite being in STRONG KEEP. Improved a lot with an explicit `preferences.md` but it's not 100% reliable. Larger models (`qwen2.5:14b`, `gpt-oss:20b`) should fix this at the cost of more latency.
- **No retry for passthroughs**: jobs with `ai_keep=NULL` aren't reprocessed in later runs. They expire from the 7-day window naturally.

### Of the scrapers

- **Hard Cloudflare**: Bain is fully blocked (even real-Chrome + stealth). Would need `cloudscraper` or `undetected-chromedriver`.
- **HTTP/2 errors**: BNP Paribas CIB aborts the connection even with HTTP/2 disabled. No current fix.
- **iCIMS sub-frame**: Arthur D. Little renders inside an iframe that's only served with specific Referer/cookie state. Pending.
- **Manual verification per company**: each new portal takes individual debugging. `src/debug_one.py` and `src/diagnose.py` help, but it isn't trivial.

### Of the scheduling

- **PC required on + user logged in**: `LogonType=Interactive`. Doesn't run with the session signed out or with the PC fully off/hibernating — only on next sign-in.
- **No automatic retry on transient errors**: if Ollama doesn't respond once, the filter passes everything through (fail-open) and the email goes out unfiltered. Improvable.
- **Supabase free tier pauses projects** after 7 days of inactivity. With the daily run this shouldn't happen, but you have to restore manually if it does.

### Of the filter quality

- **Heavily dependent on `preferences.md`**: with a vague file the model will be permissive. With one that's too restrictive, you'll miss marginals. Iterate on the file by watching real output.
- **No feedback loop**: if the model drops an interesting role, there's no way to flag it and retrain. A "no, this one was actually good" mechanism that auto-tunes prefs would be nice.

---

## Pending / ideas

- [x] **Public dashboard** — Next.js 14 on Vercel, live (see [Public dashboard](#public-dashboard)).
- [ ] **Retry passthroughs**: in each run, also pipe jobs with `ai_keep=NULL` through the filter (not only `all_new`).
- [ ] **Bain via cloudscraper**: try `curl_cffi` or `cloudscraper` for the Cloudflare bypass.
- [ ] **Feedback loop**: links in the email / buttons in the dashboard to mark "this one was good" or "this one wasn't" → auto-tune `preferences.md`.
- [ ] **Larger model**: try `qwen2.5:14b` (if RAM permits) or `gpt-oss:20b` quantized to fix the Compliance miss.
- [ ] **Personal state on the dashboard**: localStorage marks for *applied / interested / discarded* per job (no auth needed for single-user use).
- [ ] **Server-side filters per company**: some companies expose URL filters (location, role) I'm not using. Would cut down scrape time.
- [ ] **Exponential retries** for transient network errors in the Playwright scrapers.

---

## Commit history

If you peek at `git log`, development followed this progression:

1. **Initial scaffolding**: basic structure + 3 scrapers (Greenhouse, Lever, HTML).
2. **Per-company verification**: one company at a time, identify gotchas, write a custom scraper if the generic one doesn't cut it. ~50 companies, documented in `CLAUDE.md`.
3. **Email digest plan**: design of the daily pipeline with AI filter.
4. **Initial implementation with Anthropic SDK**: filter via the Claude Sonnet 4.6 API.
5. **Swap to local Ollama**: to avoid paying for inference. Same contract, different infra.
6. **Refactor to filter-only-on-delta**: the key insight — only filter URLs that are new vs yesterday, persist decisions. Cuts Day N from ~2h to ~10 min.
7. **End-to-end validation**: smoke test, e2e_small, full Day 1.
8. **Windows Task Scheduler setup**: `WakeToRun` + `StartWhenAvailable` + 4h execution limit so the run survives DST swings and missed schedules.
9. **Public dashboard**: Next.js 14 + Tailwind + Supabase anon read. Search, date chips, AI-reason display, "filter pending" badge. Deployed to Vercel — auto-revalidates every 10 min via ISR.

Each step committed separately, with a message explaining what and why.

---

## License

Personal project. No explicit license. If it inspires your own tracker, go for it — but `config/preferences.md` is mine and the scrapers are tuned for portals I care about; your mileage will vary.
