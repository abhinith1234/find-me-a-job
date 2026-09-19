from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from findmeajob import ai, report, web
from findmeajob.sources import Job


class CustomizeStub:
    def __init__(self):
        self.calls = []

    def complete(self, model, system, user, max_tokens, json_mode=False):
        self.calls.append(user)
        if len(self.calls) == 1:
            return json.dumps({
                "target_summary": "Target",
                "target_skills": ["Python"],
                "target_experience_themes": ["APIs"],
                "target_resume": "Target outline",
            })
        return json.dumps({
            "positioning_summary": "Lead with APIs",
            "keep": ["Python"],
            "rewrite_suggestions": ["Move API work up"],
            "gaps": ["No stated scale"],
            "tailored_resume": "Actual evidence only",
            "truth_check": ["Verify every metric"],
        })


def test_customize_resume_uses_jd_then_actual_resume():
    provider = CustomizeStub()
    job = Job("greenhouse:test:1", "greenhouse", "Test", "Backend Engineer",
              "Remote", "https://example.com", "Build Python APIs.")

    result = ai.customize_resume(job, resume_text="Python API engineer",
                                 provider=provider, model="stub")

    assert len(provider.calls) == 2
    assert "JOB DESCRIPTION" in provider.calls[0]
    assert '"target_summary"' in provider.calls[1]
    assert result["comparison"]["truth_check"] == ["Verify every metric"]


def test_digest_keeps_apply_action_and_has_customizer_link(monkeypatch):
    monkeypatch.setenv("CUSTOMIZE_BASE_URL", "http://127.0.0.1:5000")
    monkeypatch.setenv("CUSTOMIZE_RUN_ID", "run-1")
    job = Job("greenhouse:test:1", "greenhouse", "Test", "Backend Engineer",
              "Remote", "https://example.com", "Build Python APIs.")

    html = report.build([job], 1, 1, {})[1]

    assert "Open &amp; apply" in html
    assert "/customize/run-1/greenhouse:test:1" in html


def test_customize_page_loads_the_selected_job(tmp_path, monkeypatch):
    run_id = "run-1"
    job_id = "greenhouse:test:1"
    web.JOBS.clear()
    web.JOBS[run_id] = {"state": "done", "customize": {}}
    monkeypatch.setattr(web, "CUSTOMIZE_DATA", tmp_path)
    (tmp_path / f"{run_id}.json").write_text(json.dumps({job_id: {
        "job_id": job_id,
        "title": "Backend Engineer",
        "company": "Test",
        "location": "Remote",
        "description": "Build Python APIs.",
    }}), encoding="utf-8")

    response = web.create_app().test_client().get(
        f"/customize/{run_id}/{job_id}")

    assert response.status_code == 200
    assert b"Customize resume for Backend Engineer" in response.data
