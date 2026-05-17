"""Smoke test for ai_filter — 5 hand-picked jobs covering keep/drop/marginal cases.

Run: uv run python -m src.smoke_filter
"""
import asyncio
import time

from dotenv import load_dotenv

from .ai_filter import filter_jobs
from .models import Job

load_dotenv()

SAMPLE: list[tuple[str, Job]] = [
    # OBVIOUS KEEP — explicit early careers IB role, Madrid
    ("Santander CIB", Job(
        title="2026 Off-Cycle Internship — M&A Industrials",
        url="https://example.com/jobs/1",
        location="Madrid, Spain",
        department="Investment Banking",
    )),
    # OBVIOUS KEEP — PE/VC analyst
    ("Permira", Job(
        title="Private Equity Associate, Compliance",
        url="https://example.com/jobs/2",
        location="Madrid",
        department="Compliance",
    )),
    # OBVIOUS DROP — retail floor staff, unrelated industry
    ("Mango", Job(
        title="Dependiente/a Tienda",
        url="https://example.com/jobs/3",
        location="Madrid",
        department="Retail",
    )),
    # OBVIOUS DROP — senior C-level
    ("Random Co", Job(
        title="Chief Financial Officer — 20+ years experience required",
        url="https://example.com/jobs/4",
        location="Madrid",
        department="Executive",
    )),
    # MARGINAL — software engineering at finance firm. Should KEEP under "when in doubt".
    ("BlackRock", Job(
        title="Software Engineering Intern — Aladdin Platform",
        url="https://example.com/jobs/5",
        location="London",
        department="Technology",
    )),
]


async def main() -> None:
    print(f"Smoke test: {len(SAMPLE)} jobs")
    print("Expecting: keep #1, #2, #5; drop #3, #4. Marginal #5 must be KEPT (when-in-doubt rule).")
    print()

    t0 = time.monotonic()
    kept = await filter_jobs(SAMPLE)
    elapsed = time.monotonic() - t0

    print(f"\nElapsed: {elapsed:.1f}s")
    print(f"Kept {len(kept)}/{len(SAMPLE)}:")
    for company, job in kept:
        print(f"  [KEEP] {company}: {job.title}")
    dropped = [(c, j) for (c, j) in SAMPLE if not any(kj.url == j.url for _, kj in kept)]
    print(f"Dropped {len(dropped)}:")
    for company, job in dropped:
        print(f"  [DROP] {company}: {job.title}")


if __name__ == "__main__":
    asyncio.run(main())
