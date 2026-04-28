import httpx

from ..models import Job
from .base import BaseScraper

_API = "https://boards-api.greenhouse.io/v1/boards/{company_id}/jobs?content=true"


class GreenhouseScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        url = _API.format(company_id=self.company.greenhouse_id)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
        data = response.json()

        jobs: list[Job] = []
        for raw in data.get("jobs", []):
            location: str = raw.get("location", {}).get("name", "") or ""
            if not self.matches_location(location):
                continue

            department = None
            if raw.get("departments"):
                department = raw["departments"][0].get("name")

            # Some Greenhouse boards surface job type in custom metadata fields
            job_type = None
            for meta in raw.get("metadata", []):
                if "type" in (meta.get("name") or "").lower():
                    job_type = meta.get("value")
                    break

            description = raw.get("content") or ""
            jobs.append(
                Job(
                    title=raw["title"],
                    url=raw["absolute_url"],
                    location=location or None,
                    department=department,
                    job_type=job_type,
                    external_id=str(raw["id"]),
                    description=description[:500] or None,
                )
            )
        return jobs
