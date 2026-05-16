"""Generic SPA-aware scraper.

Strategy:
  1. Open the careers page in Chromium.
  2. Capture every JSON XHR response while the page loads (most modern career
     portals fetch jobs via XHR — Workday, SuccessFactors, Oracle HCM, iCIMS,
     TalentLink, custom, etc.).
  3. Extract jobs from those JSON bodies heuristically (works without knowing
     the specific ATS schema).
  4. Fall back to scraping <a> tags from the rendered DOM if no JSON yielded
     anything useful.
  5. On HTTP/2 protocol errors, retry once with HTTP/2 disabled.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page, Response, async_playwright

from ..models import Job
from .base import BaseScraper

# ─── Tuning ──────────────────────────────────────────────────────────────────

_NAV_TIMEOUT_MS = 60_000
_POST_LOAD_WAIT_S = 4.0           # let lazy XHRs fire after domcontentloaded
_NETWORK_IDLE_TIMEOUT_MS = 12_000
_MAX_SCROLLS = 4

# ─── Link filtering ──────────────────────────────────────────────────────────

# Strong signals that a URL points at one specific job (vs. a category page).
_STRONG_JOB_URL_KEYWORDS = (
    "/job/", "/jobs/", "/empleo/", "/oferta/", "/ofertas/", "/vacante/",
    "/vacancy/", "/vacancies/", "/posting/", "/postings/", "/jobad/",
    "/requisition/", "/requisitions/", "/puesto/", "/trabajo/",
)
# Same as above but tolerating Spanish kebab-case compounds. Matches a path
# segment that contains a job-stem bounded by `/`, `-` or `_` — so e.g.
# `/ofertas-de-empleo/property-manager/` is recognised as a job URL.
_STRONG_JOB_PATH_RE = re.compile(
    r"(?:^|[/_-])(?:empleo|oferta|vacante|vacancy|puesto|trabajo|posting|requisition|jobad|job|jobs)s?(?:[/_-]|$)",
    re.IGNORECASE,
)
# Weak signals — only accepted alongside a numeric ID in the URL (job IDs).
_WEAK_JOB_URL_KEYWORDS = (
    "/career", "/careers/", "/opening", "/programme", "/internship",
    "/graduate", "/role", "/becas", "/practicas", "/position", "/offer",
    "/apply", "/opportunit", "/jobsearch", "/job-search", "/job-",
)
_JOB_QUERY_PARAMS = ("jobid", "job_id", "vacancyid", "reqid", "requisitionid", "positionid")
# Paths that always denote navigation (saved jobs, user account, alerts, search
# pages with no specific posting). Even though they may contain "jobs" / "empleo"
# substrings, they're never specific job postings.
_NAV_PATH_KEYWORDS = (
    "/saved-jobs", "/saved_jobs", "/savedjobs", "/my-jobs", "/myjobs",
    "/job-alerts", "/jobalerts", "/alertas-de-empleo", "/ofertas-guardadas",
    "/login", "/sign-in", "/signin", "/register", "/sign-up", "/signup",
    "/account", "/profile", "/cuenta", "/mi-perfil", "/saved-searches",
    # Generic search-results / informational pages that look job-ish but
    # aren't specific postings.
    "/job-search", "/jobs-search", "/job-recruitment-scams",
    "/recruitment-scams", "/hiring-process", "/hiring-fraud",
    "/job-simulations", "/job-simulation",
    "/find-a-job", "/find-a-role", "/find-jobs", "/find-roles",
    "/buscar-trabajo", "/buscar-empleo", "/busqueda-de-empleo",
    # Rothschild has a sibling section for experienced hires; the link
    # "Experienced Professionals" lives inside /opportunities/ pages and gets
    # picked up as a fake job otherwise.
    "/experienced-professionals/", "/experienced-hires/",
)
_NUMERIC_ID_RE = re.compile(r"\d{4,}")  # 4+ consecutive digits = likely a job/req ID
# Long hex / alphanumeric tokens (16+ chars) — MongoDB ObjectIds (24 hex), GUIDs,
# base64 IDs. Used as a complement to _NUMERIC_ID_RE for sites whose job IDs are
# all-letters-with-digits-mixed (e.g. ObjectId "5ee62d016b800f0fc8e70d1c").
_ALPHANUM_ID_RE = re.compile(r"[0-9a-fA-F]{16,}")
_LOCALE_RE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2})?$")
_EXPIRE_RE = re.compile(r"\s*expires?:\s*\d{1,2}/\d{1,2}/\d{4}", re.IGNORECASE)
_GENERIC_TITLE_TERMS = frozenset({
    "empleo", "employment", "job", "jobs", "career", "careers", "ver oferta",
    "view job", "apply", "apply now", "learn more", "see more", "details",
    "ver más", "más información", "full-time", "part-time", "internship",
    "prácticas", "becas", "remote", "hybrid", "on-site", "spain", "spain (español)",
    "españa", "english", "spanish", "español",
    "saved jobs", "saved job", "ofertas guardadas", "oferta guardada",
    "job alerts", "alertas de empleo", "search jobs", "buscar empleo",
    # Career-portal section/nav labels that masquerade as titles.
    "events", "students", "professionals", "experienced hires", "experienced opportunities",
    "student opportunities", "graduate opportunities", "diversity programs", "leadership letters",
    "giving back", "find your place", "our work areas", "integrated teams", "students and graduates",
    "graduate program", "our locations", "our offices", "open positions", "all opportunities",
    "browse jobs", "search jobs", "all jobs", "search vacancies", "campus opportunities",
    "rss feed", "more jobs", "view all", "all positions", "show more", "load more",
    "saved jobs", "my account", "sign in", "sign up", "create account",
    "see the offer", "see offer", "see job", "view offer", "view position",
    "ver oferta completa", "más detalles", "more details", "read more", "view details",
    "consultar oferta", "ir a la oferta", "ver puesto",
    "add to favorites", "add to favourites", "save", "save job", "save this job",
    "share", "share this job", "favorite", "favourite", "bookmark",
    "add to wishlist", "guardar", "guardar oferta", "compartir",
    "it & digital", "data", "global banking & investor solutions",
    "financial department", "general inspection, audit & consulting", "human resources",
    "compliance, legal & risk", "operations", "marketing & communications",
})

# JSON heuristics: keys that commonly hold a job's title / url / id / location
_TITLE_KEYS = ("title", "jobtitle", "postingtitle", "job_title", "displayjobtitle", "name",
               "displayname", "postingtemplatetitle")
_URL_KEYS = ("url", "absolute_url", "applyurl", "joburl", "hostedurl", "permalink", "link", "href",
             "external_path", "externalpath", "externalurl")
_ID_KEYS = ("id", "jobid", "requisitionid", "reqid", "externalid", "external_id", "jobpostingid",
            "postingid", "jobreqid")
_LOCATION_KEYS = ("location", "locations", "locationtext", "locationstext", "city",
                  "primarylocation", "primary_location", "officecity", "office", "country", "region",
                  "geo", "workcity", "workcountry")
_DEPT_KEYS = ("department", "departments", "businessunit", "business_unit", "category", "function",
              "jobcategory", "job_category", "jobfunction", "team", "division")

# Response URLs we trust as containing job data. Anything else, we still parse but with
# extra strictness (we only accept items that *clearly* look like postings).
_JOB_RESPONSE_URL_KEYWORDS = (
    "job", "vacanc", "posting", "requisition", "opening", "career", "search",
    "opportunit", "position", "recruit", "oferta", "empleo", "cxs", "cx_",
)
# Single-word titles that are almost always category/facet labels, not real jobs.
_NON_JOB_SINGLE_WORDS = frozenset({
    "virtual", "remote", "hybrid", "office", "onsite", "fulltime", "parttime",
    "internship", "diversity", "graduate", "experienced", "entry", "senior",
    "junior", "manager", "intern", "campus", "events", "all", "home", "more",
    "search", "jobs", "careers", "apply", "register", "login", "spain",
})


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_title(text: str, url_hint: str | None = None) -> str:
    """Pick the most title-like line from possibly multi-line link text.

    If ``url_hint`` is given, prefer a candidate whose normalized form matches
    the URL slug — many career sites render link text as
    ``"Department\\nJob Title\\nLocation"`` and the longest line is the
    department, not the title. The URL slug is the most reliable tie-breaker.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return _EXPIRE_RE.sub("", lines[0]).strip()

    candidates = []
    for line in lines:
        clean = _EXPIRE_RE.sub("", line).strip()
        if not clean or len(clean) < 4:
            continue
        if clean.lower() in _GENERIC_TITLE_TERMS:
            continue
        if len(clean.split()) == 1 and len(clean) < 15:
            continue
        candidates.append(clean)

    if not candidates:
        return _EXPIRE_RE.sub("", lines[0]).strip()

    if url_hint:
        slug_title = _title_from_url_slug(url_hint)
        if slug_title:
            def _slug_normalize(s: str) -> str:
                s = re.sub(r"[^\w\s]", " ", s.lower())
                return re.sub(r"\s+", " ", s).strip()
            slug_norm = _slug_normalize(slug_title)
            for c in candidates:
                if _slug_normalize(c) == slug_norm:
                    return c

    candidates.sort(key=len, reverse=True)
    # Cap at 150 (not 80) — some real job titles are long, e.g. Goldman's
    # pipe-separated metadata titles like "2026 | EMEA | London | Asset
    # Management | Private Credit | Seasonal/Off-Cycle Internship" (~95 chars).
    # `_looks_like_real_title` already rejects descriptions over 200 chars.
    for c in candidates:
        if len(c) <= 150:
            return c
    return candidates[-1]


