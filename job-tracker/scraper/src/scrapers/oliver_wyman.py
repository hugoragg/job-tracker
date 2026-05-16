"""Oliver Wyman — Phenom People backend on `careers.marsh.com`.

Marsh McLennan's careers portal hosts Marsh, Mercer, Oliver Wyman, and Guy
Carpenter on the same Phenom People tenant. The Oliver Wyman search landing
page (`careers.marsh.com/global/en/oliver-wyman-search`) issues a POST to
`/widgets` with a body that pre-filters `business=Oliver Wyman` server-side.
URL params do not control the filter — only the request body does.

We mirror the captured payload, add `city: [Madrid]` to `selected_fields`,
and paginate via `from` until we exhaust `totalHits`. This is the same
pattern as `BcgScraper` but adapted for Marsh's `pageName`/`pageId`/`rk`
values and the `eagerLoadRefineSearchSession` ddoKey.

Jobs flow back at `data.jobs[]` with `title`, `location`, `applyUrl`,
`jobId`, etc.
"""
from __future__ import annotations

import httpx

from ..models import Job
from .base import BaseScraper

_API_URL = "https://careers.marsh.com/widgets"
_PAGE_SIZE = 50
# Captured request body uses ddoKey="eagerLoadRefineSearchSession" on page
# load, but that returns `{tokenAvailable: false}` — the actual job-list call
# uses ddoKey="refineSearch" (same as BCG's Phenom People backend).
_DDO_KEY = "refineSearch"


class OliverWymanScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Origin": "https://careers.marsh.com",
                "Referer": "https://careers.marsh.com/global/en/oliver-wyman-search",
            },
        ) as client:
            offset = 0
            while True:
                body = {
                    "lang": "en_global",
                    "deviceType": "desktop",
                    "country": "global",
                    "pageName": "Oliver Wyman Search",
                    "ddoKey": _DDO_KEY,
                    "sortBy": "",
                    "subsearch": "",
                    "from": offset,
                    "irs": False,
                    "jobs": True,
                    "counts": True,
                    "all_fields": [
                        "category", "country", "state", "city", "timeType",
                        "business", "workFromHome", "campus", "jobType",
                        "phLocSlider",
                    ],
                    "pageType": "landingPage",
                    "size": _PAGE_SIZE,
                    "rk": "l-oliver-wyman-search",
                    "clearAll": False,
                    "jdsource": "facets",
                    "isSliderEnable": True,
                    "pageId": "page52-prod-ds",
                    "siteType": "external",
                    "keywords": "",
                    "global": True,
                    "selected_fields": {
                        "business": ["Oliver Wyman"],
                        "city": [self.location_filter],
                    },
                    "locationData": {
                        "sliderRadius": 25,
                        "aboveMaxRadius": False,
                        "LocationUnit": "miles",
                    },
                    "rkstatus": True,
                }
                resp = await client.post(_API_URL, json=body)
                resp.raise_for_status()
                payload = resp.json().get(_DDO_KEY, {})
                data = payload.get("data", {}) or {}
                batch = data.get("jobs", []) or []
                total = payload.get("totalHits", 0) or 0

                for raw in batch:
                    title = (raw.get("title") or "").strip()
                    if not title:
                        continue

                    location = raw.get("location") or raw.get("city") or ""
                    if not self.matches_location(location) and not self.matches_location(
                        ", ".join(raw.get("multi_location") or [])
                    ):
                        continue

                    apply_url = (raw.get("applyUrl") or "").replace("&amp;", "&")
                    job_id = str(raw.get("jobId") or raw.get("reqId") or "")
                    if not apply_url and job_id:
                        apply_url = f"https://careers.marsh.com/global/en/job/{job_id}"
                    if not apply_url:
                        continue

                    jobs.append(
                        Job(
                            title=title,
                            url=apply_url,
                            location=location or None,
                            department=raw.get("category") or None,
                            external_id=job_id or None,
                        )
                    )

                offset += _PAGE_SIZE
                if offset >= total or not batch:
                    break

        return jobs
