import os

import resend

from .models import Job


def send_digest(new_jobs: list[tuple[str, Job]]) -> None:
    """Send a single digest email listing all newly found jobs.

    Args:
        new_jobs: list of (company_name, Job) pairs, unsorted.
    """
    if not new_jobs:
        print("No new jobs — skipping digest email.")
        return

    resend.api_key = os.environ["RESEND_API_KEY"]

    sections: list[str] = []
    current_company: str | None = None

    for company_name, job in sorted(new_jobs, key=lambda x: x[0].lower()):
        if company_name != current_company:
            sections.append(f"<h3 style='margin-bottom:4px'>{company_name}</h3>")
            current_company = company_name

        badge = f"<span style='background:#e5e7eb;border-radius:3px;padding:1px 5px;font-size:11px'>{job.job_type}</span> " if job.job_type else ""
        dept = f" &middot; {job.department}" if job.department else ""
        loc = f"<br><small style='color:#6b7280'>{job.location}</small>" if job.location else ""

        sections.append(
            f"<p style='margin:4px 0 8px'>"
            f"{badge}<a href='{job.url}' style='color:#1d4ed8'>{job.title}</a>{dept}{loc}"
            f"</p>"
        )

    html = f"""
    <div style='font-family:sans-serif;max-width:600px;margin:0 auto'>
        <h2 style='border-bottom:1px solid #e5e7eb;padding-bottom:8px'>
            Job Tracker &mdash; {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''} found
        </h2>
        {''.join(sections)}
        <hr style='margin-top:24px;border:none;border-top:1px solid #e5e7eb'>
        <p style='color:#9ca3af;font-size:12px'>Filtered for Madrid, Spain</p>
    </div>
    """

    resend.Emails.send(
        {
            "from": os.environ["EMAIL_FROM"],
            "to": [os.environ["EMAIL_TO"]],
            "subject": f"Job Tracker: {len(new_jobs)} new job{'s' if len(new_jobs) != 1 else ''} found",
            "html": html,
        }
    )
    print(f"Digest sent to {os.environ['EMAIL_TO']}.")