def _looks_like_random_id(word: str) -> bool:
    """Heuristic for "looks like a random ID, not a real word"."""
    if len(word) < 6:
        return False
    has_upper = any(c.isupper() for c in word)
    has_lower = any(c.islower() for c in word)
    has_digit = any(c.isdigit() for c in word)
    if has_upper and has_lower and has_digit:
        return True
    # Long all-uppercase or alternating-case strings are also IDs.
    case_changes = sum(1 for i in range(1, len(word)) if word[i].isupper() != word[i - 1].isupper())
    if case_changes >= 4:
        return True
    return False


def _title_from_url_slug(url: str) -> str | None:
    """Derive a human title from a URL path slug as a last-resort fallback.

    e.g. ``/en/job-offers/2027-global-markets-summer-analyst-25000ABC-e``
    →    ``2027 Global Markets Summer Analyst``

    Walks the path from the rightmost segment leftwards, returning the first
    segment that converts to a plausible title. This handles ATSes like
    BlackRock where the last segment is a numeric job ID and the title-slug
    lives earlier (e.g. ``.../sales-director-portugal/45831/94440340720``).
    """
    path = urlparse(url).path.rstrip("/")
    if not path:
        return None
    segments = [s for s in path.split("/") if s]
    for slug in reversed(segments):
        title = _slug_segment_to_title(slug)
        if title:
            return title
    return None


