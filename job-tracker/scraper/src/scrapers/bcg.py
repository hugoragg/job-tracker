"""BCG careers scraper.

BCG runs on Phenom People. The search page `careers.bcg.com/global/en/search-results`
filters jobs via POST to `/widgets` with a JSON body whose `selected_fields`
field carries the active facets. No URL params encode the filter — they must
be sent in the request body — so we issue the call directly.

User-defined filter set: City=Madrid, Category in {Consulting, Data Science
and Analytics}.
"""
from __future__ import annotations

import httpx

from ..models import Job
from .base import BaseScraper

_API_URL = "https://careers.bcg.com/widgets"
_PAGE_SIZE = 50

_SELECTED_FIELDS = {
    "city": ["Madrid"],
    "category": ["Consulting", "Data Science and Analytics"],
}


class BcgScraper(BaseScraper):
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
                "Origin": "https://careers.bcg.com",
                "Referer": "https://careers.bcg.com/global/en/search-results",
            },
        ) as client:
            offset = 0
            while True:
                body = {
                    "lang": "en_global",
                    "deviceType": "desktop",
                    "country": "global",
                    "pageName": "search-results",
                    "ddoKey": "refineSearch",
                    "sortBy": "",
                    "subsearch": "",
                    "from": offset,
                    "irs": False,
                    "jobs": True,
                    "counts": True,
                    "all_fields": ["country", "city", "category", "company", "type", "jobType"],
                    "size": _PAGE_SIZE,
                    "clearAll": False,
                    "jdsource": "facets",
                    "isSliderEnable": False,
                    "pageId": "page17-ds",
                    "siteType": "external",
                    "keywords": "",
                    "global": True,
                    "selected_fields": _SELECTED_FIELDS,
                    "locationData": {},
                }
                resp = await client.post(_API_URL, json=body)
                resp.raise_for_status()
                payload = resp.json().get("refineSearch", {})
                data = payload.get("data", {}) or {}
                batch = data.get("jobs", []) or []
                total = payload.get("totalHits", 0) or 0

                for raw in batch:
                    title = (raw.get("title") or "").strip()
                    if not title:
                        continue

                    location = raw.get("location") or raw.get("city") or ""
                    # The API already filtered by city=Madrid, so any returned
                    # job either has Madrid as its primary city or as one of
                    # multi_location entries. We trust the filter and add a
                    # belt-and-braces matches_location check.
                    if not self.matches_location(location) and not self.matches_location(
                        ", ".join(raw.get("multi_location") or [])
                    ):
                        continue

                    apply_url = raw.get("applyUrl") or ""
                    # Strip HTML entities the API sometimes embeds in URLs.
                    apply_url = apply_url.replace("&amp;", "&")

                    job_id = str(raw.get("jobId") or raw.get("reqId") or "")
                    if not apply_url and job_id:
                        apply_url = (
                            f"https://careers.bcg.com/global/en/job/{job_id}"
                        )
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
