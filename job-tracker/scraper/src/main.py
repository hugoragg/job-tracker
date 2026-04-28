import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from dotenv import load_dotenv

from .db import finish_scrape_run, get_client, get_or_create_company, start_scrape_run, upsert_jobs
from .email_digest import send_digest
from .models import CompanyConfig, Job, ScraperConfig
from .scrapers import GreenhouseScraper, HtmlScraper, LeverScraper, PlaywrightScraper

if TYPE_CHECKING:
    from .scrapers.base import BaseScraper

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"

_SCRAPER_MAP: dict[str, type["BaseScraper"]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "html": HtmlScraper,
    "playwright": PlaywrightScraper,
}


async def _scrape_company(
    company: CompanyConfig,
    default_location_filter: str,
) -> tuple[list[Job], str | None]:
    scraper_cls = _SCRAPER_MAP.get(company.ats)
    if not scraper_cls:
        return [], f"Unknown ATS '{company.ats}'"

    try:
        scraper = scraper_cls(company, default_location_filter)
        jobs = await scraper.fetch_jobs()
        print(f"  [{company.name}] fetched {len(jobs)} matching job(s)")
        return jobs, None
    except Exception as exc:
        return [], str(exc)


async def run() -> None:
    with open(_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    config = ScraperConfig(**raw)

    db = get_client()
    run_id = start_scrape_run(db)

    all_new: list[tuple[str, Job]] = []
    errors: list[dict] = []

    for company in config.companies:
        print(f"Scraping {company.name} ({company.ats})…")
        jobs, error = await _scrape_company(company, config.default_location_filter)

        if error:
            print(f"  [ERROR] {company.name}: {error}")
            errors.append({"company": company.name, "error": error})
            continue

        company_id = get_or_create_company(db, company.name, company.careers_url, company.ats)
        new_jobs = upsert_jobs(db, company_id, jobs)
        print(f"  [{company.name}] {len(new_jobs)} new job(s) inserted")

        for job in new_jobs:
            all_new.append((company.name, job))

    send_digest(all_new)
    finish_scrape_run(db, run_id, len(all_new), errors)
    print(f"\nDone — {len(all_new)} new job(s) found across {len(config.companies)} companies.")


def main() -> None:
    asyncio.run(run())
