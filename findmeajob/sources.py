"""Fetch jobs from public ATS APIs. No auth, no scraping, no ToS risk."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict, field
from typing import Any, Iterable

import requests

UA = {"User-Agent": "findmeajob/1.0 (personal job search agent)"}
TIMEOUT = 20

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


@dataclass
class Job:
    job_id: str          # stable global id for dedupe: "<ats>:<slug>:<id>"
    ats: str
    company: str
    title: str
    location: str
    url: str
    description: str
    posted_at: str | None = None
    salary: str | None = None
    # filled in later by the pipeline
    score: float | None = None
    reason: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Adapters. Each takes the raw JSON body and returns list[Job].
# Keeping parse separate from HTTP is what makes offline testing possible.
# --------------------------------------------------------------------------

def parse_greenhouse(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        out.append(Job(
            job_id=f"greenhouse:{slug}:{j.get('id')}",
            ats="greenhouse",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("absolute_url") or "",
            description=strip_html(j.get("content")),
            posted_at=j.get("updated_at") or j.get("first_published"),
        ))
    return out


def parse_lever(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or []):
        cats = j.get("categories") or {}
        # Lever splits the JD across descriptionPlain + a `lists` array.
        chunks = [j.get("descriptionPlain") or strip_html(j.get("description"))]
        for lst in (j.get("lists") or []):
            chunks.append(str(lst.get("text") or ""))
            chunks.append(strip_html(lst.get("content")))
        chunks.append(j.get("additionalPlain") or strip_html(j.get("additional")))
        ts = j.get("createdAt")
        posted = None
        if isinstance(ts, (int, float)):
            posted = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
        out.append(Job(
            job_id=f"lever:{slug}:{j.get('id')}",
            ats="lever",
            company=company,
            title=(j.get("text") or "").strip(),
            location=(cats.get("location") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            description="\n\n".join(c for c in chunks if c).strip(),
            posted_at=posted,
            salary=cats.get("commitment"),
        ))
    return out


def parse_ashby(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        salary = None
        summary = comp.get("compensationTierSummary") or comp.get("summaryComponents")
        if isinstance(summary, str):
            salary = summary
        out.append(Job(
            job_id=f"ashby:{slug}:{j.get('id')}",
            ats="ashby",
            company=company,
            title=(j.get("title") or "").strip(),
            location=(j.get("location") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            description=(j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")) or "").strip(),
            posted_at=j.get("publishedAt"),
            salary=salary,
        ))
    return out


def parse_recruitee(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        city, country = j.get("city") or "", j.get("country") or ""
        loc = j.get("location") or ", ".join(x for x in [city, country] if x)
        if j.get("remote"):
            loc = f"{loc} (remote)".strip()
        # JD is split across description + requirements, both HTML.
        desc = "\n\n".join(strip_html(x) for x in
                           [j.get("description"), j.get("requirements")] if x)
        out.append(Job(
            job_id=f"recruitee:{slug}:{j.get('id')}",
            ats="recruitee",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("careers_url") or j.get("careers_apply_url") or "",
            description=desc.strip(),
            posted_at=j.get("published_at") or j.get("created_at"),
            salary=j.get("employment_type_code"),
        ))
    return out


def parse_workable(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        loc = j.get("location") or {}
        location = ", ".join(p for p in
                             [loc.get("city"), loc.get("region"), loc.get("country")] if p)
        if loc.get("telecommuting") or j.get("telecommuting"):
            location = f"{location} (remote)".strip() if location else "Remote"
        # details=true adds description/requirements/benefits as HTML.
        desc = "\n\n".join(strip_html(x) for x in
                           [j.get("description"), j.get("requirements"), j.get("benefits")] if x)
        out.append(Job(
            job_id=f"workable:{slug}:{j.get('shortcode') or j.get('id')}",
            ats="workable",
            company=company or (body or {}).get("name") or slug,
            title=(j.get("title") or "").strip(),
            location=location.strip(),
            url=j.get("url") or j.get("shortlink") or j.get("application_url") or "",
            description=desc.strip(),
            posted_at=j.get("created_at"),
            salary=j.get("employment_type"),
        ))
    return out


def parse_personio(slug: str, company: str, xml_text: str) -> list[Job]:
    """Personio ships a single XML feed with every position and its full JD."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for pos in root.iter("position"):
        chunks = []
        for jd in pos.iter("jobDescription"):
            name = (jd.findtext("name") or "").strip()
            value = strip_html(jd.findtext("value"))
            if value:
                chunks.append(f"{name}\n{value}" if name else value)
        out.append(Job(
            job_id=f"personio:{slug}:{(pos.findtext('id') or '').strip()}",
            ats="personio",
            company=company,
            title=(pos.findtext("name") or "").strip(),
            location=(pos.findtext("office") or "").strip(),
            url=f"https://{slug}.jobs.personio.com/job/{(pos.findtext('id') or '').strip()}",
            description="\n\n".join(chunks).strip(),
            posted_at=(pos.findtext("createdAt") or None),
            salary=(pos.findtext("employmentType") or None),
        ))
    return out


