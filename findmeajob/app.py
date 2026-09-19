"""findmeajob CLI: profile -> fetch -> prefilter -> screen -> draft -> digest -> mail.

The agent never submits an application. It finds, filters, ranks and drafts.
A human reads the digest, edits the note, and presses submit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from . import report as report_mod
from . import ai, notify
from .sources import fetch_all, hydrate
from .samples import fetch_all_mock
from .filters import prefilter
from .backends import LLMError, resolve

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: str = ".env") -> None:
    """Minimal .env reader so there is no python-dotenv dependency."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cfg(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"config not found: {p}  (run from the project root)")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _load_profile(cfg: dict, allow_sample: bool) -> dict | None:
    path = Path(cfg.get("profile_file", "profile.json"))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    sample = ROOT / "profile.example.json"
    if allow_sample and sample.exists():
        print(f"  ! {path} missing — using {sample.name} for this dry run.")
        print("    Build the real one: python -m findmeajob profile --resume resume.pdf")
        return json.loads(sample.read_text(encoding="utf-8"))

    print(f"missing {path} — run `python -m findmeajob profile --resume <file>` first")
    return None


# ------------------------------------------------------------------ profile --
def cmd_profile(args) -> int:
    src = Path(args.resume)
    if not src.exists():
        print(f"resume not found: {src}")
        return 1
    is_pdf = src.suffix.lower() == ".pdf"
    is_docx = src.suffix.lower() == ".docx"

    try:
        provider, model = resolve("draft")
        print(f"reading {src.name} via {provider.name}/{model} ...")
        profile = ai.build_profile(
            resume_bytes=src.read_bytes() if is_pdf else None,
            resume_text=(ai.extract_docx_text(src.read_bytes()) if is_docx
                         else None if is_pdf else src.read_text(
                             encoding="utf-8", errors="replace")),
            is_pdf=is_pdf, provider=provider, model=model,
        )
    except (LLMError, ValueError) as e:
        print(f"profile extraction failed: {e}")
        return 1

    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"wrote {args.out}\n")
    print(json.dumps(profile, indent=2, ensure_ascii=False)[:900])
    return 0


