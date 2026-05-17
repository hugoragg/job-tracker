"""End-to-end pipeline preview — DB read -> AI filter -> email HTML render.

Pulls a sample of real jobs from Supabase, runs them through the filter, and
writes the rendered email HTML to a local file (does NOT send via Resend).
Use this to validate the new pipeline without burning a real digest send.

Run: uv run python -m src.e2e_preview [sample_size]
"""
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .ai_filter import filter_jobs
from .db import get_client
from .email_digest import _render_section
from .models import Job

load_dotenv()

_OUTPUT_HTML = Path(__file__).parent.parent / "preview_digest.html"


def _fetch_sample(client, n: int) -> list[tuple[str, Job]]:
    """Fetch the most-recent `n` active jobs (any date), joined with company name."""
    result = (
        client.table("jobs")
        .select("*, companies(name)")
        .eq("is_active", True)
        .order("first_seen_at", desc=True)
        .limit(n)
        .execute()
    )
    out: list[tuple[str, Job]] = []
    for row in result.data or []:
        company = (row.get("companies") or {}).get("name") or "Unknown"
        job = Job(
            title=row["title"],
            url=row["url"],
            location=row.get("location"),
            department=row.get("department"),
            job_type=row.get("job_type"),
            description=row.get("description"),
            external_id=row.get("external_id"),
        )
        out.append((company, job))
    return out


async def main() -> None:
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    print(f"E2E preview: fetching {sample_size} jobs from DB...")
    db = get_client()
    sample = _fetch_sample(db, sample_size)
    print(f"  Got {len(sample)} jobs across {len(set(c for c, _ in sample))} companies")

    print(f"\nRunning AI filter ({sample_size} jobs through Ollama)...")
    t0 = time.monotonic()
    filtered = await filter_jobs(sample)
    elapsed = time.monotonic() - t0
    print(f"  Filtered in {elapsed:.1f}s: {len(filtered)}/{len(sample)} kept")

    # Show what was kept vs dropped
    kept_urls = {j.url for _, j in filtered}
    print("\nDecisions:")
    for company, job in sample:
        flag = "[KEEP]" if job.url in kept_urls else "[DROP]"
        print(f"  {flag} {company:30s} {job.title[:80]}")

    # Render the email HTML — simulate Section A = first 3 as "new today",
    # Section B = full filtered list (the real pipeline does this from
    # actual day-zero diff, but for preview we just split).
    print("\nRendering email HTML...")
    section_a = filtered[:3]  # mock "new today"
    section_b = filtered
    section_a_html = _render_section("Nuevos hoy", section_a)
    section_b_html = _render_section("Últimos 7 días", section_b)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Digest preview</title></head>
<body style='background:#f9fafb;padding:40px'>
<div style='font-family:sans-serif;max-width:640px;margin:0 auto;background:white;padding:24px;border-radius:8px'>
    <h2 style='border-bottom:1px solid #e5e7eb;padding-bottom:8px'>Job Tracker (PREVIEW)</h2>
    {section_a_html}
    {section_b_html}
    <hr style='margin-top:24px;border:none;border-top:1px solid #e5e7eb'>
    <p style='color:#9ca3af;font-size:12px'>Filtrado por IA según config/preferences.md. Madrid (+ London cuando aplica).</p>
</div>
</body></html>"""
    _OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"  Written to: {_OUTPUT_HTML}")
    print(f"\nOpen the file in a browser to preview the email.")


if __name__ == "__main__":
    asyncio.run(main())
