"""PwC Spain — campus careers spread across four marketing URLs.

PwC's Spanish careers site (`www.pwc.es/es/carrera-profesional/...`) splits
its student / intern / new-joiner postings across four URLs that all differ
only by the `wdprog` (program-type) and `wdgrade` query params:

  1. student-job-search ? wdprog=b78cd3...&wdgrade=1840265
  2. student-job-search ? wdprog=181d27...&wdgrade=1840265
  3. becas-y-practicas-profesionales ? wdprog=3205d7...&wdgrade=12669415
  4. student-job-search ? wdprog=3205d7...&wdgrade=1840265

Each page server-renders a small table with one row per posting (title,
location, line of service, specialism, …, Apply). The "Apply" link points
to the real posting on PwC's Workday tenant
(`pwc.wd3.myworkdayjobs.com/Global_Campus_Careers/job/...`).

We render each URL in Playwright, read the table rows, filter by
`matches_location` against the location column + title, and use the Apply
href as the canonical job URL. Deduped across URLs by apply URL.
"""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_URLS = [
    "https://www.pwc.es/es/carrera-profesional/student-job-search/results.html"
    "?wdcountry=ESP&wdjobsite=Global_Campus_Careers"
    "&wdprog=b78cd3deaf49102755292a6430e60000&wdgrade=1840265",
    "https://www.pwc.es/es/carrera-profesional/student-job-search/results.html"
    "?wdcountry=ESP&wdjobsite=Global_Campus_Careers"
    "&wdprog=181d27aa0ec21027504f21f399fe0000&wdgrade=1840265",
    "https://www.pwc.es/es/carrera-profesional/becas-y-practicas-profesionales/results.html"
    "?wdcountry=ESP&wdjobsite=Global_Campus_Careers"
    "&wdprog=3205d7f4e6a110274f8dbea37a590000&wdgrade=12669415",
    "https://www.pwc.es/es/carrera-profesional/student-job-search/results.html"
    "?wdcountry=ESP&wdjobsite=Global_Campus_Careers"
    "&wdprog=3205d7f4e6a110274f8dbea37a590000&wdgrade=1840265",
]

# JS extraction — walks every result-table row and reads cell text + the
# Apply-link href. The marketing page uses generic <table><tr><td> markup so
# we don't need brittle class selectors.
_EXTRACT_JS = r"""
() => {
    const out = [];
    for (const row of document.querySelectorAll('table tr')) {
        const cells = Array.from(row.querySelectorAll('td')).map(c => (c.innerText || '').trim());
        if (cells.length < 2 || !cells[0]) continue;
        const title = cells[0];
        const location = cells[1] || '';
        const department = cells[2] || '';
        // The Apply <a> is in the row's last cell.
        const a = row.querySelector('a[href]');
        const url = a ? a.href : '';
        if (!url) continue;
        out.push({title, location, department, url});
    }
    return out;
}
"""


class PwcSpainScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
            )
            try:
                for url in _URLS:
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                        # The result table is server-rendered but program-script
                        # tweaks may still mutate the DOM after load — give it
                        # a few seconds.
                        await asyncio.sleep(6)
                        rows = await page.evaluate(_EXTRACT_JS)
                    finally:
                        await page.close()

                    for row in rows:
                        title = row.get("title", "").strip()
                        location = row.get("location", "").strip()
                        apply_url = row.get("url", "").strip()
                        if not title or not apply_url:
                            continue
                        if apply_url in seen:
                            continue
                        if not (self.matches_location(location) or self.matches_location(title)):
                            continue
                        seen.add(apply_url)
                        jobs.append(
                            Job(
                                title=title,
                                url=apply_url,
                                location=location or None,
                                department=row.get("department") or None,
                            )
                        )
            finally:
                await context.close()
                await browser.close()
        return jobs
