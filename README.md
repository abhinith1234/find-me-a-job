# Find Me A Job

A personal job-search agent. It reads public ATS APIs every morning, throws away
the ~99% that don't fit you, scores what's left against your resume, drafts an
application kit for the best few, and emails you a digest.

**It never submits an application.** It finds, filters, ranks and drafts. You
read the digest, edit the cover note, and press submit yourself.

```
2000 postings  →  40 candidates  →  5 in your inbox
   fetch          regex/location      LLM screen
                  /freshness gate     + draft
                  (free, no LLM)
```

---

## Quick setup

The setup scripts create a project-local virtual environment, install all
dependencies, and keep your global Python installation untouched.

### macOS/Linux

```bash
./setup.sh
./run.sh
```

Open http://127.0.0.1:5000. Choose **Ollama local model** in the UI for a
token-free setup, or choose Gemini/Hugging Face and enter that provider's key.

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

Open http://127.0.0.1:5000. The scripts use `.venv`, so activation is not
required. Install Python 3.11 or newer first if `python`/`py` is unavailable.

For local AI, install Ollama from https://ollama.com/download. The first local
model selected in the UI downloads automatically. Gemini and Hugging Face use
their hosted APIs and require their respective keys.

To stop the UI, press `Ctrl+C` in the terminal.

## Run it manually, no API key

```bash
cd find-me-a-job
./setup.sh                                      # macOS/Linux
# .\setup.ps1                                  # Windows PowerShell

.venv/bin/python -m findmeajob run --mock --scorer keyword       # macOS/Linux
# .\.venv\Scripts\python.exe -m findmeajob run --mock --scorer keyword  # Windows
```

`--mock` runs bundled fixtures through the **real parsers** — no network.
`--scorer keyword` swaps the LLM for a dumb token-overlap stub, so the whole
pipeline runs with no secrets configured. You should see:

```
[2/5] filtering
  prefilter: 12 -> 5 (dropped title=5 location=1 stale=1)
[3/5] screening 5 jobs (keyword stub — DEV ONLY)
  3 scored >= 7.0
[5/5] digest
  wrote out/digest.html

funnel: 12 scanned -> 5 passed filters -> 5 new -> 3 in digest
```

Open `out/digest.html` in a browser. That's the email you'd have received.

> The keyword scorer is **dev-only**. It cannot tell a Staff role from a
> new-grad one and has no idea what the words mean. It exists to prove the
> plumbing, never to build a digest you'd act on.

---

## Set it up for real

### 1. Point it at companies you'd actually join

Edit `companies.yaml`. The slug is the last path segment of a company's public
careers board:

| Board URL | `ats` | `slug` |
|---|---|---|
| `boards.greenhouse.io/stripe` | `greenhouse` | `stripe` |
| `jobs.lever.co/netlify` | `lever` | `netlify` |
| `jobs.ashbyhq.com/ramp` | `ashby` | `ramp` |

The shipped list is **examples** — verify each before trusting the output.
Companies migrate between ATS vendors and slugs go dead. A dead slug prints an
HTTP status and returns nothing; it never kills the run. Watch the per-board
counts on stdout: a board reporting 0 every day is a slug that needs fixing.

Start with 10–15 companies. A list of 200 is mostly noise.

**No LinkedIn or Naukri.** Neither has a public API and scraping them violates
their terms of service. The three ATS endpoints above are documented, unauthenticated,
and intended to be read.

### 2. Tune the filters

`config.yaml` holds the deterministic gate that runs **before** any LLM call.
This is the whole cost story — get it right and you spend cents a day.

```yaml
filters:
  include_titles: ['\bsde\b', 'software development engineer', ...]
  exclude_titles: ['\b(staff|principal)\b', '\b(manager)\b', ...]
  locations: [bangalore, bengaluru, india]
  allow_remote: true
  max_age_days: 30
score_threshold: 7.0
max_per_digest: 5
```

