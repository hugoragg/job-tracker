"""BDO Spain careers scraper.

BDO uses Epreselec (an Adevinta/InfoJobs ATS). The careers page is an ASP.NET
WebForms app whose Provincia filter requires a `__doPostBack` form submission;
individual postings open via `__doPostBack` rather than direct URLs. We drive
the form in Playwright and pull jobs out of the post-submit DOM, building
permalink URLs of the form ``?idOferta=<id>`` (verified to load the detail).
"""
from __future__ import annotations

import re

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

# Provincia drop-down value for Madrid (Epreselec's INE-style province code)
_MADRID_VALUE = "28"
_LOCATION_TO_VALUE: dict[str, str] = {
    "madrid": "28",
    "barcelona": "8",
    "valencia": "46",
    "alicante": "3",
    "malaga": "29",
    "zaragoza": "50",
    "las palmas": "35",
}

_TITLE_CLEAN_RE = re.compile(r"\s+")


class BdoSpainScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        provincia_value = _LOCATION_TO_VALUE.get(self.location_filter.lower(), _MADRID_VALUE)

        jobs: list[Job] = []

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
            page = await context.new_page()
            try:
                await page.goto(
                    self.company.careers_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                # Dismiss the cookie banner — without it the underlying form
                # elements stay covered and clicks don't reach them.
                try:
                    await page.click('text="Aceptar"', timeout=5_000)
                except Exception:
                    pass

                try:
                    await page.select_option(
                        "#ctl00_CPH_Body_ddlCities", value=provincia_value, timeout=10_000
                    )
                except Exception:
                    pass

                try:
                    await page.click("#ctl00_CPH_Body_bBuscar", timeout=10_000)
                except Exception:
                    pass

                # The results render via an ASP.NET partial postback. Wait for
                # the repeater rows to appear (or time out — empty result is
                # also a valid outcome).
                try:
                    await page.wait_for_selector(
                        "a[id*=lbMostrarOferta]", timeout=15_000
                    )
                except Exception:
                    pass

                raw_rows: list[dict] = await page.eval_on_selector_all(
                    "a[id*=lbMostrarOferta]",
                    """els => els.map(el => ({
                        text: (el.textContent || '').trim(),
                        idOferta: el.getAttribute('data_idoferta') || null
                    }))""",
                )
            finally:
                await context.close()
                await browser.close()

        base_origin = "https://bdo.epreselec.com"
        for row in raw_rows:
            title = _TITLE_CLEAN_RE.sub(" ", row.get("text") or "").strip()
            id_oferta = row.get("idOferta")
            if not title or not id_oferta:
                continue
            jobs.append(
                Job(
                    title=title,
                    url=f"{base_origin}/Ofertas/Ofertas.aspx?idOferta={id_oferta}",
                    location=self.location_filter,
                    external_id=str(id_oferta),
                )
            )

        return jobs
