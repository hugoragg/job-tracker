"""Morgan Stanley — public marketing page backed by a clean JSON endpoint.

The careers page (`morganstanley.com/careers/career-opportunities-search?
opportunity=<X>`) is a React SPA that fetches opportunities from:

    https://www.morganstanley.com/web/career_services/webapp/service/
    careerservice/resultset.json?opportunity=<X>&lang=EN&location=

Each result is `{jobTitle, location, country, city, region, jobNumber, url, ...}`
where `url` is the actual TalentLink apply URL (`morganstanley.tal.net/vx/
candidate/so/pm/1/pl/1/opp/<id>`).

Two reasons we don't use the generic `PlaywrightScraper`:
  1. Morgan Stanley's CDN aborts vanilla Chromium with HTTP/2 protocol errors
     (same as McKinsey). Would need the real-Chrome stealth dance just to load
     the page.
  2. Even if rendered, the result cards have no per-job anchor at top level —
     each "APPLY NOW" link opens in a new tab via JS routing.

The JSON endpoint requires no auth and no JS. We just need the `opportunity`
query param from the yaml URL (`sg` for Students & Graduates, `ep` for
Experienced Professionals).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from ..models import Job
from .base import BaseScraper

_API_TEMPLATE = (
    "https://www.morganstanley.com/web/career_services/webapp/service/"
    "careerservice/resultset.json?opportunity={opportunity}&lang=EN&location="
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class MorganStanleyScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        parsed = urlparse(self.company.careers_url)
        opp_vals = parse_qs(parsed.query).get("opportunity") or ["sg"]
        opportunity = opp_vals[0]

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.get(_API_TEMPLATE.format(opportunity=opportunity))
            resp.raise_for_status()
            data = resp.json()

        result_set = data.get("resultSet") or []
        jobs: list[Job] = []
        for j in result_set:
            title = (j.get("jobTitle") or "").strip()
            url = (j.get("url") or "").strip()
            if not title or not url:
                continue
            location = (j.get("location") or "").strip()
            country = (j.get("country") or "").strip()
            city = (j.get("city") or "").strip()
            location_text = " | ".join(s for s in (location, city, country) if s)
            if not self.matches_location(location_text):
                continue
            jobs.append(
                Job(title=title, url=url, location=location or city or None)
            )
        return jobs