> **`sde` does not match "Software Development Engineer".** They share no
> substring. Use `\bsde\b` for the acronym *and* list the spelled-out variants
> separately, or you'll silently miss half of Amazon-style postings. There's a
> test pinning this.

### 3. Build your profile

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY
python -m findmeajob profile --resume resume.pdf
```

PDFs are sent natively to Anthropic and Gemini. Ollama, Hugging Face, Groq and
other text-only providers extract selectable PDF text locally with `pypdf`.
Scanned/image-only PDFs need Gemini or Anthropic, or should be exported as
`.txt`/`.md`.

This writes `profile.json`. It's gitignored — read it, fix anything the model
got wrong, and keep it out of version control.

### 4. Run it

```bash
python -m findmeajob run                    # build the digest
python -m findmeajob run --send             # ...and email it
python -m findmeajob run --limit 10         # cost guard while tuning
python -m findmeajob run --no-draft         # screen only, skip the expensive pass
```

---

## Web UI

Prefer a browser to a terminal? There's a small upload-and-go front-end:

```bash
pip install flask
python -m findmeajob serve                  # http://127.0.0.1:5000
```

Open the page, upload a resume (PDF/DOCX/TXT/MD), enter an email, and hit **Find me
jobs**. It builds a profile from the resume, runs the same pipeline, and emails
the digest to that address (you can also view it in the browser). Tick **Demo
mode** to run offline against sample jobs with no API key.

The UI runs one pipeline at a time — `profile.json`, `seen.json` and the digest
are shared files. It's built for a single user on your own machine; don't expose
it to the public internet as-is (no auth, and it runs with your API keys).

### Test email delivery

Add SMTP settings to `.env`. For Gmail, use an App Password, not your normal
account password:

```env
SMTP_USER=you@gmail.com
SMTP_PASS=your-gmail-app-password
MAIL_TO=you@gmail.com
```

Then run the offline pipeline with email enabled:

```bash
.venv/bin/python -m findmeajob run --mock --scorer keyword --send
```

The UI's **Email me the digest** checkbox uses the same SMTP settings. Demo
mode intentionally does not send email; use the command above for a no-AI-key
delivery test.

---

## Picking providers

Screening reads hundreds of jobs and wants the cheapest decent model. Drafting
runs ~5 times and wants the best one. So they're configured separately:

```bash
LLM_PROVIDER=huggingface       # sets both stages
SCREEN_PROVIDER=groq            # ...override per stage
DRAFT_PROVIDER=anthropic
SCREEN_MODEL=claude-haiku-4-5-20251001
DRAFT_MODEL=claude-sonnet-5
```

| Provider | Value | Key | PDF resumes | Notes |
|---|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | yes | default; uses the official SDK |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | yes | generous free tier |
| Groq | `groq` | `GROQ_API_KEY` | no | very fast, free tier |
| OpenAI-compatible | `openai-compatible` | `GROQ_API_KEY` + `LLM_BASE_URL` | no | Together, OpenRouter, vLLM |
| Hugging Face | `huggingface` | `HF_TOKEN` | no | hosted open models via the HF router |
| Ollama | `ollama` | none | text-based PDFs | fully local, `OLLAMA_HOST` |

Everything except Anthropic goes over plain `requests`, so you can delete the
`anthropic` line from `requirements.txt` and still run the whole thing.

Adding a provider is one class in [`findmeajob/backends.py`](findmeajob/backends.py)
with a `complete()` method, plus an entry in the `PROVIDERS` dict.

---

## Tracking

`seen.json` is both the dedupe index and the application tracker — a job you've
already been shown is never shown again. It's gitignored: it's yours, and
shipping one would break the first run on a fresh machine.

```bash
python -m findmeajob applied "greenhouse:stripe:5501001"   # id is in the digest
python -m findmeajob stats                                 # + CSV export
```

`out/tracker.csv` opens in any spreadsheet.

---

## Scheduling

[`.github/workflows/daily.yml`](.github/workflows/daily.yml) runs it at 06:00 IST
on weekdays. `seen.json` is carried between runs with `actions/cache`, not
committed — it's personal, and a `seen.json` in the repo would mark every job as
already-seen on a fresh checkout. Nothing personal ever enters git.

Repository **secrets** to set (Settings → Secrets and variables → Actions):

| Secret | What |
|---|---|
| `PROFILE_JSON` | the entire contents of your local `profile.json` |
| `ANTHROPIC_API_KEY` | (or `GEMINI_API_KEY` / `GROQ_API_KEY`) |
| `SMTP_USER` / `SMTP_PASS` | Gmail address + **App Password**, not your login |
| `MAIL_TO` | where the digest goes |

Optional repository **variables**: `LLM_PROVIDER`, `SCREEN_PROVIDER`,
`DRAFT_PROVIDER`, `SCREEN_MODEL`, `DRAFT_MODEL`.

Trigger it by hand first — Actions → *daily job digest* → *Run workflow*, with
`dry_run` ticked to build the digest artifact without emailing.

Gmail needs an [App Password](https://myaccount.google.com/apppasswords); your
normal password stops working once 2FA is on.

---

## Layout

```
findmeajob/
  sources.py     Job dataclass, strip_html, ATS parsers, fetch_all + hydrate
  filters.py     title/location/freshness gate — no LLM, no cost
  backends.py    the swappable provider interface + 5 backends
  ai.py          screen() / draft() / build_profile() / keyword stub
  report.py      HTML email (inline CSS only — Gmail strips <style>)
  notify.py      SMTP
  tracker.py     seen.json dedupe + tracker + CSV export
  samples.py     fixtures in each ATS's native JSON shape
  app.py         argparse: profile / run / applied / stats / serve
  web.py         Flask UI: upload resume + email -> pipeline -> digest
  templates/     index + status pages for the web UI
