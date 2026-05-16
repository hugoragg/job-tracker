"""Acciona careers scraper.

Acciona's single careers page hosts jobs for all its business lines (Acciona
Construcción, Acciona Corporación, Bestinver, etc.) The page embeds the full
job catalogue (currently ~676 items) as a JSON string in the `jobs` attribute
of an `<a-mo-oferta-v2>` web component, so a single page load is enough to
satisfy any business-line filter.

A company config sets ``acciona_division`` to the `divisionID` string the page
uses (e.g. ``"Bestinver_Business_Line"`` or ``"Corporación_Business_Line"``);
jobs whose ``divisionID`` matches and whose ``primaryLocation`` passes
``matches_location`` are returned.
"""
from __future__ import annotations

import json

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_CAREERS_URL = "https://www.acciona.com/our-purpose/work-with-us/job-offers"
_COOKIE_BUTTON_SELECTOR = "#CookieModal-AcceptAll-Button"
_JOBS_SELECTOR = "a-mo-oferta-v2"


class AccionaScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        division = self.company.acciona_division
        if not division:
            raise ValueError(
                f"AccionaScraper requires acciona_division to be set on company "
                f"'{self.company.name}'"
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
                await page.goto(
                    self.company.careers_url or _CAREERS_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                # Cookie banner must be dismissed before the jobs widget hydrates.
                try:
                    await page.evaluate(
                        f"document.querySelector({_COOKIE_BUTTON_SELECTOR!r})?.click()"
                    )
                except Exception:
                    pass

                # Wait for the jobs attribute to be populated.
                try:
                    await page.wait_for_function(
                        f"document.querySelector({_JOBS_SELECTOR!r})?.getAttribute('jobs')",
                        timeout=20_000,
                    )
                except Exception:
                    pass

                jobs_attr = await page.evaluate(
                    f"document.querySelector({_JOBS_SELECTOR!r})?.getAttribute('jobs')"
                )
            finally:
                await context.close()
                await browser.close()

        if not jobs_attr:
            return []

        try:
            raw_jobs = json.loads(jobs_attr)
        except json.JSONDecodeError:
            return []

        jobs: list[Job] = []
        for raw in raw_jobs:
            if raw.get("divisionID") != division:
                continue
            location = raw.get("primaryLocation") or ""
            if not self.matches_location(location):
                continue

            title = (raw.get("jobPostingTitle") or "").strip()
            if not title:
                continue

            url_path = raw.get("url") or f"/our-purpose/work-with-us/job-detail?id={raw.get('id')}"
            url = url_path if url_path.startswith("http") else f"https://www.acciona.com{url_path}"

            jobs.append(
                Job(
                    title=title,
                    url=url,
                    location=location or None,
                    department=raw.get("divisionTitle") or None,
                    external_id=str(raw.get("id") or raw.get("jobRequisitionId") or ""),
                )
            )

        return jobs
