"""Local AI filter — runs candidate jobs through Ollama before email digest.

Reads `config/preferences.md` for the user's criteria and asks a local LLM
(default `qwen2.5:7b`) which jobs to keep. Uses Ollama's structured-output
support (JSON schema) so the response is guaranteed to validate.

Fail-open: if Ollama isn't reachable, the model isn't pulled, or the response
fails to parse, the input list is returned unchanged. Never blocks the email
on a filter error.

Hard rule baked into the system prompt: "when in doubt, KEEP". False negatives
(dropping a relevant role) are much worse than false positives.

Config via env vars:
  OLLAMA_HOST   — default http://localhost:11434
  OLLAMA_MODEL  — default qwen2.5:7b
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import ollama

from .models import Job

_DEFAULT_MODEL = "qwen2.5:7b"
_REQUEST_TIMEOUT_S = 600.0  # 10 min — generous for CPU inference on ~200 jobs
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
            },
        }
    },
    "required": ["decisions"],
}


def _load_preferences() -> str | None:
    if not _PREFERENCES_PATH.exists():
        return None
    text = _PREFERENCES_PATH.read_text(encoding="utf-8").strip()
    return text or None


async def filter_jobs(jobs: list[tuple[str, Job]]) -> list[tuple[str, Job]]:
    """Filter (company, job) pairs through Ollama using preferences.md as criteria.

    Returns the subset the model flagged as relevant, preserving input order.
    Fail-open on any error: returns the input list unchanged so the email still goes out.
    """
    if not jobs:
        return []

    preferences = _load_preferences()
    if not preferences:
        print(f"[ai_filter] {_PREFERENCES_PATH} missing or empty — passing through unfiltered.")
        return jobs

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", _DEFAULT_MODEL)

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

    client = ollama.AsyncClient(host=host, timeout=_REQUEST_TIMEOUT_S)
    try:
        response = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_PREAMBLE + preferences},
                {"role": "user", "content": user_text},
            ],
            format=_SCHEMA,
            options={"temperature": 0.0, "num_ctx": 32768},
        )
    except Exception as exc:
        print(f"[ai_filter] Ollama call failed ({type(exc).__name__}: {exc}) — passing through unfiltered.")
        return jobs

    text = (response.get("message") or {}).get("content") or ""
    if not text:
        print("[ai_filter] empty response — passing through unfiltered.")
        return jobs
    try:
        data = json.loads(text)
        decisions = data["decisions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"[ai_filter] parse failed ({exc}) — passing through unfiltered.")
        print(f"[ai_filter] raw response (first 500 chars): {text[:500]}")
        return jobs

    keep_urls = {d["url"] for d in decisions if d.get("keep")}
    eval_count_in = response.get("prompt_eval_count") or 0
    eval_count_out = response.get("eval_count") or 0
    total_duration_ms = (response.get("total_duration") or 0) // 1_000_000
    print(
        f"[ai_filter] {len(jobs)} -> {len(keep_urls)} kept "
        f"(input: {eval_count_in}t, output: {eval_count_out}t, "
        f"total: {total_duration_ms}ms, model: {model})"
    )

    return [(c, j) for (c, j) in jobs if j.url in keep_urls]
