"""AI-powered job filter — runs candidate jobs through Claude before email digest.

Reads `config/preferences.md` for the user's criteria and asks Claude which jobs
to keep. The system prompt + preferences are cached (prefix caching) so repeated
daily runs only pay the full token cost for the variable job list.

Fail-open: if `ANTHROPIC_API_KEY` is missing, the API call fails, or the response
fails to parse, the input list is returned unchanged. Never block the email on a
filter error.

Hard rule baked into the system prompt: "when in doubt, KEEP". False negatives
(dropping a relevant role) are much worse than false positives (keeping a
marginal one) for this user.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from .models import Job

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 16_000
_PREFERENCES_PATH = Path(__file__).parent.parent / "config" / "preferences.md"

_SYSTEM_PROMPT_PREAMBLE = """You are filtering job postings for a Madrid-based early-careers candidate.

For each job in the input, decide whether to KEEP or DROP it based on the user's preferences below.

CRITICAL DECISION RULE: When in doubt, KEEP the job. False negatives (dropping a relevant role) are MUCH worse than false positives (keeping a marginal one). If a job *might* match the user's interests, keep it. Only drop jobs that are clearly outside the user's areas of interest (e.g. retail floor staff, blue-collar roles, senior C-level positions, roles in unrelated industries like agriculture or fashion retail).

You will receive a JSON list of jobs with `company`, `title`, `url`, `location`, and `department`.

Output strictly valid JSON matching the provided schema: a `decisions` array with exactly one entry per input job, each containing the job's `url` (verbatim, as a stable key), `keep` (boolean), and a short `reason` (max 100 chars explaining the decision).

USER PREFERENCES (from preferences.md):
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["url", "keep", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def _load_preferences() -> str | None:
    if not _PREFERENCES_PATH.exists():
        return None
    text = _PREFERENCES_PATH.read_text(encoding="utf-8").strip()
    return text or None


async def filter_jobs(jobs: list[tuple[str, Job]]) -> list[tuple[str, Job]]:
    """Filter (company, job) pairs through Claude using preferences.md as criteria.

    Returns the subset Claude flagged as relevant, preserving input order.
    Fail-open on any error: returns the input list unchanged so the email still goes out.
    """
    if not jobs:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[ai_filter] ANTHROPIC_API_KEY not set — passing through unfiltered.")
        return jobs

    preferences = _load_preferences()
    if not preferences:
        print(f"[ai_filter] {_PREFERENCES_PATH} missing or empty — passing through unfiltered.")
        return jobs

    job_payload = [
        {
            "company": company,
            "title": j.title,
            "url": j.url,
            "location": j.location or "",
            "department": j.department or "",
        }
        for company, j in jobs
    ]
    user_text = (
        "Evaluate these jobs against the preferences and return one decision per job:\n\n"
        + json.dumps(job_payload, ensure_ascii=False, indent=2)
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT_PREAMBLE + preferences,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
    except Exception as exc:
        print(f"[ai_filter] API call failed ({type(exc).__name__}: {exc}) — passing through unfiltered.")
        return jobs

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        print("[ai_filter] empty response — passing through unfiltered.")
        return jobs
    try:
        data = json.loads(text)
        decisions = data["decisions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"[ai_filter] parse failed ({exc}) — passing through unfiltered.")
        return jobs

    keep_urls = {d["url"] for d in decisions if d.get("keep")}
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    print(
        f"[ai_filter] {len(jobs)} → {len(keep_urls)} kept "
        f"(input: {response.usage.input_tokens}t, cache_read: {cache_read}t, "
        f"cache_create: {cache_create}t, output: {response.usage.output_tokens}t)"
    )

    return [(c, j) for (c, j) in jobs if j.url in keep_urls]
