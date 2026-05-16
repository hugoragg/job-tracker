"""UBS — TGnewUI portal with no usable server-side location filter.

The careers URL (`jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?...&LinkID=15232`)
is the Early Careers / Off-Cycle Internships preset. The page exposes a
`#locationSearch=` hash fragment, but it's purely client-side cosmetic — both
`locationSearch=Madrid` and `locationSearch=London` return the same 38-job
global listing.

Cards either include the city in the title (`"2026 Off-Cycle Internship -
Global Banking - Paris"`) or omit it entirely (e.g. `"Intern in Asset
Servicing (6 months)"`, location not exposed in DOM). For ambiguous cards
we have no signal, so the safest behaviour is to require the location filter
to match the **title** explicitly.

URL routing: TGnewUI uses query-string routing — every job link shares the
base path `/TGnewUI/Search/home/HomeWithPreLoad` and only differs in
`?PageType=JobDetails&jobid=<N>`.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_NAV_TIMEOUT_MS = 60_000
_NETWORK_IDLE_TIMEOUT_MS = 12_000
_POST_LOAD_WAIT_S = 4.0
_MAX_SCROLLS = 4
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class UbsScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            page = await ctx.new_page()
            try:
                await page.goto(
                    self.company.careers_url,
                    wait_until="domcontentloaded",
                    timeout=_NAV_TIMEOUT_MS,
                )
            except Exception:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=_NETWORK_IDLE_TIMEOUT_MS)
            except Exception:
                pass
            await asyncio.sleep(_POST_LOAD_WAIT_S)
            for _ in range(_MAX_SCROLLS):
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    break
                await asyncio.sleep(0.7)

            raw: list[dict] = await page.eval_on_selector_all(
                'a[href*="PageType=JobDetails"]',
                """els => els.map(el => ({
                    href: el.href,
                    text: el.innerText.trim(),
                }))""",
            )
            await ctx.close()
            await browser.close()

        jobs: list[Job] = []
        seen: set[str] = set()
        base_host = urlparse(self.company.careers_url).hostname or ""
        for item in raw:
            href = item.get("href") or ""
            title = (item.get("text") or "").strip()
            if not href or not title or len(title) < 5:
                continue
            if urlparse(href).hostname not in (base_host, ""):
                continue
            if not self.matches_location(title):
                continue
            if href in seen:
                continue
            seen.add(href)
            jobs.append(Job(title=title, url=href))
        return jobs
