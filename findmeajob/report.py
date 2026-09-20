"""Build the daily HTML digest. Inline CSS only — Gmail strips <style> blocks."""
from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path

from .sources import Job

BG = "#f3f7f4"
CARD = "#ffffff"
LINE = "#dce8df"
TEXT = "#173126"
MUTED = "#60756a"
ACCENT = "#138a4b"
PALE_GREEN = "#e8f5ed"
DEEP_GREEN = "#0b5d32"


def _badge(score: float | None) -> str:
    return f'<span style="display:inline-block;background:#bde8cb;color:{DEEP_GREEN};font-weight:800;padding:5px 10px;border-radius:999px;font-size:13px;">{score or 0:.1f}/10</span>'


def _bullets(items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(
        f'<li style="margin:0 0 6px 0;color:{TEXT};font-size:14px;line-height:1.5;">'
        f'{html.escape(str(i))}</li>' for i in items)
    return f'<ul style="margin:8px 0 0 0;padding-left:18px;">{lis}</ul>'


def _section(label: str, body: str) -> str:
    if not body:
        return ""
        return (f'<div style="margin-top:16px;">'
          f'<div style="color:{DEEP_GREEN};font-size:11px;letter-spacing:.08em;'
          f'text-transform:uppercase;font-weight:800;">{label}</div>{body}</div>')


def _card(j: Job) -> str:
    d = j.draft or {}
    meta = " · ".join(x for x in [j.company, j.location or "—", j.ats] if x)

    para = lambda t: (f'<p style="margin:8px 0 0 0;color:{TEXT};font-size:14px;'
                      f'line-height:1.6;">{html.escape(t)}</p>') if t else ""

    cover = d.get("cover_note")
    cover_html = ""
    if cover:
        cover_html = _section("Cover note (edit before sending)",
            f'<div style="margin-top:8px;padding:14px;background:{PALE_GREEN};'
            f'border:1px solid {LINE};border-radius:8px;color:{TEXT};font-size:14px;'
            f'line-height:1.6;white-space:pre-wrap;">{html.escape(cover)}</div>')

    return f"""
<div style="background:{CARD};border:1px solid {LINE};border-left:5px solid {ACCENT};border-radius:12px;padding:20px;margin-bottom:16px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div style="font-size:18px;font-weight:800;color:{TEXT};">{html.escape(j.title)}</div>
    <div style="padding-left:12px;">{_badge(j.score)}</div>
  </div>
  <div style="color:{MUTED};font-size:13px;margin-top:7px;">{html.escape(meta)}</div>
  {para(j.reason or "")}
  {_section("Why it fits", para(d.get("fit_summary", "")))}
  {_section("Resume bullets for this role", _bullets(d.get("tailored_bullets", [])))}
  {_section("Honest gaps", _bullets(d.get("gaps", [])))}
  {cover_html}
  {_section("Ask them", _bullets(d.get("questions_to_ask", [])))}
  <div style="margin-top:16px;">
     <a href="{html.escape(j.url)}" style="display:inline-block;background:{ACCENT};
       color:#ffffff;font-weight:800;font-size:14px;text-decoration:none;
       padding:10px 18px;border-radius:8px;">Open &amp; apply →</a>
    {f'<a href="{html.escape(os.getenv("CUSTOMIZE_BASE_URL", "").rstrip("/") + "/customize/" + os.getenv("CUSTOMIZE_RUN_ID", "") + "/" + j.job_id)}" style="display:inline-block;background:{PALE_GREEN};color:{DEEP_GREEN};font-weight:800;font-size:14px;text-decoration:none;padding:10px 18px;border-radius:8px;margin-left:8px;">Customize resume</a>' if os.getenv("CUSTOMIZE_BASE_URL") and os.getenv("CUSTOMIZE_RUN_ID") else ''}
    <span style="color:{MUTED};font-size:11px;margin-left:10px;">{html.escape(j.job_id)}</span>
  </div>
</div>"""


def build(jobs: list[Job], scanned: int, candidates: int, stats: dict) -> tuple[str, str]:
    today = datetime.now().strftime("%d %b %Y")
    subject = (f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} worth your time — {today}"
               if jobs else f"No new matches today — {today}")

    if jobs:
        body = "".join(_card(j) for j in jobs)
    else:
        body = (f'<div style="background:{CARD};border:1px solid {LINE};border-radius:12px;'
                f'padding:24px;color:{MUTED};font-size:14px;">Scanned {scanned} postings, '
                f'nothing cleared the bar today. Boards are quiet on weekends.</div>')

    html_doc = f"""<!doctype html><html><body style="margin:0;padding:0;background:{BG};
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:{TEXT};">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;">
  <div style="background:{DEEP_GREEN};border-radius:16px;padding:24px 22px;margin-bottom:18px;">
    <div style="color:#bde8cb;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;">Find Me A Job</div>
    <div style="color:#ffffff;font-size:28px;font-weight:800;margin-top:7px;">Your job matches</div>
    <div style="color:#d9f4e2;font-size:13px;margin-top:8px;line-height:1.5;">Curated from public job boards and matched against your profile.</div>
  </div>
  <div style="background:{CARD};border:1px solid {LINE};border-radius:12px;padding:14px 16px;margin-bottom:18px;color:{MUTED};font-size:13px;">
    {today} · scanned {scanned} postings · {candidates} passed filters ·
    {len(jobs)} made the cut<br>
  </div>
  {body}
  <div style="color:{MUTED};font-size:11px;line-height:1.6;margin-top:22px;
       border-top:1px solid {LINE};padding-top:14px;">
    Drafts are starting points, not send-ready. Read the JD, edit the note,
    then submit it yourself.
  </div>
</div></body></html>"""
    return subject, html_doc


def write(html_doc: str, path: str | Path = "out/digest.html") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
    return path


def write_xlsx(jobs: list[Job], path: str | Path = "out/filtered-jobs.xlsx") -> Path:
    """Write the filtered jobs to an Excel sheet, for the email attachment."""
    from openpyxl import Workbook

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Filtered jobs"
    headers = ["job_id", "company", "title", "location", "score", "url", "description"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = cell.font.copy(bold=True)
    for j in jobs:
        ws.append([j.job_id, j.company, j.title, j.location or "", j.score or "",
                   j.url, j.description])
    widths = [26, 20, 30, 18, 8, 40, 60]
    for col, width in zip(ws.columns, widths):
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(path)
    return path