def _slug_segment_to_title(slug: str) -> str | None:
    if not slug or len(slug) < 4:
        return None
    # Replace separators and break into words.
    words = re.split(r"[-_]+", slug)
    # If any word looks like a random ID, the whole slug is probably opaque
    # (e.g. "/jobs/H0yXGelmdoB7XrPrUxH-Og") — don't try to derive a title.
    if any(_looks_like_random_id(w) for w in words):
        return None
    # Drop trailing token if it's a short alphanumeric ID (e.g. "25000ABC", "e", "1234")
    while words and len(words[-1]) <= 8 and any(c.isdigit() for c in words[-1]) and not words[-1].isdigit():
        words.pop()
    while words and (words[-1].isdigit() or len(words[-1]) <= 1):
        words.pop()
    if not words or len(words) < 2:
        return None
    title = " ".join(w.capitalize() if w.isalpha() else w for w in words)
    title = re.sub(r"\s+", " ", title).strip()
    if 5 <= len(title) <= 120:
        return title
    return None


_JOB_ID_QUERY_RE = re.compile(r"\b(?:id|jobid|job_id|requisitionid|reqid|positionid|vacancyid)=([A-Za-z0-9_-]{4,})", re.IGNORECASE)
_JOB_ID_FRAGMENT_RE = re.compile(r"^job[-_]?(.+)$", re.IGNORECASE)


