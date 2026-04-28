import os
from datetime import datetime, timezone

from supabase import Client, create_client

from .models import Job


def get_client() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def get_or_create_company(client: Client, name: str, careers_url: str | None, ats_platform: str) -> str:
    result = client.table("companies").select("id").eq("name", name).execute()
    if result.data:
        return result.data[0]["id"]

    inserted = (
        client.table("companies")
        .insert({"name": name, "careers_url": careers_url, "ats_platform": ats_platform})
        .execute()
    )
    return inserted.data[0]["id"]


def upsert_jobs(client: Client, company_id: str, jobs: list[Job]) -> list[Job]:
    """Upsert scraped jobs; return only the ones that are genuinely new.

    For existing jobs: updates last_seen_at and re-sets is_active = true.
    For jobs that were in DB but absent from this scrape: marks is_active = false.
    """
    if not jobs:
        return []

    now = datetime.now(timezone.utc).isoformat()

    existing_result = (
        client.table("jobs")
        .select("url")
        .eq("company_id", company_id)
        .execute()
    )
    existing_urls: set[str] = {row["url"] for row in (existing_result.data or [])}
    new_jobs = [j for j in jobs if j.url not in existing_urls]

    rows = [
        {
            "company_id": company_id,
            "external_id": j.external_id,
            "title": j.title,
            "url": j.url,
            "location": j.location,
            "department": j.department,
            "job_type": j.job_type,
            "description": j.description,
            "is_active": True,
            "last_seen_at": now,
        }
        for j in jobs
    ]
    client.table("jobs").upsert(rows, on_conflict="company_id,url").execute()

    stale_urls = existing_urls - {j.url for j in jobs}
    if stale_urls:
        client.table("jobs").update({"is_active": False}).in_("url", list(stale_urls)).eq("company_id", company_id).execute()

    return new_jobs


def start_scrape_run(client: Client) -> str:
    result = client.table("scrape_runs").insert({"status": "running"}).execute()
    return result.data[0]["id"]


def finish_scrape_run(client: Client, run_id: str, new_jobs_found: int, errors: list[dict]) -> None:
    client.table("scrape_runs").update(
        {
            "status": "completed" if not errors else "failed",
            "new_jobs_found": new_jobs_found,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "errors": errors or None,
        }
    ).eq("id", run_id).execute()
