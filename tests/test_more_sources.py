"""Parsers for the added ATS providers, run against each vendor's native shape.

Fixtures are trimmed copies of real responses (SmartRecruiters BoschGroup,
Personio /xml, Recruitee /api/offers, Workable widget). No network, no keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from findmeajob.sources import (
    parse_personio,
    parse_recruitee,
    parse_smartrecruiters,
    parse_workable,
    smartrecruiters_description,
)


# ---------------------------------------------------------------- recruitee ---

RECRUITEE = {"offers": [
    {"id": 101, "title": "Backend Engineer", "status": "published",
     "location": "Berlin, Germany", "city": "Berlin", "country": "Germany",
     "remote": True, "employment_type_code": "fulltime",
     "careers_url": "https://acme.recruitee.com/o/backend-engineer",
     "description": "<p>Own our <b>Go</b> services.</p>",
     "requirements": "<ul><li>3+ years backend</li></ul>",
     "published_at": "2026-09-15T10:00:00.000Z"},
    # draft: must be skipped
    {"id": 102, "title": "Sales Lead", "status": "draft",
     "location": "Berlin", "careers_url": "https://acme.recruitee.com/o/x"},
]}


def test_recruitee_maps_fields_and_marks_remote():
    jobs = parse_recruitee("acme", "Acme", RECRUITEE)
    assert len(jobs) == 1                        # draft dropped
    j = jobs[0]
    assert j.job_id == "recruitee:acme:101"
    assert j.location == "Berlin, Germany (remote)"
    assert "Own our Go services." in j.description   # description HTML
    assert "3+ years backend" in j.description        # requirements HTML
    assert j.url.endswith("/o/backend-engineer")


# ----------------------------------------------------------------- workable ---

WORKABLE = {"name": "Acme", "jobs": [
    {"shortcode": "ABC123", "title": "Platform Engineer",
     "employment_type": "Full-time",
     "location": {"city": "Bangalore", "region": "KA", "country": "India",
                  "telecommuting": False},
     "url": "https://apply.workable.com/acme/j/ABC123/",
     "description": "<p>Run the platform.</p>",
     "requirements": "<p>Kubernetes.</p>",
     "created_at": "2026-09-14T09:00:00Z"},
    {"shortcode": "DEF456", "title": "SRE",
     "location": {"country": "United States", "telecommuting": True},
     "url": "https://apply.workable.com/acme/j/DEF456/",
     "description": "<p>On-call.</p>", "created_at": "2026-09-13T09:00:00Z"},
]}


def test_workable_builds_location_and_remote_and_id():
    jobs = parse_workable("acme", "Acme", WORKABLE)
    plat = next(j for j in jobs if j.title == "Platform Engineer")
    assert plat.job_id == "workable:acme:ABC123"
    assert plat.location == "Bangalore, KA, India"
    assert "Run the platform." in plat.description
    assert "Kubernetes." in plat.description

    sre = next(j for j in jobs if j.title == "SRE")
    assert sre.location == "United States (remote)"


# ----------------------------------------------------------------- personio ---

PERSONIO_XML = """<?xml version="1.0" encoding="utf-8"?>
<workzag-jobs>
  <position>
    <id>275560</id>
    <name>Site Reliability Engineer</name>
    <office>Bengaluru</office>
    <employmentType>permanent</employmentType>
    <jobDescriptions>
      <jobDescription>
        <name>Your Tasks</name>
        <value><![CDATA[<p>Run production.</p>]]></value>
      </jobDescription>
      <jobDescription>
        <name>Your Profile</name>
        <value><![CDATA[<ul><li>Linux, Go</li></ul>]]></value>
      </jobDescription>
    </jobDescriptions>
    <createdAt>2026-09-10T09:25:04+00:00</createdAt>
  </position>
</workzag-jobs>"""


def test_personio_parses_xml_and_concatenates_descriptions():
    jobs = parse_personio("acme", "Acme", PERSONIO_XML)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "personio:acme:275560"
    assert j.title == "Site Reliability Engineer"
    assert j.location == "Bengaluru"
    assert j.url == "https://acme.jobs.personio.com/job/275560"
    assert "Run production." in j.description
    assert "Linux, Go" in j.description
    assert j.posted_at == "2026-09-10T09:25:04+00:00"


def test_personio_bad_xml_returns_empty():
    assert parse_personio("acme", "Acme", "not xml <<<") == []


# ------------------------------------------------------------ smartrecruiters ---

SR_LIST = {"offset": 0, "limit": 100, "totalFound": 2, "content": [
    {"id": "744000150470642", "name": "Software Engineer II",
     "company": {"identifier": "Acme", "name": "Acme"},
     "releasedDate": "2026-09-18T23:48:13.386Z", "visibility": "PUBLIC",
     "location": {"city": "Bengaluru", "region": "KA", "country": "in",
                  "remote": False, "hybrid": True}},
    # not public: must be skipped
    {"id": "999", "name": "Hidden Role", "visibility": "PRIVATE",
     "location": {"city": "Nowhere"}},
]}

SR_DETAIL = {"id": "744000150470642", "name": "Software Engineer II",
             "jobAd": {"sections": {
                 "companyDescription": {"title": "Company", "text": "<p>We build edge.</p>"},
                 "jobDescription": {"title": "Job", "text": "<p>Own <b>Go</b> services.</p>"},
                 "qualifications": {"title": "Quals", "text": "<ul><li>3+ yrs</li></ul>"},
                 "additionalInformation": {"title": "More", "text": ""},
             }}}


def test_smartrecruiters_list_has_no_description_but_keeps_meta():
    jobs = parse_smartrecruiters("Acme", "Acme", SR_LIST)
    assert len(jobs) == 1                        # PRIVATE dropped
    j = jobs[0]
    assert j.job_id == "smartrecruiters:Acme:744000150470642"
    assert j.location == "Bengaluru, KA, in (hybrid)"
    assert j.url == "https://jobs.smartrecruiters.com/Acme/744000150470642"
    assert j.description == ""                    # hydrate() fills this later


def test_smartrecruiters_description_pulls_and_orders_sections():
    desc = smartrecruiters_description(SR_DETAIL)
    assert "We build edge." in desc
    assert "Own Go services." in desc
    assert "3+ yrs" in desc
    # empty additionalInformation contributes nothing
    assert desc.index("We build edge.") < desc.index("Own Go services.")