def _job_canonical_key(url: str) -> str:
    """Stable key for deduping the same posting surfaced via different URL forms.

    e.g. ``...#job-R00297547_es`` and ``.../jobdetails?id=R00297547_es&title=...``
    both reduce to ``R00297547_es``.
    """
    parsed = urlparse(url)
    frag = parsed.fragment
    if frag:
        m = _JOB_ID_FRAGMENT_RE.match(frag)
        if m:
            return m.group(1).lower()
    if parsed.query:
        m = _JOB_ID_QUERY_RE.search(parsed.query)
        if m:
            return m.group(1).lower()
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if tail and re.search(r"\d{4,}", tail):
        return tail.lower()
    return url.lower()


def _strip_locale_prefix(path: str) -> str:
    """`/es-es/careers/...` → `/careers/...`. Used to detect language-switcher links."""
    parts = path.strip("/").split("/")
    if parts and _LOCALE_RE.match(parts[0]):
        return "/" + "/".join(parts[1:])
    return path.rstrip("/")


def _ci_get(d: dict, keys: tuple[str, ...]) -> Any:
    """Case-insensitive dict lookup over a tuple of candidate keys."""
    if not isinstance(d, dict):
        return None
    lowered = {k.lower(): v for k, v in d.items() if isinstance(k, str)}
    for k in keys:
        if k in lowered and lowered[k] not in (None, "", []):
            return lowered[k]
    return None


