from urllib.parse import urlparse

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_JOB_URL_KEYWORDS = ("/job", "/jobs/", "/position", "/career", "/opening", "/vacancy", "/offer")


class PlaywrightScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        base_netloc = urlparse(self.company.careers_url).netloc

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(self.company.careers_url, wait_until="networkidle", timeout=60_000)

            raw_links: list[dict] = await page.eval_on_selector_all(
                "a[href]",
                """els => els.map(el => ({
                    href: el.href,
                    text: el.innerText.trim(),
                    context: el.closest('li, article, [class*="job"], [class*="position"], [class*="role"]')
                              ?.innerText?.trim() ?? el.innerText.trim()
                }))""",
            )
            await browser.close()

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        for item in raw_links:
            href: str = item.get("href", "")
            text: str = item.get("text", "")
            context: str = item.get("context", "")

            if not href or not text:
                continue
            if len(text) < 3 or len(text) > 120:
                continue

            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc != base_netloc:
                continue
            if not any(kw in href.lower() for kw in _JOB_URL_KEYWORDS):
                continue
            if not self.matches_location(context):
                continue
            if href in seen_urls:
                continue

            seen_urls.add(href)
            jobs.append(Job(title=text, url=href))

        return jobs
