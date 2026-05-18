"""Local AI filter — runs candidate jobs through Ollama before email digest.

Reads `config/preferences.md` for the user's criteria and asks a local LLM
(default `qwen2.5:7b`) which jobs to keep. Uses Ollama's structured-output
support (JSON schema) so the response is guaranteed to validate.

**Batching:** input is split into chunks of `_BATCH_SIZE` jobs (default 25).
Each chunk is a separate Ollama call. This keeps any single request small
enough to fit in CPU inference time + output-token budget, and limits the
blast radius if one call fails — only that chunk's jobs fall through
unfiltered, the rest still get filtered normally.

Fail-open semantics: if Ollama isn't reachable, a chunk times out, or a
chunk's response fails to parse, the jobs in that chunk get a
**passthrough decision** (`is_real=False`, `keep=True`). The caller shows
them in the email but does NOT persist the decision to DB — so the row's
`ai_keep` stays NULL and can be retried on a future run if desired.

Hard rule baked into the system prompt: "when in doubt, KEEP". False
negatives (dropping a relevant role) are much worse than false positives.

Config via env vars:
  OLLAMA_HOST   — default http://localhost:11434
  OLLAMA_MODEL  — default qwen2.5:7b
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import ollama

from .models import Job

_DEFAULT_MODEL = "qwen2.5:7b"
_BATCH_SIZE = 25
_REQUEST_TIMEOUT_S = 900.0  # 15 min per chunk — generous for CPU on 25 jobs
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


@dataclass
class FilterDecision:
    """One filter decision per input job.

    `is_real` distinguishes a real model decision from a passthrough fallback
    (when the chunk failed). The caller should persist only `is_real=True`
    decisions to the DB.
    """
    url: str
    keep: bool
    reason: str
    is_real: bool


def _load_preferences() -> str | None:
    if not _PREFERENCES_PATH.exists():
        return None
    text = _PREFERENCES_PATH.read_text(encoding="utf-8").strip()
    return text or None


async def _filter_batch(
    chunk: list[tuple[str, Job]],
    preferences: str,
    host: str,
    model: str,
    chunk_label: str,
) -> tuple[list[FilterDecision] | None, dict]:
    """Filter one chunk through Ollama.

    Returns (decisions, stats):
      - decisions: list of FilterDecision (one per input job), OR ``None`` on
        any error (the caller's contract is to build passthrough decisions on
        ``None``).
      - stats: dict with `input_t`, `output_t`, `duration_ms` for logging.
    """
    job_payload = [
        {
            "company": company,
            "title": j.title,
            "url": j.url,
            "location": j.location or "",
            "department": j.department or "",
        }
        for company, j in chunk
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
        print(f"[ai_filter] {chunk_label}: Ollama call failed ({type(exc).__name__}: {exc}) -- chunk passes through")
        return None, {}

    text = (response.get("message") or {}).get("content") or ""
    if not text:
        print(f"[ai_filter] {chunk_label}: empty response -- chunk passes through")
        return None, {}
    try:
        data = json.loads(text)
        raw_decisions = data["decisions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"[ai_filter] {chunk_label}: parse failed ({exc}) -- chunk passes through")
        print(f"[ai_filter] {chunk_label}: raw response (first 300 chars): {text[:300]}")
        return None, {}

    # Build decisions keyed by URL, then align to input chunk so we have one
    # decision per input job even if the model dropped or duplicated some.
    decisions_by_url = {d["url"]: d for d in raw_decisions if isinstance(d, dict) and "url" in d}
    decisions: list[FilterDecision] = []
    for _, j in chunk:
        d = decisions_by_url.get(j.url)
        if d is None:
            # Model didn't return a decision for this URL — passthrough.
            decisions.append(FilterDecision(url=j.url, keep=True, reason="missing_from_model_output", is_real=False))
        else:
            decisions.append(
                FilterDecision(
                    url=j.url,
                    keep=bool(d.get("keep")),
                    reason=str(d.get("reason") or ""),
                    is_real=True,
                )
            )

    stats = {
        "input_t": response.get("prompt_eval_count") or 0,
        "output_t": response.get("eval_count") or 0,
        "duration_ms": (response.get("total_duration") or 0) // 1_000_000,
    }
    return decisions, stats


async def filter_jobs(jobs: list[tuple[str, Job]]) -> list[FilterDecision]:
    """Filter (company, job) pairs through Ollama using preferences.md as criteria.

    Returns a list of FilterDecision in input order — exactly one per input
    job. On chunk failure (or missing preferences.md), produces passthrough
    decisions (`keep=True, is_real=False`) so the email still goes out and
    nothing is lost. The caller persists `is_real=True` decisions to DB.
    """
    if not jobs:
        return []

    preferences = _load_preferences()
    if not preferences:
        print(f"[ai_filter] {_PREFERENCES_PATH} missing or empty -- passing through unfiltered.")
        return [
            FilterDecision(url=j.url, keep=True, reason="preferences_missing", is_real=False)
            for _, j in jobs
        ]

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", _DEFAULT_MODEL)

    chunks = [jobs[i : i + _BATCH_SIZE] for i in range(0, len(jobs), _BATCH_SIZE)]
    total = len(jobs)
    print(f"[ai_filter] filtering {total} jobs in {len(chunks)} chunks of up to {_BATCH_SIZE} (model: {model})")

    all_decisions: list[FilterDecision] = []
    total_input_t = 0
    total_output_t = 0
    total_ms = 0
    failed_chunks = 0

    for idx, chunk in enumerate(chunks, 1):
        label = f"chunk {idx}/{len(chunks)}"
        chunk_decisions, stats = await _filter_batch(chunk, preferences, host, model, label)
        if chunk_decisions is None:
            # Chunk failed -- emit passthrough decisions for every job in the chunk.
            failed_chunks += 1
            for _, j in chunk:
                all_decisions.append(
                    FilterDecision(url=j.url, keep=True, reason="chunk_failed", is_real=False)
                )
        else:
            all_decisions.extend(chunk_decisions)
            kept_n = sum(1 for d in chunk_decisions if d.keep)
            total_input_t += stats.get("input_t", 0)
            total_output_t += stats.get("output_t", 0)
            total_ms += stats.get("duration_ms", 0)
            print(
                f"[ai_filter] {label}: {len(chunk)} -> {kept_n} kept "
                f"(in: {stats.get('input_t', 0)}t, out: {stats.get('output_t', 0)}t, "
                f"{stats.get('duration_ms', 0)}ms)"
            )

    final_kept = sum(1 for d in all_decisions if d.keep)
    real_count = sum(1 for d in all_decisions if d.is_real)
    print(
        f"[ai_filter] DONE: {total} -> {final_kept} kept "
        f"(real_decisions: {real_count}/{total}, failed_chunks: {failed_chunks}/{len(chunks)}, "
        f"total in: {total_input_t}t, out: {total_output_t}t, "
        f"wall: {total_ms / 1000:.1f}s)"
    )
    return all_decisions
