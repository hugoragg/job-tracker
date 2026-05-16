"""SAP SuccessFactors career portal — paginated via `startrow` query param.

Used by CaixaBank (`caixabankcareers.com`), Deloitte (`empleo.es.deloitte.com`),
and likely KMPG / Santander AM. Pages are server-rendered HTML, so we use
httpx + BeautifulSoup instead of Playwright — much faster than 12 Playwright
launches.

Page size differs per portal (CaixaBank uses 10, Deloitte uses 25). The first
page tells us the actual size by counting unique `/job/.../<id>/` links; we
then iterate `startrow=N, 2N, ...` until a page returns no new results.

Jobs whose URL or title clearly references a *different* Spanish city
(e.g. `/job/Alicante-...`) are rejected by `BaseScraper.matches_location`,
which lets us point the scraper at a country-wide `locationsearch=spain` URL
and still get only Madrid jobs out the other end.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode, urljoin, urlparse, urlunparse, parse_qsl

import httpx
from bs4 import BeautifulSoup

from ..models import Job
from .base import BaseScraper

_MAX_PAGES = 50  # safety cap (1,250 listings with pageSize=25)
_JOB_ID_TAIL_RE = re.compile(r"/\d{6,}/?$")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class SapSuccessFactorsScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        base = self.company.careers_url
        parsed = urlparse(base)
        carry_params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() != "startrow"]

        all_jobs: list[Job] = []
        seen_urls: set[str] = set()
        page_size: int | None = None

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-GB,en;q=0.9,es;q=0.8"},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for page_idx in range(_MAX_PAGES):
                startrow = page_idx * (page_size or 25)
                page_params = carry_params + [("startrow", str(startrow))]
                page_url = urlunparse(parsed._replace(query=urlencode(page_params)))

                try:
                    resp = await client.get(page_url)
                except httpx.HTTPError:
                    break
                if resp.status_code != 200:
                    break

                cards = _extract_cards(resp.text, base)
                if page_size is None:
                    page_size = len(cards) or 25

                if not cards:
                    break

                added_this_page = False
                for title, url in cards:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    if not (self.matches_location(url) or self.matches_location(title)):
                        continue
                    all_jobs.append(Job(title=title, url=url, location=self.location_filter))
                    added_this_page = True

                _ = added_this_page  # kept for readability; we only break on raw-empty page

                if len(cards) < page_size:
                    break  # last page

        return all_jobs


def _extract_cards(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return (title, absolute_url) for every unique job posting on the page.

    SuccessFactors renders each card with multiple `<a href="/job/...">`
    tags (title + view-more + apply); we dedupe by URL and prefer the first
    anchor whose text looks like a real title (length > 4).
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, str] = {}
    for a in soup.select('a[href*="/job/"]'):
        href = (a.get("href") or "").strip()
        text = a.get_text(strip=True)
        if not text or len(text) < 4:
            continue
        if not _JOB_ID_TAIL_RE.search(href.rstrip("/") + "/"):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen[absolute] = text
    return [(title, url) for url, title in seen.items()]
