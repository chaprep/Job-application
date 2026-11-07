# Jab

A personal, local workspace for preparing job applications and keeping track of them. The React interface and FastAPI backend cover all five workflows: base résumé setup, job intake, document preparation, review/download, and application tracking.

## Run with Docker (macOS, Windows, or Linux)

Install Docker Desktop (or Docker Engine with Compose 2.24+ on Linux), start Docker, then:

```sh
git clone https://github.com/chaprep/Job-application.git
cd Job-application
docker compose up --build -d
```

Open **http://localhost:8000**. The image builds the React interface and includes Python, Poppler, LuaLaTeX, Inter, and Roboto; no host Python, Node, or TeX installation is needed. The Dockerfile uses images available for Intel/AMD and ARM computers. Internet access is needed for the first build and provider calls. The first build downloads the PDF toolchain and can take several minutes.

AI is optional for starting Jab. To enable it, copy `.env.example` to `.env` (PowerShell: `Copy-Item .env.example .env`), enter your provider keys and valid model IDs, then run:

```sh
docker compose up -d --force-recreate
```

In macOS/Linux terminals, use `cp .env.example .env`. Credentials are passed at runtime through Compose's [optional environment file](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/); `.env` is excluded from Git and Docker's build context. Do not share `.env`, container inspection output, or expanded Compose configuration.

```sh
docker compose logs --tail=100
docker compose down
```

The named `jab-data` volume retains the database, uploads, and generated PDFs across container rebuilds and ordinary `down` commands. It starts as a fresh workspace; local `data/` is deliberately not imported. Never use `docker compose down -v` unless you intend to delete this workspace. For backups, stop Jab first, then copy all of `/app/data` from the stopped container with `docker compose cp jab:/app/data ./jab-backup`; restart with `docker compose up -d`. Keep backups private and outside this repository.

The app is for one person on their own computer: it has no login. Compose publishes only on loopback, and the backend keeps its local host/origin checks. Use port 8000 and open it on the computer running Docker; public hosting requires separate authentication and deployment work. Stop another service on port 8000 before starting Jab.

## Open Jab without Docker

From a terminal:

```sh
cd Job-application
./start.sh
```

Open **http://127.0.0.1:8000** in your browser. Keep the terminal open; Ctrl+C stops Jab. The launcher builds the frontend when necessary and serves the interface and API from the same loopback address. It does not submit applications or automatically start paid AI requests.

For a fresh native installation:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
npm run build
cd ..
./start.sh
```

Tested with Python 3.14 and Node 24. PDF intake/output requires Poppler (`pdfinfo`, `pdftotext`, `pdftohtml`) and LuaLaTeX with Inter. Node/npm are needed to install or rebuild the frontend; the built application is served by Python. Do not run multiple backend workers or use reload with the task worker.

## Connect AI

Create `.env` from `.env.example`, then fill in the provider URL, model ID, and API key. Restart Jab after changing configuration. The provider must expose an OpenAI-compatible Chat Completions endpoint. Keys are read only by the backend; résumé and job text needed for processing is sent to that provider.

Set `JAB_AI_RESUME_MODEL=openai/gpt-6-luna-pro` for base résumé organisation and `JAB_AI_JOB_MODEL=openai/gpt-6-luna-pro` for job intake, including their response repairs. Set `JAB_AI_REVIEW_MODEL=openai/gpt-6-luna-pro` for document review of both résumés and cover letters, including response repairs. Set `JAB_AI_REVISION_MODEL=anthropic/claude-sonnet-5.5` for résumé AI revisions, including response repairs. Cover-letter AI revisions and their response repairs use `JAB_AI_COVER_LETTER_MODEL`. The default `JAB_AI_MODEL` is `anthropic/claude-sonnet-5.5`. Initial résumé tailoring uses `JAB_AI_TAILOR_MODEL=anthropic/claude-sonnet-5.5` and cover letter writing uses `JAB_AI_COVER_LETTER_MODEL=anthropic/claude-sonnet-5.5`. All use the same OpenRouter URL and key; leaving an override blank uses the default model.

Use **Workspace status** in Jab to check database, renderer, and default model configuration readiness. Configuration presence does not prove that credentials or either selected model work. Live provider inference has not been verified during implementation.

Without AI, you can complete job fields manually, track applications, read saved content, and download existing ready PDFs. Organisation, extraction of job fields, and document writing need AI. Generated drafts go directly to PDF creation for your review; there is no automated factual approval gate.

## Use the workspace

1. **Base résumé:** upload a PDF or DOCX up to 10 MiB. Review the extracted content in the structured editor, confirm its accuracy, and activate it. If link-format checks block activation, **Override and activate as is** lets you keep those values unchanged; the PDFs show them as plain text. Other checks still apply. Editing an approved résumé saves a new version; earlier application documents stay preserved.
2. **Jobs:** add a direct job URL or paste the full description. Review company, role, full JD, and optional details. Confirm before preparation. If URL capture fails, paste a replacement or complete the fields manually.
3. **Documents:** prepare a résumé and cover letter. Review each document’s findings, edit the content beside its saved PDF, or request an AI revision. Manual changes create new revisions and run fresh checks. Each document has its own history and saved selected version across all generation attempts. You can combine any résumé version with any cover-letter version. Generation activity remains available separately. PDF output uses a fixed Inter résumé template on A4 and a separate Roboto cover-letter template on US Letter, each limited to one page.
4. **Record application:** submit externally, explicitly select the exact ready PDFs you sent, and record the submission. Downloading a PDF never marks it applied.
5. **Applications:** search/filter submissions, change stages, add dated notes, set follow-up actions/dates, or make audited corrections. You can also record applications prepared outside Jab.

Progress is polled from persisted backend tasks. Closing a browser tab does not stop backend work. Stopping the server interrupts unfinished operations; retry explicitly after restart. Follow-up dates are tracked in Jab without scheduled notifications. Scanned résumés require a text-based replacement; OCR is outside this version.

Unsaved edits warn before navigation. Failed requests preserve the current form. The UI does not keep a second copy of personal data in localStorage, and it does not need externally hosted fonts or assets.

## Development

Run the backend from `Jab/`:

```sh
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