_SR_SECTIONS = ("companyDescription", "jobDescription", "qualifications",
                "additionalInformation")


def parse_smartrecruiters(slug: str, company: str, body: Any) -> list[Job]:
    """List endpoint only — it carries no JD, so description is filled later
    by hydrate() on the survivors of the prefilter."""
    out = []
    for j in (body or {}).get("content", []):
        if j.get("visibility") not in (None, "PUBLIC"):
            continue
        loc = j.get("location") or {}
        location = ", ".join(p for p in
                             [loc.get("city"), loc.get("region"), loc.get("country")] if p) \
            or (loc.get("fullLocation") or "")
        if loc.get("remote"):
            location = f"{location} (remote)".strip()
        elif loc.get("hybrid"):
            location = f"{location} (hybrid)".strip()
        out.append(Job(
            job_id=f"smartrecruiters:{slug}:{j.get('id')}",
            ats="smartrecruiters",
            company=company or (j.get("company") or {}).get("name") or slug,
            title=(j.get("name") or "").strip(),
            location=location.strip(),
            url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
            description="",
            posted_at=j.get("releasedDate"),
        ))
    return out


def smartrecruiters_description(detail: Any) -> str:
    """Pull the JD out of a SmartRecruiters posting-*detail* payload."""
    sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
    chunks = [strip_html((sections.get(k) or {}).get("text"))
              for k in _SR_SECTIONS if (sections.get(k) or {}).get("text")]
    return "\n\n".join(c for c in chunks if c).strip()


def parse_openjobdata(rows: Iterable[dict[str, Any]],
                      company: str = "OpenJobData") -> list[Job]:
    """Map OpenJobData's normalized rows into the local Job contract."""
    out = []
    for row in rows:
        if row.get("status") not in (None, "active"):
            continue
        location = ", ".join(str(row.get(k) or "").strip()
                              for k in ("city", "region", "country")
                              if row.get(k))
        workplace = str(row.get("workplace_type") or "").strip()
        if row.get("is_remote") or workplace.lower() == "remote":
            location = f"{location} (remote)".strip() if location else "Remote"
        out.append(Job(
            job_id=f"openjobdata:{row.get('id') or row.get('job_id')}",
            ats="openjobdata",
            company=str(row.get("company_name") or company),
            title=str(row.get("title") or "").strip(),
            location=location,
            url=str(row.get("apply_url") or "").strip(),
            description=strip_html(str(row.get("description") or "")),
            posted_at=str(row.get("posted_at") or "") or None,
            salary=str(row.get("salary") or "") or None,
        ))
    return out


ENDPOINTS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever":      ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby":      ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
    "recruitee":  ("https://{slug}.recruitee.com/api/offers/", parse_recruitee),
    "workable":   ("https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true", parse_workable),
}


def _fetch_personio(slug: str, company: str,
                    sess: requests.Session | Any) -> list[Job]:
    r = sess.get(f"https://{slug}.jobs.personio.com/xml", headers=UA, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"  ! personio/{slug} -> HTTP {r.status_code}")
        return []
    return parse_personio(slug, company, r.text)


