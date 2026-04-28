import httpx

from ..models import Job
from .base import BaseScraper

_API = "https://api.lever.co/v0/postings/{lever_id}?mode=json"


class LeverScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        url = _API.format(lever_id=self.company.lever_id)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
        data = response.json()

        jobs: list[Job] = []
        for raw in data:
            categories = raw.get("categories", {})
            location: str = categories.get("location") or ""
            if not self.matches_location(location):
                continue

            description_plain: str = raw.get("descriptionPlain") or ""
            jobs.append(
                Job(
                    title=raw["text"],
                    url=raw["hostedUrl"],
                    location=location or None,
                    department=categories.get("department") or None,
                    job_type=categories.get("commitment") or None,  # "Full-time", "Internship", etc.
                    external_id=raw["id"],
                    description=description_plain[:500] or None,
                )
            )
        return jobs