In another terminal:

```sh
cd Jab/frontend
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies API, readiness, and health calls to the backend. The interface uses hash routes so saved links work with the production static server. `frontend/src/` contains the React/TypeScript components and plain CSS; `backend/` retains ownership of files, secrets, AI calls, and persistence.

## Verification

```sh
# From Jab/
.venv/bin/python -m pytest tests -q
cd frontend
npm test
npm run build
```

Frontend tests check request contracts, unsafe-link handling, recursive résumé editing/rendering, cover-letter evidence, exact PDF references, validation findings, explicit submission controls, and targeted revision views. They use React server rendering and Node’s test runner; they are **not** a replacement for browser interaction or layout checks.

Backend checks use mocked provider responses and real PDF compilation. They cover persistence, HTTP workflows, document selection, link preservation, and rendering. Reference PDFs and fixtures use synthetic candidate data. Exact raster comparisons can depend on the TeX/Poppler versions; use the documented native toolchain when comparing an approved reference image.

To run backend checks inside the built Linux image against a temporary copy of the source (macOS/Linux shell):

```sh
docker build -t jab:local .
docker run --rm --user root --entrypoint sh -v "$PWD:/source:ro" jab:local -c 'mkdir -p /tmp/frontend; cp -a /app/frontend/dist /source/frontend/public /tmp/frontend/; cp -a /source/backend /source/tests /source/reference /tmp/; cd /tmp; python -m pytest tests -q'
```

This copies only code, tests, and synthetic references; it does not load the local `.env` or workspace. Model billing and credentials are not exercised by mocked tests.

## Your data

For native installations, the SQLite database and saved files live in `data/`, excluded from version control along with `.env`, caches, build output, and dependencies. Stop Jab before copying the complete `data/` directory for backup. Back up the database and referenced files together.

## Preserving linked text

Restart Jab after updating, then open **Base résumé → Re-import original with links** to recover destinations from an already saved original. This creates a separate draft; compare it with the prior reviewed version, carry across any later manual edits, review any unresolved links, then activate it explicitly. Existing runs and submitted PDFs are unchanged.

Contact links have separate labels and destinations. For text within a heading, bullet, summary, skill or letter paragraph, select the phrase and choose **Link selected text**. If editing changes a linked phrase, its destination stays visible for reattachment instead of being silently discarded. Valid retained links appear blue and clickable in generated PDFs. The existing override keeps invalid values as non-clickable text.

## Repository privacy

Publish application code and synthetic examples only. Local `.env` files, saved workspace data, dependency folders, build output, credentials, and obsolete personal reference scripts are ignored. Docker uses a restricted build context and explicit runtime copies. If a real key is ever committed or shared, revoke it with its provider; deleting the current file does not revoke a key or erase Git history.
