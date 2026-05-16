"""EY — Yello.co job board with HTML-in-JSON search endpoint.

The Yello careers board (`eyglobal.yello.co/job_boards/<id>`) exposes its
search at `/job_boards/<id>/search?query=&filters=<ids>&page_number=N`, which
returns `{"html": "<li class='search-results__item'>...</li>"}`. The
`filters=` value is a comma-joined list of office IDs (checkbox values in the
UI). For Madrid, EY currently uses two offices: **ESP-Madrid** (`139513`)
and **ESP-Madrid Campus** (`180711`).

The scraper extracts the board ID from `careers_url`, applies the hardcoded
Madrid filter IDs, walks pagination until a page returns 0 items, and parses
the embedded HTML for `(title, url)`.

Note: results may include jobs whose primary title city is non-Madrid (e.g.
"Auditor/a Junior Asturias - Septiembre 2025") — Yello returns any posting
that has Madrid as *one of its* offices, so the title city is just the lead
location. We pass these through because the user filter (`Madrid`) is
office-based, not title-based.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import urlparse, urljoin

import httpx

from ..models import Job
from .base import BaseScraper

_MADRID_FILTER_IDS = "139513,180711"  # ESP-Madrid + ESP-Madrid Campus
_MAX_PAGES = 20
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TITLE_LINK_RE = re.compile(
    r'class="search-results__req_title"[^>]*href="([^"]+)"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_BOARD_ID_RE = re.compile(r"/job_boards/([^/?#]+)")


class EyScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        parsed = urlparse(self.company.careers_url)
        m = _BOARD_ID_RE.search(parsed.path)
        if not m:
            raise RuntimeError(
                f"EyScraper: cannot extract board id from {self.company.careers_url!r}"
            )
        board_id = m.group(1)
        base = f"{parsed.scheme}://{parsed.netloc}"

        all_jobs: list[Job] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for page_idx in range(1, _MAX_PAGES + 1):
                url = (
                    f"{base}/job_boards/{board_id}/search"
                    f"?query=&filters={_MADRID_FILTER_IDS}&page_number={page_idx}"
                )
                try:
                    resp = await client.get(url)
                except httpx.HTTPError:
                    break
                if resp.status_code != 200:
                    break

                try:
                    data = resp.json()
                except ValueError:
                    break
                html_chunk = data.get("html") or ""
                if not html_chunk:
                    break

                items = _TITLE_LINK_RE.findall(html_chunk)
                if not items:
                    break

                new_count = 0
                for href, title_raw in items:
                    title = _html.unescape(title_raw).strip()
                    if not title or len(title) < 4:
                        continue
                    absolute = urljoin(base, href)
                    if absolute in seen_urls:
                        continue
                    seen_urls.add(absolute)
                    all_jobs.append(Job(title=title, url=absolute, location=self.location_filter))
                    new_count += 1

                if new_count == 0:
                    break

        return all_jobs
