import re
from urllib.parse import parse_qs, urlparse

import httpx

from ..models import Job
from .base import BaseScraper

_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")

# URL params that are tracking/routing params, not Workday facet IDs
_NON_FACET_PARAMS = frozenset({"source", "ref", "referrer", "channel", "campaign",
                                "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"})


class WorkdayScraper(BaseScraper):
    """Scrapes Workday job boards via the undocumented CXS JSON API.

    Parses the tenant, instance, and site from careers_url, converts URL
    query params into Workday appliedFacets, and paginates through results.
    """

    async def fetch_jobs(self) -> list[Job]:
        parsed = urlparse(self.company.careers_url)

        # "bbva.wd3.myworkdayjobs.com" → tenant="bbva", instance="wd3"
        host_parts = parsed.hostname.split(".")
        tenant = host_parts[0]
        instance = host_parts[1]

        # Strip locale prefix (en-US, en-GB, …) from path to get the site name
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        site = "/".join(p for p in path_parts if not _LOCALE_RE.match(p))

        api_url = (
            f"https://{tenant}.{instance}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}/jobs"
        )

        # URL query params → appliedFacets; strip tracking params that Workday rejects as unknown facets
        applied_facets: dict = {
            k: v for k, v in parse_qs(parsed.query).items()
            if k not in _NON_FACET_PARAMS
        }

        limit = 20
        offset = 0
        all_jobs: list[Job] = []

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.post(
                    api_url,
                    json={
                        "appliedFacets": applied_facets,
                        "limit": limit,
                        "offset": offset,
                        "searchText": "",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for posting in postings:
                    location: str = posting.get("locationsText", "") or ""
                    if not self.matches_location(location):
                        continue

                    title: str = posting.get("title", "")
                    ext_path: str = posting.get("externalPath", "")
                    if not title or not ext_path:
                        continue

                    all_jobs.append(
                        Job(
                            title=title,
                            url=f"https://{parsed.hostname}{ext_path}",
                            location=location or None,
                        )
                    )

                total: int = data.get("total", 0)
                offset += limit
                if offset >= total:
                    break

        return all_jobs