def _fetch_smartrecruiters(slug: str, company: str,
                           sess: requests.Session | Any) -> list[Job]:
    base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    jobs: list[Job] = []
    offset = 0
    while True:
        r = sess.get(base, params={"limit": 100, "offset": offset},
                     headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"  ! smartrecruiters/{slug} -> HTTP {r.status_code}")
            break
        data = r.json()
        content = data.get("content") or []
        jobs.extend(parse_smartrecruiters(slug, company, data))
        offset += len(content)
        if not content or offset >= (data.get("totalFound") or 0):
            break
    return jobs


# ATSes that need more than one GET or a non-JSON body.
CUSTOM_FETCHERS = {
    "personio": _fetch_personio,
    "smartrecruiters": _fetch_smartrecruiters,
}


def _fetch_openjobdata(slug: str, company: str,
                       sess: requests.Session | Any) -> list[Job]:
    """Read the latest public minimal delta from OpenJobData's HF bucket."""
    del sess  # HfFileSystem handles the public object-storage connection.
    try:
        from huggingface_hub import HfFileSystem
        import pyarrow.parquet as pq
    except ImportError:
        print("  ! openjobdata requires huggingface-hub and pyarrow")
        return []
    try:
        fs = HfFileSystem()
        prefix = "buckets/Invicto69/Jobs-Dataset-bucket/data/minimal/changes"
        files = sorted(fs.glob(f"{prefix}/*.parquet"))
        if not files:
            print("  ! openjobdata -> no daily delta files found")
            return []
        latest = files[-1]
        print(f"  openjobdata latest delta: {latest.rsplit('/', 1)[-1]}")
        with fs.open(latest, "rb") as stream:
            table = pq.read_table(stream)
        rows = table.to_pylist()
        return parse_openjobdata(rows, company)
    except Exception as exc:
        print(f"  ! openjobdata -> {type(exc).__name__}: {exc}")
        return []


CUSTOM_FETCHERS["openjobdata"] = _fetch_openjobdata


def fetch_board(ats: str, slug: str, company: str | None = None,
                session: requests.Session | None = None) -> list[Job]:
    """Hit one company's public board. Returns [] on any failure (never raises)."""
    sess = session or requests
    if ats in CUSTOM_FETCHERS:
        try:
            return CUSTOM_FETCHERS[ats](slug, company or slug, sess)
        except Exception as e:  # dead slug, rate limit, network blip
            print(f"  ! {ats}/{slug} -> {type(e).__name__}: {e}")
            return []
    if ats not in ENDPOINTS:
        raise ValueError(f"unknown ATS: {ats}")
    url_tpl, parser = ENDPOINTS[ats]
    try:
        r = sess.get(url_tpl.format(slug=slug), headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"  ! {ats}/{slug} -> HTTP {r.status_code}")
            return []
        return parser(slug, company or slug, r.json())
    except Exception as e:  # dead slug, rate limit, network blip
        print(f"  ! {ats}/{slug} -> {type(e).__name__}: {e}")
        return []


def hydrate(jobs: list[Job], session: requests.Session | None = None) -> list[Job]:
    """Fill descriptions that require a second call (SmartRecruiters).

    Runs after the prefilter so we pay for a handful of survivors, not the
    whole board — an enterprise SmartRecruiters slug can list thousands of
    postings, almost all of which the title/location gate throws away.
    """
    sess = session or requests.Session()
    for j in jobs:
        if j.ats != "smartrecruiters" or j.description:
            continue
        _, slug, jid = j.job_id.split(":", 2)
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}"
        try:
            r = sess.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                j.description = smartrecruiters_description(r.json())
            else:
                print(f"  ! smartrecruiters detail {jid} -> HTTP {r.status_code}")
        except Exception as e:
            print(f"  ! smartrecruiters detail {jid} -> {type(e).__name__}: {e}")
        time.sleep(0.1)
    return jobs


def fetch_all(companies: Iterable[dict], sleep: float = 0.25) -> list[Job]:
    jobs: list[Job] = []
    session = requests.Session()
    for c in companies:
        got = fetch_board(c["ats"], c["slug"], c.get("name"), session=session)
        if got:
            print(f"  {c.get('name') or c['slug']:<28} {len(got):>4} jobs  ({c['ats']})")
        jobs.extend(got)
        time.sleep(sleep)
    return jobs