config.yaml      filters, thresholds, paths
companies.yaml   boards to poll
tests/           55 tests, no network, no key
```

HTTP is kept out of the parsers on purpose. Each `parse_*(slug, company, body)`
takes already-decoded JSON and returns `list[Job]`, which is what makes `--mock`
exercise the real code path instead of a parallel implementation.

Every job gets `job_id = "{ats}:{slug}:{id}"` — globally unique, so the same
role posted on two boards is still two rows, and a re-run never duplicates.

### ATS quirks the parsers handle

- **Greenhouse** — `content` is HTML-entity-escaped HTML. Unescape *before*
  stripping tags and again after, or you ship `&amp;` into the prompt.
- **Lever** — `createdAt` is epoch **milliseconds**. The full JD is split across
  `descriptionPlain` **+** `lists[].text` **+** `lists[].content` **+**
  `additionalPlain`; concatenate all four or you lose the requirements section
  and every job looks unqualified.
- **Ashby** — skip `isListed: false`; those are unpublished drafts.

---

## Tests

```bash
python -m pytest tests -q
```

No network, no API key, no cost. The suite covers:

- each parser against fixtures in its **native** ATS shape
- the two bugs that cost me an evening each: Lever's epoch-ms timestamps
  (fixture dates are generated relative to *now*, never hardcoded, so they
  can't silently age past the freshness gate) and the `\bsde\b` regex
- prefilter rejects the planted junk: wrong seniority, wrong city, wrong
  function, a stale posting, an unlisted Ashby draft
- the LLM layer with the provider stubbed: batching splits at the configured
  size, JD truncation is applied before send, fenced/preamble/object-or-array
  JSON all parse, scores land on the right job when returned out of order, a
  failed batch warns and the run continues, and the draft kit always has every
  key the digest renders

---

## Cost

With ~15 boards, a tight `config.yaml`, Haiku screening and Sonnet drafting,
this lands in the low single-digit rupees per day. The prefilter is what makes
that true: nothing reaches a model until it has already passed title, location
and freshness. Set `SCREEN_PROVIDER=groq` or `gemini` and it's free.

Use `--limit` while tuning filters so a bad regex can't run up a bill.
