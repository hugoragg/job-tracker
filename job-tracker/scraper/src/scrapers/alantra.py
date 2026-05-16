"""Alantra careers scraper.

Alantra's careers page (https://www.alantra.com/careers/apply/) is a WordPress
site whose listings are loaded via a custom admin-ajax action `careers_filter`.
Each job card has no individual detail URL — clicking the card opens a contact
form popup — so we synthesize a stable URL from the careers page + a slug of
the title.

Endpoint: POST https://www.alantra.com/wp-admin/admin-ajax.php
Body:     action=careers_filter&page=N&location=<display>&division=&words=

The `location` value is the human-readable label from the dropdown (e.g.
"Spain - Madrid"); other values are rejected with an empty payload.
"""
from __future__ import annotations

import re
from html import unescape

import httpx

from ..models import Job
from .base import BaseScraper

_AJAX_URL = "https://www.alantra.com/wp-admin/admin-ajax.php"
_AJAX_ACTION = "careers_filter"

# Maps our internal location filter to Alantra's dropdown value.
_LOCATION_LABEL: dict[str, str] = {
    "madrid": "Spain - Madrid",
    "barcelona": "Spain - Madrid",  # Alantra has no Barcelona option
    "london": "UK - London",
    "new york": "USA - New York",
    "athens": "Greece - Athens",
    "stockholm": "Sweden - Stockholm",
    "milan": "Italy - Milan",
    "frankfurt": "Germany - Frankfurt",
}

_TITLE_RE = re.compile(r'class="news-grid__items_title"[^>]*>([^<]+)</p>', re.IGNORECASE)
_LOCATION_RE = re.compile(r'class="news-grid__items_publish_date"[^>]*>([^<]+)</div>', re.IGNORECASE)
_DEPT_RE = re.compile(r'class="news-grid__items_cat"[^>]*>([^<]+)</div>', re.IGNORECASE)
# Each job is wrapped in <li class="...careers__list__item...">...</li>
_CARD_RE = re.compile(
    r'<li[^>]*class="[^"]*careers__list__item[^"]*"[^>]*>(.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:80]


class AlantraScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        location_value = _LOCATION_LABEL.get(self.location_filter.lower(), "")

        jobs: list[Job] = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                resp = await client.post(
                    _AJAX_URL,
                    data={
                        "action": _AJAX_ACTION,
                        "page": page,
                        "location": location_value,
                        "division": "",
                        "words": "",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                html = payload.get("careers", "") or ""
                cards = _CARD_RE.findall(html)
                if not cards:
                    break

                added_this_page = 0
                for card in cards:
                    title_m = _TITLE_RE.search(card)
                    if not title_m:
                        continue
                    title = unescape(title_m.group(1)).strip()
                    if not title:
                        continue

                    loc_m = _LOCATION_RE.search(card)
                    location = unescape(loc_m.group(1)).strip() if loc_m else None

                    dept_m = _DEPT_RE.search(card)
                    department = unescape(dept_m.group(1)).strip() if dept_m else None

                    # Filter check (the API also filters, but title-based filtering
                    # via _LOCATION_LABEL is approximate for fallbacks).
                    if location and not self.matches_location(location):
                        continue

                    jobs.append(
                        Job(
                            title=title,
                            url=f"{self.company.careers_url}#{_slugify(title)}",
                            location=location,
                            department=department,
                        )
                    )
                    added_this_page += 1

                if added_this_page == 0:
                    break
                page += 1
                if page > 20:  # safety: Alantra never has >20 pages
                    break

        return jobs
