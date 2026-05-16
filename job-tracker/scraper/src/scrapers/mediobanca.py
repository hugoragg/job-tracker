"""Mediobanca — Intervieweb ATS, accessed via JSON endpoint.

The marketing careers page (`mediobanca.com/en/work-with-us/open-positions.html`)
embeds an Intervieweb widget that fetches the full job list from:

    https://mediobanca.intervieweb.it/annunci.php?lang=it&d=mediobanca.com
        &k=<api-key>&format=json_en

This returns a JSON array with one entry per posting (title, slug, id, city,
location, etc.). The generic `PlaywrightScraper` does capture XHR responses
but its location-matching heuristic relies on URLs in the JSON body — and the
Intervieweb payload has slugs, not full URLs — so jobs slip through.

We bypass Playwright entirely: hit the JSON endpoint with httpx, filter by
location, and construct per-job URLs as `https://mediobanca.intervieweb.it/
jobs/<slug>/en/` (verified — returns the full ~250KB English detail page,
while shorter paths redirect or 404).
"""
from __future__ import annotations

import httpx

from ..models import Job
from .base import BaseScraper

_API_URL = (
    "https://mediobanca.intervieweb.it/annunci.php"
    "?lang=it&d=mediobanca.com&k=5d5fe2bade7b20b3eeff504912a9afa0&format=json_en"
)
_JOB_URL_TEMPLATE = "https://mediobanca.intervieweb.it/jobs/{slug}/en/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class MediobancaScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.get(_API_URL)
            resp.raise_for_status()
            postings = resp.json()

        jobs: list[Job] = []
        for p in postings:
            slug = (p.get("slug") or "").strip()
            title = (p.get("title") or "").strip()
            if not slug or not title:
                continue
            # Intervieweb's `location` is the most specific descriptor (e.g.
            # "City of Westminster London Boro"); `city` is the normalized
            # city name. Test both against the filter.
            location = (p.get("location") or "").strip()
            city = (p.get("city") or "").strip()
            country = (p.get("nation") or "").strip()
            location_text = " | ".join(s for s in (location, city, country) if s)
            if not self.matches_location(location_text):
                continue
            jobs.append(
                Job(
                    title=title,
                    url=_JOB_URL_TEMPLATE.format(slug=slug),
                    location=location or city or None,
                )
            )
        return jobs
