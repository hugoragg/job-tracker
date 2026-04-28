from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from ..models import Job
from .base import BaseScraper

_JOB_CLASS_KEYWORDS = ("job", "position", "role", "opening", "vacancy", "career", "offer")
_JOB_URL_KEYWORDS   = ("/job", "/jobs/", "/position", "/career", "/opening", "/vacancy", "/offer")


class HtmlScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.company.careers_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        base_url = self.company.careers_url

        containers: list[Tag] = (
            soup.select(self.company.job_selector)
            if self.company.job_selector
            else self._heuristic_containers(soup)
        )

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        for container in containers:
            link: Tag | None = container if container.name == "a" else container.find("a")  # type: ignore[assignment]
            if not link or not link.get("href"):
                continue

            title = link.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue

            href = urljoin(base_url, link["href"])
            if href in seen_urls:
                continue

            surrounding_text = container.get_text(" ", strip=True)
            if not self.matches_location(surrounding_text):
                continue

            seen_urls.add(href)
            jobs.append(Job(title=title, url=href))

        return jobs

    def _heuristic_containers(self, soup: BeautifulSoup) -> list[Tag]:
        # Strategy 1: elements whose class names look job-related
        by_class: list[Tag] = soup.find_all(
            ["li", "div", "article"],
            class_=lambda c: c and any(kw in " ".join(c).lower() for kw in _JOB_CLASS_KEYWORDS),
        )
        if by_class:
            return by_class

        # Strategy 2: anchor tags whose href looks job-related
        base_netloc = urlparse(self.company.careers_url).netloc
        return [
            a
            for a in soup.find_all("a", href=True)
            if urlparse(a["href"]).netloc in ("", base_netloc)
            and any(kw in a["href"].lower() for kw in _JOB_URL_KEYWORDS)
        ]
