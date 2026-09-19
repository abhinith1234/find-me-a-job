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
| OpenAI-compatible | `openai-compatible` | provider-specific key and `LLM_BASE_URL` | Text extraction |

For PDF resumes, Gemini can read the PDF directly. Other providers use local text
extraction; scanned image-only PDFs should be exported to text or sent to a
document-capable provider.

## Tracking policy

Normal CLI and UI runs process the current jobs that pass the filters and do not
deduplicate or track previous results. Scheduled email runs are different: they
use the local, gitignored `old_ones.json` file to avoid emailing the same job
again. A job is added to `old_ones.json` only after its email is accepted by the
SMTP server. The digest does not display tracking or application counters.

## Email

### Brevo setup

1. Create or sign in to your Brevo account: <https://app.brevo.com/>
2. Open **Transactional** → **Settings** → **SMTP & API**.
3. In the SMTP section, create an SMTP key. Copy it immediately; Brevo may not
  show the full key again.
4. Open **Senders & IP** → **Senders**, add `coconut.ai.labs@gmail.com`, and
  complete the verification email. Brevo must verify this address before it can
  be used as `SMTP_FROM`.
5. Review delivery activity at <https://app.brevo.com/transactional/email/real-time>.
6. Put the settings in the local `.env` file:

```env
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=your-brevo-smtp-login
SMTP_PASS=your-brevo-smtp-key
SMTP_FROM=coconut.ai.labs@gmail.com
MAIL_TO=your-recipient@example.com
```

`SMTP_USER` is the Brevo SMTP login, not necessarily the sender address.
`SMTP_FROM` must be a verified Brevo sender. Keep `.env` private; it is ignored
by Git.

Test delivery without running the job search:

```powershell
.\.venv\Scripts\python.exe -m findmeajob test-email --to your-recipient@example.com
```

On macOS/Linux:

```bash
.venv/bin/python -m findmeajob test-email --to your-recipient@example.com
```

The command confirms that Brevo accepted the message. Check Inbox and Spam/Junk,
and use Brevo's real-time activity page to diagnose delivery. The UI's email
mode and the daily scheduler use the same settings. Browser mode does not send
mail.

### Test email delivery

After filling in `.env`, send a small test message without running the job
pipeline:

```powershell
.\.venv\Scripts\python.exe -m findmeajob test-email --to you@example.com
```

On macOS/Linux:

```bash
.venv/bin/python -m findmeajob test-email --to you@example.com
```

Brevo must have the `SMTP_FROM` address verified. The command reports when the
SMTP server accepts the message; check Inbox and Spam/Junk for final delivery.

### Daily email trigger

The scheduled job runs the equivalent of:

```text
python -m findmeajob run --send
```

It uses the current `.env`, `companies.yaml`, `config.yaml`, and `profile.json`.
Scheduled runs additionally use the local, gitignored `old_ones.json` file to
avoid emailing the same job again. Normal CLI and UI runs do not use this file.
Make sure `profile.json` exists before installing the schedule.

#### Windows Task Scheduler

Run PowerShell from the project root. The default time is 09:00 local time:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\schedule_daily.ps1 -Action Install
```

Test immediately, inspect the log, or remove the task:

```powershell
.\schedule_daily.ps1 -Action RunNow
Get-ChildItem .\out\scheduled
.\schedule_daily.ps1 -Action Remove
```

Install at another time using 24-hour `HH:MM` format:

```powershell
.\schedule_daily.ps1 -Action Install -Time 18:30
```

#### macOS/Linux cron

Run from the project root:

```bash
chmod +x schedule_daily.sh run_daily.sh
./schedule_daily.sh install 09:00
```

Test immediately, inspect the schedule/log, or remove it:

```bash
./schedule_daily.sh run-now
./schedule_daily.sh list
ls -la out/scheduled
./schedule_daily.sh remove
```

The cron entry runs in your user account and uses the project virtual
environment. The computer must be awake for the scheduled run; macOS users who
need wake-from-sleep behavior should use a launchd agent instead of cron.

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
run_daily.ps1/.sh daily email runner
schedule_daily.ps1/.sh local scheduler setup
tests/           offline regression tests
```

## Tests

```bash
python -m pytest tests -q
```

The suite uses local fixtures and does not require an API key or network access.
It covers ATS parsers, OpenJobData mapping, title/location filtering, profile and
provider behavior, batching, JSON parsing, draft normalization, and the web flow.
