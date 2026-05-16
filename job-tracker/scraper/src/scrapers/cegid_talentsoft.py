"""Cegid TalentSoft career portal — ASP.NET WebForms.

Used by Credit Agricole CIB (`jobs.ca-cib.com`) and Amundi (`jobs.amundi.com`).
The careers URL (`/job/list-of-jobs.aspx`) returns the unfiltered worldwide
listing on a plain GET. Filtering by country requires:

  1. accepting the Didomi cookie banner (otherwise clicks are blocked),
  2. selecting the country in the GeographicalArea dropdown,
  3. clicking the "Start search" / "Lancer la recherche" submit button to
     trigger a form POST.

After that the page rerenders with `<a class="ts-offer-card__title-link">`
elements pointing at the filtered job detail pages.

The dropdown's element id varies slightly between portals (`ctl01` vs `ctl02`
in the WebForms control path) but the field name always ends in
`GeographicalAreaCollection`, and the country option values are shared
across instances (Spain=74).
"""
from __future__ import annotations

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_GEO_SELECT_SELECTOR = "select[name$='GeographicalAreaCollection']"
_SEARCH_BUTTON_SELECTOR = "input[name$='BT_recherche']"
# Cegid TalentSoft renders job cards either as `ts-offer-card` (tile view, the
# default on Credit Agricole) or `ts-offer-list-item` (list view, the default
# on Amundi). Either class always ends in `__title-link`.
_JOB_LINK_SELECTOR = "a.ts-offer-card__title-link, a.ts-offer-list-item__title-link"

# Country option values in the GeographicalArea dropdown. Shared across all
# Cegid TalentSoft instances we've seen.
_COUNTRY_VALUE_BY_FILTER: dict[str, str] = {
    "madrid": "74",   # Spain / Espagne
    "barcelona": "74",
    "spain": "74",
}


class CegidTalentSoftScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        country_value = _COUNTRY_VALUE_BY_FILTER.get(self.location_filter.lower())
        if not country_value:
            raise RuntimeError(
                f"CegidTalentSoftScraper: no country mapping for location_filter "
                f"'{self.location_filter}' — extend _COUNTRY_VALUE_BY_FILTER."
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            page = await context.new_page()
            try:
                await page.goto(self.company.careers_url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=12_000)
                except Exception:
                    pass

                # Dismiss Didomi cookie banner — it intercepts pointer events.
                try:
                    consent = await page.query_selector("#didomi-notice-agree-button")
                    if consent:
                        await consent.click(timeout=3_000)
                except Exception:
                    pass

                await page.select_option(_GEO_SELECT_SELECTOR, value=country_value)
                await page.click(_SEARCH_BUTTON_SELECTOR)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass

                cards: list[dict] = await page.eval_on_selector_all(
                    _JOB_LINK_SELECTOR,
                    """els => els.map(el => ({
                        href: el.href,
                        text: el.innerText.trim()
                    }))""",
                )
            finally:
                await context.close()
                await browser.close()

        jobs: list[Job] = []
        seen: set[str] = set()
        for c in cards:
            href = (c.get("href") or "").strip()
            text = (c.get("text") or "").strip()
            if not href or not text or href in seen:
                continue
            seen.add(href)
            jobs.append(Job(title=text, url=href, location=self.location_filter))
        return jobs
