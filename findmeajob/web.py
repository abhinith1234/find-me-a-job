"""Web UI: upload a resume, enter an email, and trigger the pipeline.

This is a thin front-end over the same code the CLI runs. It builds a profile
from the uploaded resume, runs fetch -> prefilter -> screen -> draft -> digest,
and (optionally) emails the digest to the address the user typed. The digest is
also viewable in the browser, so it works even with SMTP unconfigured.

Runs are serialised with a lock: profile.json and out/digest.html are shared
files, so two pipelines at once would corrupt each other. For a personal,
single-user tool that is the right trade-off.

    python -m findmeajob serve
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import uuid
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

from . import ai
from .app import ROOT, _cfg, _load_env, cmd_run
from .backends import LLMError, resolve

ALLOWED_EXT = {".pdf", ".docx", ".txt", ".md"}
LOCAL_MODELS = {
    "llama3.2:1b": "Llama 3.2 1B (smallest)",
    "gemma2:2b": "Gemma 2 2B",
    "qwen2.5:1.5b": "Qwen 2.5 1.5B",
}
PROVIDERS = {"ollama", "huggingface", "gemini"}
MAX_BYTES = 5 * 1024 * 1024  # 5 MB is plenty for a resume
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

UPLOADS = ROOT / "uploads"
CUSTOMIZE_DATA = ROOT / "out" / "customize"

# job_id -> {state, email, filename, log, digest, emailed, error}
JOBS: dict[str, dict] = {}
_RUN_LOCK = threading.Lock()
_OLLAMA_INSTALL_PROCESS: subprocess.Popen | None = None
_OLLAMA_INSTALL_STATE = "idle"
_OLLAMA_MODEL_PROCESS: subprocess.Popen | None = None
_OLLAMA_MODEL_NAME: str | None = None
_OLLAMA_MODEL_STATE = "idle"


def _save_local_secret(name: str, value: str) -> None:
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    replaced = False
    updated = []
    for line in lines:
        if line.startswith(prefix):
            updated.append(f"{name}={value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"{name}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.environ[name] = value


class _LiveLog:
    def __init__(self, job: dict, buffer: io.StringIO):
        self.job = job
        self.buffer = buffer

    def write(self, text: str) -> int:
        written = self.buffer.write(text)
        self.job["log"] = self.buffer.getvalue()
        return written

    def flush(self) -> None:
        self.job["log"] = self.buffer.getvalue()


def _ollama_install_details() -> tuple[str, str, str]:
    """Return a human-readable install command and link for the current OS."""
    system = platform.system()
    if system == "Windows":
        return (
            "winget install --id Ollama.Ollama -e",
            "https://ollama.com/download/windows",
            "Windows",
        )
    if system == "Darwin":
        return (
            "brew install ollama",
            "https://ollama.com/download/mac",
            "macOS",
        )
    return (
        "curl -fsSL https://ollama.com/install.sh | sh",
        "https://ollama.com/download/linux",
        "Linux",
    )


def _ollama_install_command() -> list[str] | str:
    system = platform.system()
    if system == "Windows":
        return ["winget", "install", "--id", "Ollama.Ollama", "-e"]
    if system == "Darwin":
        return ["bash", "-lc", "brew install ollama"]
    return ["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"]


def _ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if platform.system() == "Windows":
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if installed.exists():
            return str(installed)
    return None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES
    app.secret_key = os.urandom(24)
    _load_env()

    @app.route("/", methods=["GET"])
    def index():
        install_cmd, install_url, label = _ollama_install_details()
        return render_template("index.html", error=None,
                               ollama_install_cmd=install_cmd,
                               ollama_install_url=install_url,
                               ollama_os_label=label,
                               gemini_key_saved=bool(os.environ.get("GEMINI_API_KEY")))

    @app.route("/install-ollama", methods=["POST"])
    def install_ollama():
        global _OLLAMA_INSTALL_PROCESS, _OLLAMA_INSTALL_STATE
        try:
            if (_OLLAMA_INSTALL_PROCESS is not None
                    and _OLLAMA_INSTALL_PROCESS.poll() is None):
                message = "Ollama installation is already running."
            else:
                command = _ollama_install_command()
                _OLLAMA_INSTALL_PROCESS = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, shell=False,
                    start_new_session=True)
                _OLLAMA_INSTALL_STATE = "running"
                message = "Ollama install started in the background. Watch the status below."
            return render_template(
                "index.html",
                error=message,
                ollama_install_cmd=_ollama_install_details()[0],
                ollama_install_url=_ollama_install_details()[1],
                ollama_os_label=_ollama_install_details()[2],
            )
        except Exception as exc:  # pragma: no cover - UI-only fallback
            return render_template(
                "index.html",
                error=f"Could not start the Ollama installer automatically: {exc}",
                ollama_install_cmd=_ollama_install_details()[0],
                ollama_install_url=_ollama_install_details()[1],
                ollama_os_label=_ollama_install_details()[2],
            )

    @app.route("/ollama-install-status", methods=["GET"])
    def ollama_install_status():
        global _OLLAMA_INSTALL_STATE
        process = _OLLAMA_INSTALL_PROCESS
        if process is not None:
            returncode = process.poll()
            if returncode is not None:
                _OLLAMA_INSTALL_STATE = "completed" if returncode == 0 else "failed"
        model = request.args.get("model", "").strip()
        ollama = _ollama_executable()
        installed = []
        if ollama:
            try:
                result = subprocess.run(
                    [ollama, "list"], capture_output=True, text=True, check=False)
                installed = [line.split()[0] for line in result.stdout.splitlines()[1:]
                             if line.split()]
            except OSError:
                pass
        model_process = _OLLAMA_MODEL_PROCESS
        model_state = _OLLAMA_MODEL_STATE
        if model_process is not None and model_process.poll() is not None:
            model_state = "completed" if model_process.returncode == 0 else "failed"
        return jsonify({
            "state": _OLLAMA_INSTALL_STATE,
            "ollama_installed": bool(ollama),
            "model": model,
            "model_installed": model in installed,
            "model_state": model_state if _OLLAMA_MODEL_NAME == model else "idle",
        })

    @app.route("/install-ollama-model", methods=["POST"])
    def install_ollama_model():
        global _OLLAMA_MODEL_PROCESS, _OLLAMA_MODEL_NAME, _OLLAMA_MODEL_STATE
        model = (request.form.get("model") or "").strip()
        if model not in LOCAL_MODELS:
            return jsonify({"error": "Choose a supported Ollama model."}), 400
        ollama = _ollama_executable()
        if ollama is None:
            return jsonify({
                "error": "Ollama is not installed. Install Ollama first, then try again."
            }), 400
        if _OLLAMA_MODEL_PROCESS is not None and _OLLAMA_MODEL_PROCESS.poll() is None:
            return jsonify({"state": "running", "model": _OLLAMA_MODEL_NAME})
        try:
            _OLLAMA_MODEL_PROCESS = subprocess.Popen(
                [ollama, "pull", model], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, shell=False, start_new_session=True)
            _OLLAMA_MODEL_NAME = model
            _OLLAMA_MODEL_STATE = "running"
            return jsonify({"state": "running", "model": model})
        except OSError as exc:
            _OLLAMA_MODEL_STATE = "failed"
            return jsonify({"error": f"Could not start Ollama: {exc}"}), 500

    @app.route("/run", methods=["POST"])
    def run():
        email = (request.form.get("email") or "").strip()
        upload = request.files.get("resume")
        demo = request.form.get("demo") == "on"
        delivery = (request.form.get("delivery") or "browser").strip().lower()
        send = delivery == "email"
        limit_raw = (request.form.get("limit") or "").strip()
        provider = (request.form.get("provider") or "ollama").strip().lower()
        model = (request.form.get("model") or "").strip()
        token = (request.form.get("token") or "").strip()
        remember_gemini = request.form.get("remember_gemini") == "on"
        if provider == "gemini" and not token:
            token = os.environ.get("GEMINI_API_KEY", "").strip()
        if provider == "gemini" and token and remember_gemini:
            _save_local_secret("GEMINI_API_KEY", token)

        if delivery not in {"browser", "email"}:
            return render_template("index.html", error="Choose a delivery option."), 400
        if send and not EMAIL_RE.match(email):
            return render_template("index.html", error="Enter a valid email address."), 400
        if not upload or not upload.filename:
            return render_template("index.html", error="Choose a resume file to upload."), 400

        ext = Path(secure_filename(upload.filename)).suffix.lower()
        if ext not in ALLOWED_EXT:
            return render_template(
                "index.html",
                error=f"Unsupported file type '{ext or '?'}'. Use PDF, DOCX, TXT or MD."), 400
        if provider not in PROVIDERS:
            return render_template("index.html", error="Choose a supported AI provider."), 400
        if provider == "huggingface" and (not model or model in LOCAL_MODELS):
            model = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
        elif provider == "gemini" and (not model or model in LOCAL_MODELS):
            model = "gemini-3.6-flash"
        if provider == "ollama" and model not in LOCAL_MODELS:
            return render_template("index.html", error="Choose a local Ollama model."), 400
        if provider in {"huggingface", "gemini"} and not token:
            label = "Hugging Face token" if provider == "huggingface" else "Gemini API key"
            return render_template("index.html", error=f"Enter your {label}.",
                                   provider=provider), 400
        limit = None
        if limit_raw:
            try:
                limit = max(1, int(limit_raw))
            except ValueError:
                return render_template("index.html", error="Limit must be a number."), 400

        job_id = uuid.uuid4().hex
        UPLOADS.mkdir(parents=True, exist_ok=True)
        resume_path = UPLOADS / f"{job_id}{ext}"
        upload.save(resume_path)
        saved_resume = CUSTOMIZE_DATA / f"{job_id}{ext}"
        saved_resume.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resume_path, saved_resume)

        JOBS[job_id] = {
            "state": "queued", "email": email or "browser preview", "filename": upload.filename,
            "log": "[queued] Request accepted; waiting for the pipeline lock.\n",
            "digest": False, "emailed": False, "error": None,
            "resume_path": str(saved_resume), "customize": {},
        }
        opts = Namespace(demo=demo, send=send, limit=limit, provider=provider,
                 model=model, token=token, resume_path=str(saved_resume))
        threading.Thread(target=_worker, args=(job_id, resume_path, email, opts),
                         daemon=True).start()
        return redirect(url_for("status", job_id=job_id))

    @app.route("/status/<job_id>", methods=["GET"])
    def status(job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            abort(404)
        return render_template("status.html", job=job, job_id=job_id)

    @app.route("/digest/<job_id>", methods=["GET"])
    def digest(job_id: str):
        job = JOBS.get(job_id)
        if job is None or not job.get("digest"):
            abort(404)
        path = ROOT / "out" / f"{job_id}.html"
        if not path.exists():
            abort(404)
        return send_file(path)

    @app.route("/customize/<run_id>/<path:job_id>", methods=["GET", "POST"])
    def customize(run_id: str, job_id: str):
        run = JOBS.get(run_id)
        data_path = CUSTOMIZE_DATA / f"{run_id}.json"
        if run is None or not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        if job_id not in data:
            abort(404)
        result = None
        error = None
        if request.method == "POST":
            try:
                opts = Namespace(
                    provider=(request.form.get("provider") or "ollama").strip(),
                    model=(request.form.get("model") or "llama3.2:1b").strip(),
                    token=(request.form.get("token") or "").strip(),
                )
                if opts.provider == "huggingface" and opts.model in LOCAL_MODELS:
                    opts.model = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
                elif opts.provider == "gemini" and opts.model in LOCAL_MODELS:
                    opts.model = "gemini-3.6-flash"
                previous = _configure_provider(opts)
                try:
                    result = _customize(data[job_id], opts)
                finally:
                    _restore_env(previous)
                run["customize"] = result
            except Exception as exc:  # surface provider errors in the page
                error = f"{type(exc).__name__}: {exc}"
        return render_template("customize.html", job=data[job_id], data=data[job_id],
                               result=result, error=error)

    return app


def _worker(job_id: str, resume_path: Path, email: str, opts: Namespace) -> None:
    """Build the profile, run the pipeline, copy the digest aside. All output is
    captured so the status page can show exactly what the CLI would have."""
    job = JOBS[job_id]
    job["state"] = "running"
    buf = io.StringIO(job["log"])
    try:
        with _RUN_LOCK, redirect_stdout(_LiveLog(job, buf)):
            print(f"[run] Started for {job['filename']} -> {email}", flush=True)
            print(f"[provider] {opts.provider}/{opts.model}", flush=True)
            previous_env = {} if opts.demo else _configure_provider(opts)
            print("[provider] Ready", flush=True)
            cfg = _cfg("config.yaml")
            profile_file = Path(cfg.get("profile_file", "profile.json"))

            # Demo mode is offline and needs no key: the pipeline falls back to
            # profile.example.json when profile.json is absent (allow_sample).
            if not opts.demo:
                print("[resume] Extracting profile", flush=True)
                _build_profile(resume_path, profile_file)
                print("[resume] Profile ready", flush=True)
            else:
                print("[resume] Demo profile enabled", flush=True)

            os.environ["MAIL_TO"] = email
            os.environ["CUSTOMIZE_BASE_URL"] = "http://127.0.0.1:5000"
            os.environ["CUSTOMIZE_RUN_ID"] = job_id
            args = Namespace(
                config="config.yaml",
                mock=opts.demo,
                scorer="keyword" if opts.demo else "llm",
                no_draft=opts.demo,
                send=False if opts.demo else opts.send,
                limit=opts.limit,
                web_job_id=job_id,
                resume_path=opts.resume_path,
            )
            cmd_run(args)
            print("[run] Pipeline complete", flush=True)

            digest_src = Path(cfg.get("digest_file", "out/digest.html"))
            if digest_src.exists():
                dst = ROOT / "out" / f"{job_id}.html"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(digest_src, dst)
                job["digest"] = True
            _restore_env(previous_env)

        log = buf.getvalue()
        job["log"] = log
        job["emailed"] = "mailed ->" in log
        job["state"] = "done"
        job["log"] = f"{log}[done] Task finished.\n"
    except LLMError as e:
        job["log"] = buf.getvalue()
        job["error"] = (f"{e}\n\nNo API key? Tick 'Demo mode' to run offline with "
                        f"sample jobs, or set a key in .env.")
        job["log"] += f"[error] {e}\n"
        job["state"] = "error"
    except Exception as e:  # noqa: BLE001 — surface anything to the status page
        job["log"] = buf.getvalue()
        job["error"] = f"{type(e).__name__}: {e}"
        job["log"] += f"[error] {type(e).__name__}: {e}\n"
        job["state"] = "error"
    finally:
        if "previous_env" in locals():
            _restore_env(previous_env)
        try:
            resume_path.unlink(missing_ok=True)
        except OSError:
            pass


def _configure_provider(opts: Namespace) -> dict[str, str | None]:
    """Apply one UI run's provider settings without persisting secrets."""
    provider = opts.provider
    model = opts.model
    env_names = ["LLM_PROVIDER", "SCREEN_PROVIDER", "DRAFT_PROVIDER",
                 "SCREEN_MODEL", "DRAFT_MODEL", "HF_TOKEN", "GEMINI_API_KEY",
                 "CUSTOMIZE_BASE_URL", "CUSTOMIZE_RUN_ID"]
    previous = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["LLM_PROVIDER"] = provider
        os.environ["SCREEN_PROVIDER"] = provider
        os.environ["DRAFT_PROVIDER"] = provider
        if model:
            os.environ["SCREEN_MODEL"] = model
            os.environ["DRAFT_MODEL"] = model
        if provider == "huggingface":
            os.environ["HF_TOKEN"] = opts.token
        elif provider == "gemini":
            os.environ["GEMINI_API_KEY"] = opts.token
        elif provider == "ollama":
            ollama = _ollama_executable()
            if ollama is None:
                install_cmd, install_url, label = _ollama_install_details()
                raise LLMError(
                    "Ollama is not installed. Install it for this "
                    f"{label} machine. Run this command: {install_cmd}\n"
                    f"Download page: {install_url}"
                )
            print(f"checking local model {model} ...")
            result = subprocess.run(
                [ollama, "list"], capture_output=True, text=True, check=False)
            if model not in result.stdout:
                print(f"downloading local model {model} ...")
                pull = subprocess.Popen(
                    [ollama, "pull", model], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True)
                lines = []
                for line in pull.stdout or []:
                    line = line.rstrip()
                    lines.append(line)
                    print(line, flush=True)
                pull.wait()
                output = "\n".join(lines).strip()
                if pull.returncode:
                    raise LLMError(
                        f"Ollama could not download {model} (exit code {pull.returncode}).\n"
                        f"{output or 'No details returned by Ollama.'}\n"
                        "Check that Ollama is running and that your internet connection "
                        "can reach the model registry."
                    )
    except Exception:
        _restore_env(previous)
        raise
    return previous


