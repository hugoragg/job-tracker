"""TalentLink (Cornerstone OnDemand / Oleeo) — `*.tal.net` ATSes.

Used by Evercore, Jefferies, Lazard, Nomura, and Parella Weiberg (and likely
others). The configured careers URL is a heavy JS-rendered candidate portal
under `/vx/lang-en-GB/.../candidate/jobboard/vacancy/<Y>/adv/`.

Older TalentLink tenants expose a clean **Atom feed** at:

    /vx/mobile-0/appcentre-1/brand-<X>/candidate/jobboard/vacancy/<Y>/feed

One `<entry>` per posting with `<title>` and a `<link rel="alternate" href>`
to the public detail page. No JS, no HTML parsing, no session tokens.

Newer Oleeo-hosted tenants (e.g. `nomuracampus.tal.net`) **do not** expose
the feed at any standard path. For those we fall back to rendering the
candidate portal with Playwright and reading the per-job anchors directly —
they have a stable shape `/.../candidate/so/pm/<a>/pl/<b>/opp/<id>-<slug>/<lang>`.

The scraper extracts `brand-<X>` and `vacancy/<Y>` from the configured
`careers_url`, builds the feed URL, parses the XML, and applies the
`location_filter` against each entry's title (TalentLink titles typically
embed the city, e.g. "EMEA – Madrid Off-Cycle Internship").
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_BRAND_RE = re.compile(r"/brand-([^/]+)/")
_VACANCY_RE = re.compile(r"/vacancy/(\d+)")
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
# Per-job URL shape on the candidate portal — `/candidate/so/pm/<a>/pl/<b>/
# opp/<id>-<slug>/<lang>`. Used by the HTML fallback to filter out the
# countless navigation links that share the same `tal.net` host.
_OPP_PATH_RE = re.compile(r"/candidate/so/pm/[^/]+/pl/[^/]+/opp/[^/?#]+", re.IGNORECASE)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TalentLinkScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        parsed = urlparse(self.company.careers_url)
        brand_match = _BRAND_RE.search(parsed.path)
        vacancy_match = _VACANCY_RE.search(parsed.path)
        if not brand_match or not vacancy_match:
            raise RuntimeError(
                f"TalentLinkScraper: cannot extract brand/vacancy from "
                f"{self.company.careers_url!r}"
            )
        brand = brand_match.group(1)
        vacancy = vacancy_match.group(1)
        feed_url = (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/vx/mobile-0/appcentre-1/brand-{brand}"
            f"/candidate/jobboard/vacancy/{vacancy}/feed"
        )

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "application/atom+xml"},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.get(feed_url)
            xml_text = resp.text if resp.status_code == 200 else None

        if xml_text is not None:
            return self._jobs_from_atom(xml_text)
        # Atom feed not available on this tenant — render the candidate portal
        # and pick up per-job anchors directly.
        return await self._jobs_from_html()

    def _jobs_from_atom(self, xml_text: str) -> list[Job]:
        root = ET.fromstring(xml_text)
        jobs: list[Job] = []
        seen: set[str] = set()
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title_el = entry.find(f"{_ATOM_NS}title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title or len(title) < 4:
                continue

            # Pick the alternate link (the public detail page), falling back
            # to <id> which is the same URL in TalentLink Atom feeds.
            href: str | None = None
            for link in entry.findall(f"{_ATOM_NS}link"):
                rel = link.get("rel") or ""
                if rel in ("", "alternate") and link.get("href"):
                    candidate = link.get("href") or ""
                    # The "instant=apply" variant skips the job detail page;
                    # prefer the canonical (no-query) form when both exist.
                    if "instant=apply" not in candidate:
                        href = candidate
                        break
                    href = href or candidate
            if not href:
                id_el = entry.find(f"{_ATOM_NS}id")
                href = (id_el.text or "").strip() if id_el is not None else ""
            if not href or href in seen:
                continue

            # Match location against title and URL slug.
            if not (self.matches_location(title) or self.matches_location(href)):
                continue

            seen.add(href)
            jobs.append(Job(title=title, url=href, location=self.location_filter))
        return jobs

    async def _jobs_from_html(self) -> list[Job]:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            page = await context.new_page()
            try:
                await page.goto(
                    self.company.careers_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                await asyncio.sleep(6)
                anchors: list[dict] = await page.eval_on_selector_all(
                    "a[href]",
                    """els => els.map(a => ({
                        href: a.href || '',
                        text: (a.innerText || '').trim()
                    })).filter(a => a.href && a.text)""",
                )
            finally:
                await context.close()
                await browser.close()

        jobs: list[Job] = []
        seen: set[str] = set()
        for a in anchors:
            href = a["href"]
            text = a["text"]
            if not _OPP_PATH_RE.search(href):
                continue
            if len(text) < 4:
                continue
            if not (self.matches_location(text) or self.matches_location(href)):
                continue
            if href in seen:
                continue
            seen.add(href)
            jobs.append(Job(title=text, url=href, location=self.location_filter))
        return jobs