# ---------------------------------------------------------------------- run --
def cmd_run(args) -> int:
    cfg = _cfg(args.config)
    profile = _load_profile(cfg, allow_sample=args.mock)
    if profile is None:
        return 1
    filters = cfg.get("filters", {}) or {}
    profile_locations = profile.get("preferred_locations") or profile.get("locations") or []
    if profile_locations:
        filters = dict(filters)
        filters["preferred_locations"] = profile_locations

    # ---- 1. fetch
    print("\n[1/5] fetching boards")
    if args.mock:
        jobs = fetch_all_mock()
    else:
        companies = _cfg(cfg.get("companies_file", "companies.yaml")).get("companies") or []
        if not companies:
            print("companies.yaml has no entries")
            return 1
        jobs = fetch_all(companies)
    scanned = len(jobs)
    if not scanned:
        print("no postings fetched — check the slugs in companies.yaml")
        return 1

    # ---- 2. prefilter (deterministic, free, no LLM)
    print("\n[2/5] filtering")
    jobs = prefilter(jobs, filters)
    passed_filters = len(jobs)
    print(f"  matching jobs: {len(jobs)}")
    candidates = len(jobs)
    if args.limit:
        jobs = jobs[:args.limit]
        print(f"  --limit {args.limit} applied")

    # Some boards (SmartRecruiters) omit the JD from their list endpoint; pull
    # it now, after the cut, so we fetch a handful of details, not the board.
    if not args.mock and jobs:
        hydrate(jobs)

    if not jobs:
        subject, doc = report_mod.build([], scanned, 0, {})
        path = report_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
        print(f"\nnothing new today. preview: {path}")
        return 0

    # ---- 3. screen
    scorer = "keyword" if args.scorer == "keyword" else "llm"
    if scorer == "keyword":
        print(f"\n[3/5] screening {len(jobs)} jobs (keyword stub — DEV ONLY)")
        ai.keyword_screen(jobs, profile)
    else:
        try:
            provider, model = resolve("screen")
        except LLMError as e:
            print(f"\n{e}\nNo key? Run with --scorer keyword for an offline dry run.")
            return 1
        print(f"\n[3/5] screening {len(jobs)} jobs via {provider.name}/{model}")
        ai.screen(jobs, profile,
                   batch_size=int(cfg.get("screen_batch_size", 8)),
                   jd_chars=int(cfg.get("screen_jd_chars", 1400)),
                   provider=provider, model=model)

    # If every batch failed, the digest would be empty and — worse — we would
    # record these jobs as seen and never show them again. Bail instead.
    if scorer == "llm" and not any(j.score is not None for j in jobs):
        print("\n! screening scored nothing: every batch failed.\n"
              "  Not recording these jobs, so the next run retries them.\n"
              "  Check the warnings above (bad key, rate limit, wrong model id).")
        return 1

    threshold = float(cfg.get("score_threshold", 7.0))
    top_n = int(cfg.get("max_per_digest", 5))
    shortlist = sorted([j for j in jobs if (j.score or 0) >= threshold],
                       key=lambda j: j.score or 0, reverse=True)[:top_n]
    print(f"  {len(shortlist)} scored >= {threshold}")

    # ---- 4. draft
    print(f"\n[4/5] drafting kits for {len(shortlist)}")
    if not shortlist:
        print("  nothing cleared the threshold")
    elif scorer == "keyword" or args.no_draft:
        print("  skipped (keyword scorer / --no-draft)")
    else:
        try:
            provider, model = resolve("draft")
            print(f"  via {provider.name}/{model}")
            ai.draft(shortlist, profile,
                      jd_chars=int(cfg.get("draft_jd_chars", 6000)),
                      provider=provider, model=model)
        except LLMError as e:
            print(f"  ! drafting unavailable: {e}")

    # ---- 5. digest
    print("\n[5/5] digest")
    subject, doc = report_mod.build(shortlist, scanned, candidates, {})
    path = report_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
    print(f"  wrote {path}")
    if getattr(args, "web_job_id", None):
        data_path = Path("out") / "customize" / f"{args.web_job_id}.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data = {j.job_id: j.to_dict() for j in shortlist}
        for item in data.values():
            item["resume_path"] = args.resume_path
        data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    sent = False
    if args.send:
        try:
            notify.send(subject, doc)
            sent = True
        except Exception as e:  # bad app password, blocked port, offline
            print(f"  ! email failed ({type(e).__name__}: {e}) — digest still on disk")
    else:
        print("  --send not passed, email skipped")


    print(f"\nfunnel: {scanned} scanned -> {passed_filters} passed filters "
          f"-> {candidates} new -> {len(shortlist)} in digest")
    print(f"subject: {subject}")
    return 0


def cmd_serve(args) -> int:
    try:
        from .web import run_server
    except ImportError:
        print("Flask is not installed. Run: pip install flask")
        return 1
    run_server(host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    _load_env()
    p = argparse.ArgumentParser(
        prog="findmeajob",
        description="Personal job-search agent. Finds and drafts; never submits.")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("profile", help="turn a resume into profile.json")
    sp.add_argument("--resume", required=True, help="path to a .pdf, .txt or .md resume")
    sp.add_argument("--out", default="profile.json")
    sp.set_defaults(func=cmd_profile)

    sr = sub.add_parser("run", help="run the daily pipeline")
    sr.add_argument("--mock", action="store_true", help="bundled fixtures, no network")
    sr.add_argument("--scorer", choices=["llm", "keyword", "claude"], default="llm",
                    help="keyword = offline stub, needs no API key ('claude' is an "
                         "alias for 'llm', kept for older docs)")
    sr.add_argument("--no-draft", action="store_true", help="skip the expensive stage")
    sr.add_argument("--send", action="store_true", help="actually email the digest")
    sr.add_argument("--limit", type=int, help="cap jobs sent to the LLM (cost guard)")
    sr.set_defaults(func=cmd_run)

    sv = sub.add_parser("serve", help="launch the web UI (upload resume, get a digest)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=5000)
    sv.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
