"""Standalone diagnostic — runs each company scraper and reports counts/errors.

Does NOT touch the database or send emails.
Run: uv run python -m src.diagnose [company_name_substring]
"""
import asyncio
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .main import _resolve_scraper
from .models import ScraperConfig

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"


async def main() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = ScraperConfig(**raw)

    filter_arg = sys.argv[1].lower() if len(sys.argv) > 1 else None

    results = []
    for company in config.companies:
        if filter_arg and filter_arg not in company.name.lower():
            continue
        scraper_cls = _resolve_scraper(company)
        if not scraper_cls:
            results.append((company.name, company.ats, -1, f"Unknown ATS '{company.ats}'"))
            continue
        try:
            scraper = scraper_cls(company, config.default_location_filter)
            jobs = await scraper.fetch_jobs()
            results.append((company.name, company.ats, len(jobs), None))
            print(f"OK    [{company.ats:11s}] {company.name:30s} -> {len(jobs)} jobs")
            for j in jobs[:3]:
                print(f"        - {j.title[:70]}  {j.url[:80]}")
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            results.append((company.name, company.ats, -1, err))
            print(f"FAIL  [{company.ats:11s}] {company.name:30s} -> {err[:200]}")

    print("\n" + "=" * 80)
    ok = sum(1 for r in results if r[2] >= 0)
    nonzero = sum(1 for r in results if r[2] > 0)
    failed = sum(1 for r in results if r[2] < 0)
    total_jobs = sum(r[2] for r in results if r[2] > 0)
    print(f"Tested: {len(results)} | OK: {ok} | with jobs: {nonzero} | failed: {failed} | total jobs: {total_jobs}")


if __name__ == "__main__":
    asyncio.run(main())