def _customize(item: dict, opts: Namespace) -> dict:
    from types import SimpleNamespace

    job = SimpleNamespace(**item)
    resume_path = Path(item["resume_path"])
    is_pdf = resume_path.suffix.lower() == ".pdf"
    is_docx = resume_path.suffix.lower() == ".docx"
    provider, model = resolve("draft")
    return ai.customize_resume(
        job, resume_text=(ai.extract_docx_text(resume_path.read_bytes()) if is_docx
                          else None if is_pdf else resume_path.read_text(
                              encoding="utf-8", errors="replace")),
        resume_bytes=resume_path.read_bytes() if is_pdf else None,
        is_pdf=is_pdf, provider=provider, model=model)


def _restore_env(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _build_profile(resume_path: Path, profile_file: Path) -> None:
    is_pdf = resume_path.suffix.lower() == ".pdf"
    is_docx = resume_path.suffix.lower() == ".docx"
    provider, model = resolve("draft")
    print(f"reading {resume_path.name} via {provider.name}/{model} ...")
    profile = ai.build_profile(
        resume_bytes=resume_path.read_bytes() if is_pdf else None,
        resume_text=(ai.extract_docx_text(resume_path.read_bytes()) if is_docx
                     else None if is_pdf else resume_path.read_text(
                         encoding="utf-8", errors="replace")),
        is_pdf=is_pdf, provider=provider, model=model,
    )
    profile_file.write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    print(f"wrote {profile_file}")


def run_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    # The pipeline reads/writes config.yaml, profile.json and out/
    # by relative path, so anchor the process at the project root.
    os.chdir(ROOT)
    _load_env()
    app = create_app()
    print(f"findmeajob UI on http://{host}:{port}  (Ctrl-C to stop)")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run_server()
