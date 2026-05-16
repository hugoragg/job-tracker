"""McKinsey — campus application-deadline tracker, not a typical ATS.

The page (`mckinsey.com/careers/students/application-deadlines?...`) renders
a static set of role "deadline cards" filtered by `?officeCountry=<country>`
and `?roleNames=<comma-list>` query params. Each card is an `<h3>` role
title (e.g. "Business Analyst - Spain") inside a content block that also
holds a status label ("ROLLING", "THIS ROUND'S DEADLINE HAS PASSED") and,
when applications are open, a per-role "Apply to the role in <country>"
link to the actual job posting on `/careers/search-jobs/jobs/...`.

The generic `PlaywrightScraper` fails here for two reasons:
  1. McKinsey's CDN aborts vanilla Chromium with `ERR_HTTP2_PROTOCOL_ERROR`.
     We bypass it with the real-Chrome channel + stealth tweaks, same trick
     as `DcAdvisoryScraper`.
  2. The page has no per-job URLs at top level — the role cards are content
     blocks, not anchors, and only the open roles expose an apply link.

We extract every role h3 whose title matches the configured location filter
(case-insensitive substring on the title text itself — McKinsey's titles
end in "- Spain"), pair it with the surrounding card text to recover the
status label, and use the per-card apply link as the job URL when present
(falling back to the careers_url for cards whose deadline has passed).
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

# JS extraction script — runs in the page context, returns one entry per
# role card.
_EXTRACT_JS = r"""
() => {
    // Status badge regex — case-sensitive uppercase (the McKinsey design
    // system renders these labels as ALL CAPS) to avoid accidentally matching
    // body copy like "open positions".
    const STATUS_RE = /(ROLLING|THIS ROUND[’']S DEADLINE HAS PASSED|DEADLINE HAS PASSED|APPLY NOW|CLOSED|OPEN NOW)/;
    const cards = [];
    const headings = document.querySelectorAll('h3[class*="mdc-c-heading"]');
    for (const h of headings) {
        const title = (h.innerText || '').trim();
        if (!title) continue;
        // Walk up to the content-block card that holds the title + date copy.
        let card = h;
        for (let i = 0; i < 8 && card; i++) {
            if (card.className && typeof card.className === 'string'
                && card.className.includes('content-block')) break;
            card = card.parentElement;
        }
        // The status badge ("ROLLING", "THIS ROUND'S DEADLINE HAS PASSED") is
        // typically a previous sibling of the content-block's parent, and the
        // "Apply to the role in <country>" link is a later sibling inside the
        // same outer wrapper. Walk up one ancestor at a time, looking at the
        // first line of innerText for the badge.
        let status = null;
        let outer = null;
        let anc = card ? card.parentElement : null;
        for (let i = 0; i < 4 && anc; i++) {
            const txt = (anc.innerText || '').trim();
            if (txt) {
                const firstLine = txt.split('\n', 1)[0].trim();
                const m = firstLine.match(STATUS_RE);
                if (m) { status = m[1]; outer = anc; break; }
            }
            anc = anc.parentElement;
        }
        // Apply link: search within whichever container we found. Prefer the
        // outer (status) ancestor since the apply link sits one level above
        // the content-block.
        const searchRoot = outer || card;
        let applyHref = null;
        if (searchRoot) {
            for (const a of searchRoot.querySelectorAll('a[href]')) {
                if (/apply.*role|apply\s+to/i.test(a.innerText || '')) {
                    applyHref = a.href;
                    break;
                }
            }
        }
        cards.push({title, status, applyHref});
    }
    return cards;
}
"""


def _normalize_status(status: str | None) -> str | None:
    if not status:
        return None
    s = status.lower()
    if "rolling" in s:
        return "Rolling"
    if "passed" in s:
        return "Deadline passed"
    if "apply now" in s or s == "open":
        return "Open"
    if s == "closed":
        return "Closed"
    return status.title()


class McKinseyScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(channel="chrome")
            except Exception:
                # Real Chrome not installed — fall back to bundled Chromium.
                # Will likely hit the HTTP/2 protocol error but at least fails
                # loudly rather than silently returning 0.
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
                await page.goto(
                    self.company.careers_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass
                # The role cards render via client-side rendering after the
                # filter dropdowns initialize — give them time to populate.
                await asyncio.sleep(7)

                raw_cards = await page.evaluate(_EXTRACT_JS)
            finally:
                await context.close()
                await browser.close()

        jobs: list[Job] = []
        seen: set[str] = set()
        for card in raw_cards:
            title = (card.get("title") or "").strip()
            if not title:
                continue
            if not self.matches_location(title):
                continue
            if title in seen:
                continue
            seen.add(title)
            status = _normalize_status(card.get("status"))
            display_title = f"{title} ({status})" if status else title
            url = card.get("applyHref") or self.company.careers_url
            jobs.append(Job(title=display_title, url=url, location=self.location_filter))
        return jobs
