from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Dict, List

from jobfinder import config, storage
from jobfinder.models import Job

log = logging.getLogger(__name__)

_STYLE_WRAP = (
    'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
    'max-width:640px;margin:0 auto;background:#f6f8fa;padding:24px;'
)
_STYLE_CARD = (
    'background:#ffffff;border:1px solid #e1e4e8;border-radius:10px;'
    'margin-bottom:16px;overflow:hidden;'
)
_STYLE_COMPANY = (
    'background:#0b5394;color:#ffffff;padding:10px 16px;font-size:15px;'
    'font-weight:700;letter-spacing:.3px;'
)
_STYLE_ROW = 'padding:12px 16px;border-top:1px solid #f0f2f4;'
_STYLE_BTN = (
    'display:inline-block;background:#1a7f37;color:#ffffff;text-decoration:none;'
    'padding:6px 14px;border-radius:6px;font-size:13px;font-weight:600;'
)


def render_new_jobs_html(new_jobs: Dict[str, List[Job]]) -> str:
    total = sum(len(v) for v in new_jobs.values())
    parts = [
        f'<div style="{_STYLE_WRAP}">',
        '<h2 style="color:#24292f;margin:0 0 4px;">&#127775; New Job Postings</h2>',
        f'<p style="color:#57606a;margin:0 0 20px;">{total} new job'
        f'{"s" if total != 1 else ""} found &middot; '
        f'{datetime.now().strftime("%d %b %Y, %H:%M")}</p>',
    ]
    for company, jobs in sorted(new_jobs.items()):
        parts.append(f'<div style="{_STYLE_CARD}">')
        parts.append(
            f'<div style="{_STYLE_COMPANY}">{escape(company)} '
            f'<span style="opacity:.8;font-weight:400;">&middot; {len(jobs)} new</span></div>'
        )
        for job in jobs:
            closing = (
                f'<div style="color:#9a6700;font-size:12px;margin-top:2px;">'
                f'Closes: {escape(job.closing_date)}</div>'
                if job.closing_date and job.closing_date != "N/A" else ""
            )
            parts.append(
                f'<div style="{_STYLE_ROW}">'
                f'<div style="color:#24292f;font-size:14px;font-weight:600;'
                f'margin-bottom:6px;">{escape(job.title)}</div>'
                f'{closing}'
                f'<a href="{escape(job.url, quote=True)}" style="{_STYLE_BTN}">Apply &rarr;</a>'
                f'</div>'
            )
        parts.append('</div>')
    parts.append(
        '<p style="color:#8c959f;font-size:12px;text-align:center;margin-top:20px;">'
        'Job-Finder &middot; automated alert</p></div>'
    )
    return "".join(parts)


def render_error_html(failures: Dict[str, str], zero_warnings: List[str]) -> str:
    parts = [f'<div style="{_STYLE_WRAP}">',
             '<h2 style="color:#cf222e;margin:0 0 16px;">Job Scraper Problems</h2>']
    if failures:
        parts.append('<h3 style="color:#24292f;">Scrapers that failed</h3><ul>')
        for company, error in sorted(failures.items()):
            parts.append(f'<li><b>{escape(company)}</b>: {escape(error)}</li>')
        parts.append('</ul>')
    if zero_warnings:
        parts.append('<h3 style="color:#24292f;">Suspicious results</h3><ul>')
        for company in zero_warnings:
            parts.append(
                f'<li><b>{escape(company)}</b> returned 0 jobs but previously had '
                f'active listings &mdash; the site layout may have changed.</li>'
            )
        parts.append('</ul>')
    parts.append('</div>')
    return "".join(parts)


def send_email(subject: str, html: str, recipients: List[str]) -> None:
    msg = MIMEMultipart()
    msg["From"] = config.FROM_EMAIL
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT) as server:
        server.login(config.SMTP_USERNAME, config.get_smtp_password())
        server.sendmail(config.FROM_EMAIL, recipients, msg.as_string())
    log.info("Email sent: %s -> %s", subject, recipients)


def _send_and_log(conn, kind: str, subject: str, html: str, recipients: List[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        send_email(subject, html, recipients)
        storage.log_email(conn, now, kind, subject, recipients, True)
    except Exception as exc:
        log.error("Failed to send %s email: %s", kind, exc)
        storage.log_email(conn, now, kind, subject, recipients, False, str(exc))


def send_run_notifications(conn, result) -> None:
    if result.new_jobs:
        total = sum(len(v) for v in result.new_jobs.values())
        _send_and_log(
            conn, "alert", f"{total} New Job Posting{'s' if total != 1 else ''}",
            render_new_jobs_html(result.new_jobs), config.ALERT_RECIPIENTS,
        )
    if result.failures or result.zero_warnings:
        _send_and_log(
            conn, "error", "Job Scraper Error Notification",
            render_error_html(result.failures, result.zero_warnings),
            config.ERROR_RECIPIENTS,
        )
