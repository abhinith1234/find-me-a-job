# Find Me A Job

A personal job-search agent. It reads public ATS APIs and the OpenJobData public
job dataset, filters jobs against your resume, scores the survivors, drafts an
application kit for the best matches, and optionally emails or displays a digest.

**It never submits an application.** You review the results and apply yourself.

## Quick setup

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

### macOS/Linux

```bash
./setup.sh
./run.sh
```

Open <http://127.0.0.1:5000>. The setup scripts use the project-local `.venv`.
Python 3.11 or newer is recommended.

## Web UI

Upload a PDF, DOCX, TXT, or MD resume and choose a results mode:

- **Browser results** displays the current matches in the browser.
- **Email me the digest** sends the digest through the configured SMTP server.

The UI builds a profile from the resume and runs the same fetch, filter, screen,
and draft pipeline as the CLI.

### Gemini key

Select Google Gemini, enter the API key, and optionally check **Remember Gemini
API key on this computer**. The key is saved only in the local, gitignored `.env`
file. It is not rendered back into the page or written to logs. Temporary Gemini
429/5xx/503 failures retry automatically.

### Ollama

Select **Ollama local model**. The UI checks whether Ollama and the selected model
are installed. If the model is missing, click **Install selected model**; the UI
runs the equivalent of `ollama pull <model>` in the background and reports the
status.

Available models:

- `llama3.2:1b`
- `gemma2:2b`
- `qwen2.5:1.5b`

Install Ollama itself from <https://ollama.com/download>. Windows installations
are detected at the standard local install path even when the current terminal
has not refreshed its PATH. macOS and Linux use their normal Ollama executable.

## CLI usage

Run an offline parser test with no API key:

```bash
python -m findmeajob run --mock --scorer keyword
```

Run the real pipeline:

```bash
python -m findmeajob profile --resume resume.pdf
python -m findmeajob run
python -m findmeajob run --send
python -m findmeajob run --limit 10
python -m findmeajob run --no-draft
```

`--limit` is a cost guard. `--no-draft` screens jobs but skips application-kit
generation. The keyword scorer is only a development stub and does not understand
seniority or requirements.

## Sources

`companies.yaml` supports these public sources:

- Greenhouse
- Lever
- Ashby
- Recruitee
- Workable
- SmartRecruiters
- Personio
- OpenJobData

Company entries use an ATS and public board slug:

```yaml
- {ats: greenhouse, slug: stripe, name: Stripe}
- {ats: lever, slug: netlify, name: Netlify}
- {ats: ashby, slug: ramp, name: Ramp}
- {ats: smartrecruiters, slug: BoschGroup, name: Bosch}
```

The shipped list includes Indian technology, fintech, consulting, finance, and
global companies. Slugs can go stale when companies migrate ATS providers; a dead
slug prints its HTTP status and does not stop the run.

### OpenJobData

The `openjobdata` entry reads the latest public minimal Parquet delta from the
OpenJobData Hugging Face bucket. It includes jobs from Workday, SmartRecruiters,
iCIMS, Greenhouse, Lever, Ashby, and other ATS platforms. `huggingface-hub` and
`pyarrow` are installed from `requirements.txt`.

OpenJobData often provides a title, location, and apply URL without a full
description. The pipeline first applies the deterministic title/location/freshness
filter, then hydrates only survivors from their original ATS detail API or public
HTML/JSON-LD page before sending them to the LLM.

LinkedIn, Naukri, and Indeed are intentionally absent: they do not provide a
free public API for this use and scraping them is not part of this project.

## Filtering and screening

The deterministic filter in `config.yaml` runs before any LLM call:

- Include and exclude title regexes
- India-wide locations and allowed remote roles
- Freshness via `max_age_days`
- Preferred locations from the resume profile

If the profile contains `preferred_locations`, such as:

```json
"preferred_locations": ["Bangalore", "Bengaluru", "India"]
```

Bangalore/Bengaluru jobs are ordered first, while other India and allowed remote
roles remain eligible.

The LLM then receives the candidate profile, company, title, location, and job
description. It scores each job from 0 to 10. Only jobs at or above the configured
threshold enter the digest:

```yaml
score_threshold: 5.0
max_per_digest: 5
```

## Providers

Set provider values in `.env` or select them in the UI. Screening and drafting can
use different providers with `SCREEN_PROVIDER` and `DRAFT_PROVIDER`.

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
SCREEN_MODEL=gemini-3.6-flash
DRAFT_MODEL=gemini-3.6-flash
```

Supported providers:

| Provider | Value | Credential | PDF support |
|---|---|---|---|
| Google Gemini | `gemini` | `GEMINI_API_KEY` | Yes |
| Ollama | `ollama` | None | Text extraction |
| Hugging Face | `huggingface` | `HF_TOKEN` | Text extraction |
| Groq | `groq` | `GROQ_API_KEY` | Text extraction |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Yes |
| OpenAI-compatible | `openai-compatible` | `GROQ_API_KEY` and `LLM_BASE_URL` | Text extraction |

For PDF resumes, Gemini and Anthropic can read the PDF directly. Other providers
use local text extraction; scanned image-only PDFs should be exported to text or
sent to a document-capable provider.

## Tracking policy

There is no `seen.json` deduplication or application-tracking feature. Every run
processes the current jobs that pass the filters. The digest does not display seen
or applied counters.

## Email

For Gmail, use an App Password rather than your normal password:

```env
SMTP_USER=you@gmail.com
SMTP_PASS=your-gmail-app-password
MAIL_TO=you@gmail.com
```

The UI's email mode uses these settings. Browser mode does not send mail.

## Layout

```text
findmeajob/
  sources.py     ATS parsers, OpenJobData reader, fetching, and description hydration
  filters.py     title/location/freshness filter and preferred-location ordering
  backends.py    provider interface and LLM backends
  ai.py          profile extraction, screening, drafting, and keyword stub
  report.py      HTML digest
  notify.py      SMTP delivery
  app.py         CLI: profile, run, and serve
  web.py         Flask UI and background jobs
  templates/     UI pages
config.yaml      filters, thresholds, and paths
companies.yaml   public boards to poll
tests/           offline regression tests
```

## Tests

```bash
python -m pytest tests -q
```

The suite uses local fixtures and does not require an API key or network access.
It covers ATS parsers, OpenJobData mapping, title/location filtering, profile and
provider behavior, batching, JSON parsing, draft normalization, and the web flow.
