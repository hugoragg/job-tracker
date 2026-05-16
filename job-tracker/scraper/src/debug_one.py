"""Quick per-company debug: dump captured XHRs and DOM links to understand why
a scraper returns 0 jobs.

Run: uv run python -m src.debug_one <company_substring>
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from playwright.async_api import Response, async_playwright

from .models import ScraperConfig

load_dotenv()
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: debug_one <substring>")
        return
    needle = sys.argv[1].lower()

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = ScraperConfig(**raw)
    target = next((c for c in config.companies if needle in c.name.lower()), None)
    if not target:
        print(f"No match for '{needle}'")
        return

    print(f"Target: {target.name}  ({target.ats})")
    print(f"URL:    {target.careers_url}")
    print()

    captured: list[tuple[str, int]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-GB",
        )
        page = await ctx.new_page()

        async def on_response(response: Response) -> None:
            try:
                ctype = (response.headers.get("content-type") or "").lower()
                if "json" not in ctype:
                    return
                body = await response.text()
                captured.append((response.url, len(body)))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        try:
            await page.goto(target.careers_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"goto failed: {e}")
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        await asyncio.sleep(4)
        for _ in range(4):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            await asyncio.sleep(0.7)

        all_links: list[dict] = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.href,
                text: el.innerText.trim().slice(0, 200)
            })).filter(l => l.href && !l.href.startsWith('javascript:') && !l.href.startsWith('mailto:'))""",
        )

        page_html_len = len(await page.content())
        await ctx.close()
        await browser.close()

    print(f"Page HTML length: {page_html_len}")
    print(f"\nCaptured JSON responses: {len(captured)}")
    for url, blen in captured[:20]:
        print(f"  [{blen:>8}] {url[:140]}")
    if len(captured) > 20:
        print(f"  ... +{len(captured)-20} more")

    print(f"\nDOM links: {len(all_links)}")
    base_netloc = urlparse(target.careers_url).netloc
    same_origin = [l for l in all_links if urlparse(l["href"]).netloc in (base_netloc, "")]
    print(f"  Same-origin (or relative): {len(same_origin)}")
    print("\nFirst 40 same-origin links:")
    for l in same_origin[:40]:
        text = (l["text"] or "").replace("\n", " | ")[:80]
        print(f"  {text:80s}  {l['href'][:120]}")


if __name__ == "__main__":
    asyncio.run(main())
