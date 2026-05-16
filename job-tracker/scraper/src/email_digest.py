import os

import resend

from .models import Job


def _render_section(title: str, jobs: list[tuple[str, Job]]) -> str:
    if not jobs:
        return f"<h3 style='margin:24px 0 4px;color:#374151'>{title}</h3><p style='color:#9ca3af;font-size:13px'>Sin novedades.</p>"

    parts: list[str] = [f"<h3 style='margin:24px 0 4px;color:#374151'>{title} &mdash; {len(jobs)}</h3>"]
    current_company: str | None = None
    for company_name, job in sorted(jobs, key=lambda x: x[0].lower()):
        if company_name != current_company:
            parts.append(f"<h4 style='margin:14px 0 2px;color:#111827'>{company_name}</h4>")
            current_company = company_name

        badge = (
            f"<span style='background:#e5e7eb;border-radius:3px;padding:1px 5px;font-size:11px'>{job.job_type}</span> "
            if job.job_type else ""
        )
        dept = f" &middot; {job.department}" if job.department else ""
        loc = f"<br><small style='color:#6b7280'>{job.location}</small>" if job.location else ""
        parts.append(
            f"<p style='margin:4px 0 8px'>"
            f"{badge}<a href='{job.url}' style='color:#1d4ed8'>{job.title}</a>{dept}{loc}"
            f"</p>"
        )
    return "".join(parts)


def send_digest(new_today: list[tuple[str, Job]], last_7_days: list[tuple[str, Job]]) -> None:
    """Send the daily digest email with two sections.

    Args:
        new_today: jobs first seen in today's scrape (already AI-filtered).
        last_7_days: jobs first seen in the last 7 days (already AI-filtered).
            Section B intentionally includes today's new jobs as well.
    """
    if not new_today and not last_7_days:
        print("No jobs in either section — skipping digest email.")
        return

    resend.api_key = os.environ["RESEND_API_KEY"]

    section_a = _render_section("Nuevos hoy", new_today)
    section_b = _render_section("Últimos 7 días", last_7_days)

    subject_total = len(new_today)
    subject = (
        f"Job Tracker: {subject_total} nuevo{'s' if subject_total != 1 else ''} hoy"
        if new_today else
        f"Job Tracker: 0 nuevos hoy · {len(last_7_days)} activos esta semana"
    )

    html = f"""
    <div style='font-family:sans-serif;max-width:640px;margin:0 auto'>
        <h2 style='border-bottom:1px solid #e5e7eb;padding-bottom:8px'>Job Tracker</h2>
        {section_a}
        {section_b}
        <hr style='margin-top:24px;border:none;border-top:1px solid #e5e7eb'>
        <p style='color:#9ca3af;font-size:12px'>Filtrado por IA según config/preferences.md. Madrid (+ London cuando aplica).</p>
    </div>
    """

    resend.Emails.send(
        {
            "from": os.environ["EMAIL_FROM"],
            "to": [os.environ["EMAIL_TO"]],
            "subject": subject,
            "html": html,
        }
    )
    print(f"Digest sent to {os.environ['EMAIL_TO']} (A={len(new_today)}, B={len(last_7_days)}).")