def _flatten_to_string(value: Any) -> str:
    """Reduce a nested JSON value to a human string. Used for location fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten_to_string(v) for v in value]
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        for k in ("name", "label", "city", "displayname", "text", "title"):
            v = value.get(k) or value.get(k.title())
            if v:
                return _flatten_to_string(v)
        return ", ".join(_flatten_to_string(v) for v in value.values() if v)
    return ""


def _job_score(obj: dict) -> int:
    """Score 0-5 measuring how job-like a dict object looks."""
    if not isinstance(obj, dict):
        return 0
    score = 0
    if _ci_get(obj, _TITLE_KEYS) is not None:
        score += 1
    if _ci_get(obj, _URL_KEYS) is not None:
        score += 1
    if _ci_get(obj, _ID_KEYS) is not None:
        score += 1
    if _ci_get(obj, _LOCATION_KEYS) is not None:
        score += 1
    if _ci_get(obj, _DEPT_KEYS) is not None:
        score += 1
    return score


def _looks_like_real_title(title: str) -> bool:
    """Reject obvious facet/category labels masquerading as titles."""
    t = title.strip()
    if len(t) < 5 or len(t) > 200:
        return False
    if t.lower() in _NON_JOB_SINGLE_WORDS or t.lower() in _GENERIC_TITLE_TERMS:
        return False
    # Real job titles virtually always have 2+ words. Single-word "titles" are
    # almost always categories ("Internship") or API endpoint names
    # ("recruitingCEEvents") or labels.
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < 2:
        return False
    return True


def _walk_json(
    node: Any,
    depth: int = 0,
    strict: bool = False,
) -> list[dict]:
    """Find lists-of-dicts that look like job postings.

    ``strict`` raises the bar: each item must score >= 3 on the job-likeness
    scale. Used for responses whose URL doesn't already imply they're job data.
    """
    found: list[dict] = []
    if depth > 8:
        return found

    if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
        if 1 <= len(node) <= 500:
            scores = [_job_score(item) for item in node[:5]]
            sample_min_score = min(scores) if scores else 0
            sample_avg_score = sum(scores) / len(scores) if scores else 0
            threshold = 3 if strict else 2
            if sample_min_score >= threshold or sample_avg_score >= threshold + 0.5:
                # Title presence is mandatory.
                if all(_ci_get(item, _TITLE_KEYS) for item in node[:5]):
                    found.extend(node)
        # Recurse into nested structures regardless.
        for item in node:
            found.extend(_walk_json(item, depth + 1, strict))
        return found

    if isinstance(node, dict):
        for v in node.values():
            found.extend(_walk_json(v, depth + 1, strict))
    return found


def _build_job_from_obj(obj: dict, base_url: str) -> Job | None:
    title = _ci_get(obj, _TITLE_KEYS)
    if not isinstance(title, str):
        return None
    title = _norm(title)
    if not _looks_like_real_title(title):
        return None

    raw_url = _ci_get(obj, _URL_KEYS)
    location_raw = _ci_get(obj, _LOCATION_KEYS)
    location = _flatten_to_string(location_raw) or None

    has_real_url = isinstance(raw_url, str) and bool(raw_url)
    # Require either a real URL or a location field. A bare {title, id} dict is
    # almost always a category/facet, not a job posting.
    if not has_real_url and not location:
        return None

    if has_real_url:
        url = urljoin(base_url, raw_url)
    else:
        ext_id = _ci_get(obj, _ID_KEYS)
        if not ext_id:
            return None
        url = f"{base_url.rstrip('/')}#job-{ext_id}"

    dept_raw = _ci_get(obj, _DEPT_KEYS)
    department = _flatten_to_string(dept_raw) or None

    ext_id = _ci_get(obj, _ID_KEYS)
    return Job(
        title=title,
        url=url,
        location=location,
        department=department,
        external_id=str(ext_id) if ext_id else None,
    )


# ─── Scraper ─────────────────────────────────────────────────────────────────

class PlaywrightScraper(BaseScraper):
    async def fetch_jobs(self) -> list[Job]:
        try:
            return await self._scrape(disable_http2=False)
        except Exception as exc:
            msg = str(exc)
            retryable = (
                "ERR_HTTP2_PROTOCOL_ERROR" in msg
                or "ERR_HTTP2" in msg
                or "Timeout" in msg
                or "timeout" in msg
                or "ERR_NETWORK_CHANGED" in msg
                or "chrome-error" in msg
            )
            if retryable:
                # Retry with HTTP/2 disabled and a more permissive wait state.
                return await self._scrape(disable_http2=True)
            raise

    async def _scrape(self, disable_http2: bool) -> list[Job]:
        base_parsed = urlparse(self.company.careers_url)
        base_netloc = base_parsed.netloc
        base_path_norm = _strip_locale_prefix(base_parsed.path)

        captured: list[tuple[str, str]] = []  # (url, body_text)

        chromium_args: list[str] = []
        if disable_http2:
            chromium_args.append("--disable-http2")

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=chromium_args or None)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            page = await context.new_page()

            async def on_response(response: Response) -> None:
                try:
                    ctype = (response.headers.get("content-type") or "").lower()
                    if "json" not in ctype:
                        return
                    if response.status >= 400:
                        return
                    body = await response.text()
                    if len(body) > 2_000_000:  # skip very large blobs
                        return
                    captured.append((response.url, body))
                except Exception:
                    pass

            page.on("response", lambda r: asyncio.create_task(on_response(r)))

            nav_timeout = 90_000 if disable_http2 else _NAV_TIMEOUT_MS
            try:
                await page.goto(
                    self.company.careers_url,
                    wait_until="domcontentloaded",
                    timeout=nav_timeout,
                )
            except Exception:
                # Some sites never reach DOMContentLoaded under bot-detection
                # or analytics-heavy SPAs. Fall back to "commit" — we just need
                # the request to start; we'll rely on post-load sleep + scroll
                # to capture XHRs and the rendered DOM.
                try:
                    await page.goto(
                        self.company.careers_url,
                        wait_until="commit",
                        timeout=nav_timeout,
                    )
                except Exception:
                    # Give up on navigation event; the page object may still
                    # have content if the request went through partially.
                    pass

            try:
                await page.wait_for_load_state("networkidle", timeout=_NETWORK_IDLE_TIMEOUT_MS)
            except Exception:
                pass

            await asyncio.sleep(_POST_LOAD_WAIT_S)

            # Trigger lazy-loaded content via scroll.
            for _ in range(_MAX_SCROLLS):
                try:
                    await page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                except Exception:
                    break
                await asyncio.sleep(0.7)

            link_extract_script = """els => els.map(el => {
                    let node = el.parentElement;
                    let container = null;
                    const linkText = el.innerText.trim().toLowerCase();
                    for (let i = 0; i < 6 && node; i++) {
                        const tag = node.tagName.toLowerCase();
                        const cls = node.className || '';
                        if (['li', 'article', 'tr', 'section'].includes(tag)) {
                            container = node; break;
                        }
                        const isBemSub = cls.includes('__');
                        const isJobContainer = /job|position|role|card|listing|result|item|vacancy|opening|posting|requisition/i.test(cls);
                        if (isJobContainer && !isBemSub) { container = node; break; }
                        const nodeText = node.innerText?.trim()?.toLowerCase() || '';
                        if (nodeText.length > linkText.length + 20) { container = node; break; }
                        node = node.parentElement;
                    }
                    return {
                        href: el.href,
                        text: el.innerText.trim(),
                        context: container?.innerText?.trim() ?? ''
                    };
                })"""

            raw_links: list[dict] = await page.eval_on_selector_all(
                "a[href]", link_extract_script
            )

            # Some ATSes (iCIMS, certain SuccessFactors embeds) render the job
            # list inside a same-origin iframe. Pull links from those too.
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    f_url = urlparse(frame.url)
                except Exception:
                    continue
                if not f_url.netloc or f_url.netloc != base_netloc:
                    continue
                try:
                    iframe_links: list[dict] = await frame.eval_on_selector_all(
                        "a[href]", link_extract_script
                    )
                except Exception:
                    continue
                raw_links.extend(iframe_links)

            await context.close()
            await browser.close()

        # ── Parse captured JSON responses ──
        json_jobs = self._extract_from_json_responses(captured, base_netloc, base_path_norm)

        # ── Parse DOM links ──
        dom_jobs = self._extract_from_dom_links(raw_links, base_netloc, base_path_norm)

        # Merge, dedupe by canonical ID. The same posting can surface twice
        # (once as a hash-anchor stub from the JSON parser when no real URL
        # was given, and once as a real /jobdetails?id=... link from the DOM).
        # Prefer URLs without a fragment over hash-stubs.
        merged_by_key: dict[str, Job] = {}
        for j in json_jobs + dom_jobs:
            key = _job_canonical_key(j.url)
            existing = merged_by_key.get(key)
            if existing is None:
                merged_by_key[key] = j
                continue
            if "#" in existing.url and "#" not in j.url:
                merged_by_key[key] = j
        return list(merged_by_key.values())

    def _extract_from_json_responses(
        self,
        responses: list[tuple[str, str]],
        base_netloc: str,
        base_path_norm: str,
    ) -> list[Job]:
        candidates: list[dict] = []
        for resp_url, body in responses:
            text = body.strip()
            if not text or text[0] not in "[{":
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            # Match against the URL *path* (not query) so query params like
            # "flexFieldsFacet" don't accidentally veto a real jobs endpoint.
            path_lower = urlparse(resp_url).path.lower()
            url_implies_jobs = any(kw in path_lower for kw in _JOB_RESPONSE_URL_KEYWORDS)
            if any(skip in path_lower for skip in ("/event", "/facet", "/locale", "/translation",
                                                    "/saved", "/recommend", "/notification",
                                                    "/globalsetting", "/setting")):
                continue
            candidates.extend(_walk_json(data, strict=not url_implies_jobs))

        if not candidates:
            return []

        jobs: list[Job] = []
        seen_urls: set[str] = set()
        base_root_domain = ".".join(base_netloc.rsplit(".", 2)[-2:])
        for obj in candidates:
            job = _build_job_from_obj(obj, self.company.careers_url)
            if not job:
                continue
            # Reject URLs that escape to an unrelated domain — JSON APIs
            # sometimes echo back marketing or partner links that aren't jobs.
            job_parsed_for_host = urlparse(job.url)
            if job_parsed_for_host.netloc:
                job_root_domain = ".".join(job_parsed_for_host.netloc.rsplit(".", 2)[-2:])
                if job_root_domain != base_root_domain:
                    continue
            # Reject items whose URL is essentially the base careers page
            # (same path AND no distinctive fragment / no job-id-bearing query).
            job_parsed = urlparse(job.url)
            same_path = _strip_locale_prefix(job_parsed.path) == base_path_norm
            has_distinctive = (
                bool(job_parsed.fragment)
                or any(qk in job_parsed.query.lower() for qk in _JOB_QUERY_PARAMS)
                or bool(_NUMERIC_ID_RE.search(job_parsed.query))
            )
            if same_path and not has_distinctive:
                continue
            # Location filter: prefer the JSON-provided location; if missing, accept (the API itself filtered).
            if job.location and not self.matches_location(job.location):
                continue
            if job.url in seen_urls:
                continue
            seen_urls.add(job.url)
            jobs.append(job)
        return jobs

    def _extract_from_dom_links(
        self,
        raw_links: list[dict],
        base_netloc: str,
        base_path_norm: str,
    ) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        for item in raw_links:
            href: str = item.get("href", "")
            text: str = item.get("text", "")
            context: str = item.get("context", "")
            if not href or not text:
                continue

            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc != base_netloc:
                continue

            # Skip same-page (incl. locale-only-different) navigation links.
            # Exception: query-string-routed ATSes (e.g. UBS TGnewUI) put job
            # IDs in the query while the path stays identical to the base. If
            # the link carries a distinctive job-id query or fragment, keep it.
            if _strip_locale_prefix(parsed.path) == base_path_norm:
                has_distinctive_qf = (
                    bool(parsed.fragment) and parsed.fragment not in ("", "0")
                    or any(qk in parsed.query.lower() for qk in _JOB_QUERY_PARAMS)
                    or bool(_NUMERIC_ID_RE.search(parsed.query))
                )
                if not has_distinctive_qf:
                    continue
            # Skip well-known navigation paths (saved jobs, alerts, login, etc).
            path_for_nav_check = parsed.path.lower()
            if any(nav in path_for_nav_check for nav in _NAV_PATH_KEYWORDS):
                continue
            # SmashFly/Phenom (and similar ATS) put facet/category/search-result
            # listing pages under /search/<facet>/... while real job detail pages
            # live at /jobs/<id>-<slug> at top level. Any link whose path starts
            # with /search/ (and isn't the base URL itself, already filtered
            # above) is a listing page, not a posting.
            if parsed.path.lower().startswith("/search/"):
                continue

            path_lower = parsed.path.lower()
            query_lower = parsed.query.lower()
            full_lower = f"{path_lower}?{query_lower}"
            has_strong_path = (
                any(kw in path_lower for kw in _STRONG_JOB_URL_KEYWORDS)
                or bool(_STRONG_JOB_PATH_RE.search(path_lower))
            )
            has_weak_path = any(kw in path_lower for kw in _WEAK_JOB_URL_KEYWORDS)
            has_job_query = any(qk in query_lower for qk in _JOB_QUERY_PARAMS)
            has_numeric_id = bool(_NUMERIC_ID_RE.search(full_lower)) or bool(_ALPHANUM_ID_RE.search(full_lower))
            # Accept iff: strong keyword present, OR job-query param, OR weak keyword + numeric ID.
            if not (has_strong_path or has_job_query or (has_weak_path and has_numeric_id)):
                continue
            # NOTE: a previous check rejected URLs whose tail slug was all-lowercase
            # with no digits (e.g. /jobs/data) on the assumption real job IDs are
            # mixed-case. That assumption breaks for HR-style Spanish slugs like
            # /property-manager/ or /consejero-financiero/. The title-text check
            # downstream (`_looks_like_real_title`) is sufficient to reject the
            # category-label cases this used to catch.

            title = _extract_title(text, url_hint=href)
            # If the link text itself is generic (e.g. "See the offer" /
            # "Apply"), try extracting from the surrounding container instead.
            if (not title or not _looks_like_real_title(title)) and context:
                title = _extract_title(context, url_hint=href)
            # Last-resort fallback: derive a readable title from the URL slug.
            if not title or not _looks_like_real_title(title):
                slug_title = _title_from_url_slug(href)
                if slug_title and _looks_like_real_title(slug_title):
                    title = slug_title
            if not title or not _looks_like_real_title(title):
                continue
            if len(title) > 120:
                continue

            # Accept if ANY of these signals match the location filter:
            #  - the URL path itself (e.g. /madrid-...)
            #  - the title text
            #  - the surrounding container text
            # When all three are silent on location we trust the careers_url's
            # own pre-filtering rather than rejecting.
            location_signals = [parsed.path, title, context]
            location_evidence = [s for s in location_signals if s]
            if location_evidence and not any(self.matches_location(s) for s in location_evidence):
                # If the surrounding context was substantive (>40 chars) and
                # didn't mention any expanded location term, treat as a hint
                # that this listing isn't in the target city. Otherwise allow.
                if context and len(context) > 40:
                    continue

            if href in seen_urls:
                continue
            seen_urls.add(href)
            jobs.append(Job(title=title, url=href))

        return jobs
