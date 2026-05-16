"""DC Advisory — Cloudflare-protected careers page with inline job listings.

The careers page (`www.dcadvisory.com/careers/?location=spain&students=true`)
is gated by Cloudflare bot protection. The bundled-Chromium Playwright build
gets a "Sorry, you have been blocked" page; using the real-Chrome channel with
a few stealth tweaks (webdriver=undefined, plugins, languages, window.chrome)
gets past the check.

Once rendered, the page lists jobs inline as `<h4>` headings inside the
"Students & Graduates opportunities in Spain" / "Experienced hires" sections.
There are no per-job detail URLs — every posting routes through the same
external "Apply Now" link (currently `https://dcadvisoryrecruitingspain.com/`).

We filter headings against the configured location filter (matching either
the heading text directly or the URL's `?location=` param).
"""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from ..models import Job
from .base import BaseScraper

_STEALTH_INIT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-GB','en','es']});
    window.chrome = {runtime: {}};
"""

# Heading text must look like a job posting — start with one of these role
# stems, possibly with seniority/qualifier words around it.
_ROLE_KEYWORDS = (
    "analyst", "associate", "intern", "internship", "graduate",
    "off-cycle", "summer", "vice president", "vp", "director",
    "managing director", "principal",
)
# Section-heading phrases that contain role keywords but are NOT individual
# postings (DC Advisory groups openings under headings like "Students &
# Graduates opportunities in Spain" → "Off-cycle Analyst (Spain, Madrid)").
_SECTION_HEADING_PATTERNS = (
    "opportunities in",
    "students & graduates",
    "experienced hires",
    "current openings",
    "open positions",
)


class DcAdvisoryScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(channel="chrome")
            except Exception:
                # Real Chrome not installed — fall back to bundled Chromium.
                # This will likely hit the Cloudflare block but at least
                # surfaces a clear failure rather than a silent zero.
                browser = await p.chromium.launch()

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            await context.add_init_script(_STEALTH_INIT)
            page = await context.new_page()
            try:
                await page.goto(self.company.careers_url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass
                await asyncio.sleep(6)

                # Best-effort OneTrust accept.
                try:
                    btn = await page.query_selector("#onetrust-accept-btn-handler")
                    if btn:
                        await btn.click(timeout=3_000)
                        await asyncio.sleep(1)
                except Exception:
                    pass

                # The body text is short enough to short-circuit on the CF block page.
                body = await page.inner_text("body")
                if "you have been blocked" in body.lower():
                    raise RuntimeError(
                        "DcAdvisoryScraper: Cloudflare blocked the request "
                        "(install Chrome via `playwright install chrome` or run with real Chrome channel)."
                    )

                headings: list[str] = await page.eval_on_selector_all(
                    "h2, h3, h4",
                    "els => els.map(e => (e.innerText || '').trim()).filter(t => t.length > 0 && t.length < 200)",
                )

                apply_links: list[str] = await page.eval_on_selector_all(
                    "a[href]",
                    """els => els
                        .filter(e => /apply/i.test(e.innerText || '') || /recruit|apply/i.test(e.href || ''))
                        .map(e => e.href)
                        .filter(h => h && !h.includes('#'))""",
                )
            finally:
                await context.close()
                await browser.close()

        apply_url = apply_links[0] if apply_links else self.company.careers_url

        jobs: list[Job] = []
        seen: set[str] = set()
        for text in headings:
            text_lower = text.lower()
            if not any(kw in text_lower for kw in _ROLE_KEYWORDS):
                continue
            if any(pat in text_lower for pat in _SECTION_HEADING_PATTERNS):
                continue
            if not self.matches_location(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            jobs.append(Job(title=text, url=apply_url, location=self.location_filter))
        return jobs
