# Job Tracker — Frontend

Next.js 14 read-only dashboard for the [Job Tracker](../../README.md) scraper. Renders active listings from Supabase grouped by company, with client-side search and date filters. Mirrors the email digest's Section B filter: shows jobs the AI kept (`ai_keep IS NULL OR ai_keep = true`).

## Stack

- Next.js 14 (App Router)
- React 18
- Tailwind CSS
- `@supabase/supabase-js`
- ISR (revalidates every 10 min)

## Local development

```bash
cd job-tracker/frontend
npm install

# Create .env.local with the ANON key (NOT the service key)
cp .env.example .env.local
# Then edit .env.local:
#   NEXT_PUBLIC_SUPABASE_URL=https://<your-project-ref>.supabase.co
#   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...   (Supabase dashboard -> Settings -> API -> anon public)

npm run dev
# Open http://localhost:3000
```

## Deploy to Vercel (free)

1. Sign up at [vercel.com](https://vercel.com) with your GitHub account.
2. **Import Project** → select the `job-tracker` repo.
3. In the import wizard:
   - **Root Directory**: `job-tracker/frontend` (use the "Edit" button next to root directory)
   - **Framework Preset**: Next.js (auto-detected)
   - **Build Command**: leave default (`next build`)
   - **Output Directory**: leave default (`.next`)
4. **Environment Variables** — add these (find values in Supabase dashboard → Settings → API):
   - `NEXT_PUBLIC_SUPABASE_URL` → `https://<project-ref>.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` → the `anon public` key (NOT the service_role key)
5. Click **Deploy**. After 1-2 min you get a URL like `job-tracker-xxx.vercel.app`. Share it.

Every push to `main` triggers a redeploy automatically.

## What the dashboard shows

- Active listings only (`is_active = true`)
- Excludes jobs the AI explicitly dropped (`ai_keep = false`)
- Includes jobs with no decision yet (`ai_keep IS NULL`, shown with "Filter decision pending" badge)
- Grouped by company, sorted alphabetically
- Client-side search across title, company, location, department, AI reason
- Date filter chips: Today / Last 7 days / All
- Each job shows: title (links to original posting), location, department, AI reason (the model's one-line rationale)

## Why anon key, not service key

The service key bypasses Row Level Security (RLS) and has full read/write access. It must never be exposed in the browser. The anon key is gated by RLS policies — currently `SELECT` is open to anon for `companies`, `jobs`, and `scrape_runs` (see `../supabase/schema.sql`). That's what makes the public dashboard safe to expose.
