# Jab local backend

The backend implements the five workflows through HTTP: base résumé setup, job intake, document generation, review/revision/download, and application tracking. The React frontend is implemented in `frontend/`; run `./start.sh` from `Jab/` to build when needed and serve the full local workspace. See [../README.md](../README.md).

## Soft deletion

Jobs and applications have **Delete** controls on their lists and detail pages. Each asks for confirmation, hides the record from active lists, search, counts and follow-ups, and preserves its row, files and linked records. Deleting a job leaves its applications editable; deleting an application leaves its job available. Retained details remain readable by ID. Deleted records reject edits and new processing; jobs with queued or running intake, generation or rendering cannot be deleted.

Migration `005_soft_deletion.sql` adds nullable `deleted_at` columns and an append-only `activity_events` table without removing existing data. It runs automatically on backend startup. `DELETE /jobs/{id}` and `DELETE /applications/{id}` return the retained record; repeating deletion preserves the original timestamp and creates no extra event. Job creation, updates, confirmation and archival are recorded in the activity log, and database triggers record both deletion types in the same transaction as their timestamp. Existing application events continue to record stage changes, notes, corrections and follow-ups. Earlier actions are not backfilled.

Read the new logs through `GET /jobs/{id}/activity` and `GET /applications/{id}/activity` with the usual pagination. Application history remains available at `/applications/{id}/events`. Physical deletion and changes to activity records are blocked by SQLite triggers. There is no restore or permanent-purge UI.

## Start

From the `Jab/` directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
# Edit .env with the inference provider's URL, model ID and API key.
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

After building the frontend, open http://127.0.0.1:8000 for Jab. Open http://127.0.0.1:8000/docs for request schemas, upload forms and API calls. `/health` checks the process; `/readiness` checks the database, renderer/font availability and whether AI configuration is present. Readiness does not make a paid request or prove that a model/key works. Tracking and manual job completion work without AI configuration.

Requires Python 3.14 (tested), LuaLaTeX with Inter (résumés) and Roboto (cover letters), and Poppler (`pdftotext`, `pdfinfo`, `pdftohtml`; `pdftoppm` for the reference-layout test). The renderer discovers each font independently through `kpsewhich`. Missing Roboto does not block résumé rendering. `/readiness.renderer` continues to report résumé readiness. PDF/DOCX uploads are limited to 10 MiB; OCR is excluded.

The tested installation uses Poppler for PDF extraction and bounded ZIP/XML parsing for DOCX. Hyperlink-aware extraction uses one Poppler PDF path and one bounded DOCX XML path, independent of optional parser packages. Core API dependencies were installed from local cached wheels because network package downloads were unavailable. Multipart uploads use bounded standard-library MIME parsing and require no extra multipart dependency.

## Provider configuration

`.env` is ignored by Git. Set:

- `JAB_AI_BASE_URL`: OpenAI-compatible API base, e.g. `https://openrouter.ai/api/v1`; Jab appends `/chat/completions`.
- `JAB_AI_MODEL`: default model ID, configured as `anthropic/claude-sonnet-5.5` through OpenRouter. Operations with blank overrides use this model.
- `JAB_AI_TAILOR_MODEL`: initial résumé tailoring and response repairs; configured as `anthropic/claude-sonnet-5.5`. Blank uses `JAB_AI_MODEL`.
- `JAB_AI_COVER_LETTER_MODEL`: cover letter writing, AI revisions and response repairs; configured as `anthropic/claude-sonnet-5.5`. Blank uses `JAB_AI_MODEL`.
- `JAB_AI_RESUME_MODEL`: optional model for base résumé organisation and its response repair. Blank uses `JAB_AI_MODEL`.
- `JAB_AI_JOB_MODEL`: optional model for the single job-intake call, without automatic response repair. Blank uses `JAB_AI_MODEL`. The API base and key are shared.
- `JAB_AI_REVIEW_MODEL`: legacy setting retained for compatibility; document preparation no longer calls an AI reviewer.
- `JAB_AI_REVISION_MODEL`: optional model for résumé AI revisions, including response repairs. Cover-letter AI revisions use `JAB_AI_COVER_LETTER_MODEL`. Set to `anthropic/claude-sonnet-5.5` through OpenRouter. Blank uses `JAB_AI_MODEL`.
- `JAB_AI_API_KEY`: provider key, sent only as a Bearer header.
- `JAB_ZYTE_API_KEY`: Zyte API key for job URL imports and optional cover-letter company research, sent only by the backend to Zyte's `/v1/extract` and `/v1/search` endpoints using HTTP Basic authentication. Pasted job intake does not use Zyte; later cover-letter research may. Missing configuration does not prevent startup or manual job entry.
- `JAB_COVER_LETTER_RESEARCH_ENABLED`: `true` by default; accepts `true`/`false` or `1`/`0`. Research requires a Zyte key and a model/provider supporting function tools.
- `JAB_RESEARCH_MAX_SEARCHES`, `JAB_RESEARCH_MAX_PAGES`, `JAB_RESEARCH_TIMEOUT`: defaults `5`, `8`, and `300` seconds. Allowed ranges are 1-20 searches, 1-30 page reads, and 1-600 seconds. Final drafting and the single schema-repair attempt use `JAB_AI_TIMEOUT` separately.
- `JAB_ZYTE_SEARCH_DOMAIN`: search engine hostname, default `google.com`. Zyte must support the configured domain; unsupported-domain responses become research errors, not fabricated results.
- `JAB_AI_RESPONSE_FORMAT`: `prompt_json` (default) or `json_schema` when explicitly supported by the selected provider/model.
- `JAB_AI_MAX_OUTPUT_TOKENS`: default 8192; provider/model must accept this request limit.
- `JAB_AI_TIMEOUT`: default 120 seconds for provider network operations.
- `JAB_DATABASE`: defaults to `data/jab.sqlite3`; relative paths resolve against `Jab/`.
- `JAB_ALLOWED_ORIGINS`: comma-separated localhost frontend origins; default port 5173.

Restart after changing settings. Only the configured provider/model is used; there is no silent provider/model fallback. Model output must be text in the Chat Completions response shape. Invalid JSON/schema gets one repair attempt, recorded separately, except job intake, which requires explicit retry. Network, quota, authentication and layout failures require explicit retry. Failed/timed-out requests may already have been billed by the provider.

Requests, prompt versions, raw model responses, validated results, and supplied usage data are saved independently of user-edited content. Headers and credentials are excluded; known key values in returned provider text are redacted. Raw source text and model responses contain personal résumé/job information and stay in the local database. Configured inference calls send the necessary text to your provider.

## API workflows

All workflow routes use `/api/v1`. Reads return decoded JSON; lists use `items`, `total`, `limit` (25 by default, at most 100) and `offset`. Long operations return HTTP 202 with `task_id` and resource ID. Poll `GET /tasks/{task_id}` until terminal. A completed generation task can expose a partial/failed **run outcome** in its result; inspect run and document statuses rather than assuming every task completion produced two ready PDFs.

| Workflow | Routes and actions |
| --- | --- |
| Base résumé | `POST /resumes` with multipart field `file`; `GET /resumes`, `/resumes/active`, `/resumes/{id}`; `PATCH /resumes/{id}/draft` with `content`; `POST /resumes/{id}/activate` with `content` and `confirmed: true`; `POST /resumes/{id}/retry-extraction`; `GET /resumes/{id}/original` and `/captures` |
| Jobs | `POST /jobs` with `source_type: pasted` and `jd_text`, or `source_type: url` and `source_url`; `GET /jobs` and `/jobs/{id}`; `PATCH /jobs/{id}`; `POST /jobs/{id}/confirm`, `/archive`, `/intake`; `GET /jobs/{id}/captures`, `/jobs/{id}/documents` |
| Generation | `POST /jobs/{id}/runs` with optional `instructions`; `GET /jobs/{id}/runs`, `/runs/{id}`, `/runs/{id}/documents` |
| Review | `GET /documents/{id}`; `POST /documents/{id}/revisions` with edited `content`; `POST /documents/{id}/ai-revisions` with `instructions`; `POST /documents/{id}/render` to retry a non-ready revision; `GET /documents/{id}/pdf` (`?download=false` previews inline) |
| Applications | `POST /applications`; `GET /applications`, `/applications/{id}`, `/applications/{id}/events`; `POST /applications/{id}/stage`, `/notes`, `/corrections`; `PUT /applications/{id}/follow-up` |
| AI history | Run detail includes model calls; `GET /captures/{id}/ai-calls` exposes intake call history |

Jobs require company, title and the full JD before confirmation. Optional fields include location, expected/advertised salary, employment type, deadline, recruiter/reference details, tailoring instructions, and structured requirements. Expected salary is never inferred by the model. Editing a confirmed job returns it to review; reconfirm explicitly. Blocked URLs retain their source URL and accept pasted text through `/intake`. Missing AI configuration or extraction failure still allows manual completion.

Drafting requires an active reviewed résumé and confirmed job. Manual and AI revisions preserve past content and files. AI revisions freeze the current approved base/job plus the chosen prior document and requested changes. Manual revisions retain the original run's frozen baseline. Add genuinely new candidate facts to the base résumé, approve it, then create a new run.

Résumés retain one-page Inter styling; cover letters use their own two-column Roboto template, 250–350 body words in three or four paragraphs, on one US Letter page. Optional `emphasis` values must be exact substrings of a claim's text. Stable IDs remain internal metadata. Claim `source_refs` are optional legacy metadata, are not printed, and are not required for PDF creation.

Only explicit submission recording creates an application. For `origin: jab`, supply company, role, job, applied date and exact ready résumé ID; letter ID is optional. External applications can omit job, files and unknown applied date. Stages: applied, screening, interviewing, offer, accepted, rejected, withdrawn. Follow-ups store actions/dates without scheduling notifications. Corrections require a reason and append old/new values. Job-scoped ready document selection uses `/jobs/{id}/documents?status=ready`; application lists accept `job_id`. Original résumé previews use `/resumes/{id}/original?download=false`. Job detail exposes `active_tasks` across intake, preparation and document work. Lists support company/role search; application filters include stage and `due_before`.

## Checks and failures

Preparation snapshots the reviewed base résumé and confirmed job, writes both documents with AI, then renders PDFs directly for human review and download. There is no Python factual/source-reference approval or separate AI review. JSON/schema decoding and bounded malformed-response repair remain. Manual and AI revisions use the same rendering-only path. A ready PDF means rendering succeeded, not that its facts were approved. Review wording and facts before applying.

Migration 006 replaces only the PDF-publication trigger: the latest PDF check must pass; historical structure, factual and AI-review failures no longer block publication. No tables are rebuilt and no findings or drafts are deleted. Existing failed drafts can use Retry PDF creation without new writing calls. Historical preparation status records the original attempt and is not rewritten. Restart the backend to apply the migration.

The renderer accepts escaped structured text, never model-written LaTeX. It uses isolated working directories, shell escape disabled, a 60-second compilation deadline, and controlled font settings. It checks logs, a single page of the correct size (A4 for résumés, US Letter for cover letters), extracted text, glyphs, word bounds and hyperlink destinations/labels. Cover letters also check column separation and boxed-column height. It reports overflow instead of shrinking typography or automatically making extra model calls.

Job URL imports use Zyte browser rendering (`browserHtml: true`). The rendered HTML is saved unchanged in `intake_captures.captured_text` and sent directly to the job-extraction AI with `input_format: html`, `source_content`, and `source_url`. No HTML parser, local metadata override, or literal evidence filter runs in this import path. The job URL is sent to Zyte; candidate résumé data and AI credentials are not sent to Zyte. The rendered job page is sent to the configured AI provider. No Zyte structured extraction, Playwright installation, or additional Python dependency is required.

One AI response supplies a complete cleaned plain-text `jd_text`, structured job fields, requirements, informational evidence, and review findings. The prompt asks the model to preserve all substantive content and resolve relevant visible content and embedded metadata, without summarizing, inventing missing facts, or following webpage instructions. Python checks the response structure, types, and nonempty URL description; it does not clear extracted facts based on evidence matching. A null URL description reports an unusable posting. Pasted descriptions use `input_format: plain_text` and the same extraction contract, but their stored description remains exactly as entered, regardless of the AI's returned wording. Descriptions, fields, source URL, and requirements are saved together only after successful extraction. Failed re-imports preserve saved job details and retain the new source capture. New failed URL imports can be completed manually or retried. Existing records are not rewritten automatically. No database migration is needed.

Extraction must copy source wording verbatim for the description, scalar fields, and every responsibility or qualification. Cleanup only removes markup and unrelated page content, decodes HTML entities, and adjusts layout whitespace and bullet formatting. It must not paraphrase, correct spelling, translate, assemble a new location phrase, or normalize salary and date values. Findings can explain ambiguity; evidence must quote the source. `application_deadline` is nullable text in both extraction and job-edit API contracts, so advertised wording such as `30 November 2026, 17:00 CET` is stored and edited as written. Historical ISO date strings remain valid. The existing SQLite TEXT column needs no migration. Application tracking dates and follow-up dates retain their existing date validation. The supplied job URL is preserved directly by the backend.

Job extraction makes one AI call per attempt, with no automatic schema-repair call. Malformed output, truncation, and provider failures are recorded and require an explicit retry. Other AI operations retain their existing bounded repair behavior. `JAB_AI_JOB_MODEL` and the existing response-format and output-token settings still apply; returning the full description consumes output tokens, so raise `JAB_AI_MAX_OUTPUT_TOKENS` if the provider reports truncation. No automatic output shortening is performed. AI cleanup and extraction still require user review; schema checks cannot prove factual accuracy or completeness.

Set `JAB_ZYTE_API_KEY` in `.env` and restart. Each URL intake attempt makes one paid provider request, without automatic retries or fallback to direct HTTP. Provider errors, rate limits, missing configuration, and unusable pages appear in existing task errors; users can retry explicitly or paste the full description. Zyte duration and error code are logged alongside task logs, without credentials or raw provider error bodies.

Submitted and returned final URLs must pass public HTTP/HTTPS URL validation. Zyte manages browser redirects and subrequests remotely; local DNS pinning does not apply to that remote navigation. The old public-only, DNS-pinned direct fetcher and its text parser remain available internally and tested, but are not the default intake path. Zyte retrieval has a 90-second deadline, a 20 MiB decompressed API-response limit, and a 5 MiB rendered-HTML limit. Job HTML input, pasted descriptions, cleaned AI descriptions, and job edits have no application character-count cap and are not truncated. The existing HTTP request-body size limit and the configured model's context window, output-token budget, and timeout still apply; provider failures require explicit retry. Pages requiring login, expired postings, challenges, and incomplete content may still need paste fallback. Successful retrieval alone does not prove a complete description; review the imported content before confirming.

JSON request bodies are limited to 2 MiB. Unexpected browser origins cannot make mutations. This is a loopback-only personal backend, without accounts.

To validate a Zyte setup, use an isolated test database and import `https://voucherify.bamboohr.com/careers/82` (if still active) plus two other active job postings. Compare the captured responsibilities and qualifications against the visible posting, then check AI fields and review status. Do not use HTTP success alone as the acceptance check. Provider-mocked regression tests require no live key or paid requests.

Errors use `{error: {code, message, fields, retryable}}`: missing resources 404, state/constraint conflicts 409, oversized input 413, invalid input 422, unavailable configuration/tools 503. Background errors live on the task and relevant source/run/revision. Logs include task IDs, steps, durations and sanitised codes; no raw résumés, prompts or credentials.

## Tasks, persistence and recovery

One worker executes persisted tasks; one process lock protects each data directory. Do not use Uvicorn reload or multiple workers. Conflicting work is rejected. Each operation uses a short transaction; nested repository work uses savepoints so resource+task creation is atomic. Do not hold database transactions across network calls or compilation.

At startup, old queued/running tasks and generation/AI/capture operations become interrupted. Successful documents and saved edits survive. Retry explicitly; Jab never replays paid requests automatically. Shutdown waits for current work; if the process is killed, restart recovery identifies unfinished work.

```text
data/
  jab.sqlite3
  backend.lock
  originals/   # generated names; immutable source PDF/DOCX
  pdfs/        # generated names; immutable ready exports
  tmp/         # short-lived artifact writes
```

Paths are relative to the database directory. Never overwrite a ready file or edit an approved résumé in place. A changed source creates a new version. Files publish before the database marks them ready; a failed commit may leave an orphan file. `storage.orphan_files` reports these without deleting data. Downloads, submissions, full checks and backups reject missing/hash-changed files.

Database commands, from `Jab/`:

```sh
.venv/bin/python -m backend.database init
.venv/bin/python -m backend.database check
.venv/bin/python -m backend.database backup --destination ../Jab-backup-2026-11-05
.venv/bin/python -m backend.database restore --bundle ../Jab-backup-2026-11-05 --destination ../Jab-restored-data
```

Ordered migrations preserve existing data and verify checksums. Never modify an applied migration. Backup reserves writes while snapshotting SQLite and copying referenced originals/PDFs, then verifies the result. Destinations must be new and outside live data. Restore validates into a new directory; stop the backend before changing `JAB_DATABASE` to it. Unfinished restored work is interrupted on startup. Backups include task/history rows and omit orphan files, locks and compilation caches.

## Verification

```sh
.venv/bin/python -m pytest tests -q
```

Tests cover original persistence operations, all five HTTP workflows, mocked inference and repair, real PDF rendering, exact reference raster comparison, DOCX/table and PDF extraction, scanned-file rejection, URL restrictions, task conflicts/recovery, immutable submissions and backup/restore. The test suite uses temporary databases and never writes fixture candidate data into your live database.

Live provider authentication, model quality, latency and billing require a successful connectivity check; mocked retrieval and inference tests cover the network boundaries. The frontend is implemented. OCR, auto-applying and notifications remain outside this milestone.

The implementation-time smoke check used only public company queries and synthetic candidate data in
a temporary database. Zyte failed with `ConnectError` and inference failed with
`provider_network_error`, so live Search API access, search-domain acceptance, and model tool support
remain unverified in this environment.

## Cover-letter company research

For every cover-letter draft and AI revision with research enabled and configured, the backend forces
`search_web(query)` first, then `read_page(url)` until a search and a page read succeed. Sonnet 5.5
uses `tool_choice: auto` because it rejects provider-level forced choices; backend validation still
requires both research steps. Other models use a named tool choice for the missing step. The backend rejects
premature final text or a model that ignores the required tool, rather than saving an unresearched letter.
Python performs searches through Zyte Search API and reads rendered pages through Zyte
Extract API. No Playwright installation is required. The model decides which queries and pages are
useful and may finish after the required research succeeds; Python enforces the configured request/time
budgets and
a 16-inference research-turn limit. Repeated identical tool requests reuse cached results. Failed
external requests count toward the budget and are not automatically retried.

Searches return up to ten organic results. Page observations retain requested/final URLs, titles,
retrieval times, up to 20,000 characters of readable text, and up to 30 links, with a text truncation
flag. Submitted and returned page URLs must pass public-URL validation. Zyte manages remote redirects
and subrequests, as with job intake. Candidate names, contact values, email patterns and long phone-like
numbers are rejected in research arguments as a best-effort privacy check; prompt instructions also
prohibit sending personal candidate details. Search/page results are untrusted source data.

The task reports researching/searching/reading steps through existing progress polling. Every model
turn, tool result and source is stored in `ai_calls`; the final document points to its successful final
inference. `GET /runs/{id}` adds `research` with status, request counts, stopping reason and source
URLs/titles/retrieval times. Full captured evidence remains in call history. Existing run snapshots
and the letter JSON contract are unchanged; no database migration is needed.

Cover-letter revisions receive previously captured evidence from their source document's run, but
still perform the required fresh search and page read. Research disabled/missing credentials skips tool
advertising. Tool rejection or an unrecoverable research error falls back to ordinary drafting with available evidence.
Individual retrieval errors are returned to the model so it can choose another source. These fallbacks
apply to observed failures or exhausted budgets, not a model choosing to skip research.
Successful drafting records `model_finished_after_research`; it does not assert that the evidence is sufficient.
Historical `enough_evidence` records remain readable. Résumé preparation, job intake, and response repair remain tool-free.

## Explicit résumé link override

`POST /resumes/{id}/activate` accepts `override_invalid_links: true` alongside `confirmed: true`. Only link-format findings can be waived. Missing names, duplicate source IDs, schema errors and other structural issues still block activation. Error fields expose `can_override_links` when all activation findings are eligible. The UI shows **Override and activate as is** after such an error, with the existing review checkbox still required.

Migration 004 adds immutable `resume_versions.validation_overrides_json`. Approval is recorded with the exact reviewed content and copied into each new preparation snapshot. Base-résumé activation still checks link formatting; generated documents now go directly to rendering without factual approval. Invalid values print as escaped plain text, never clickable links. Editing an approved base résumé requires fresh approval for its new version. Restart the backend after this upgrade so migration 004 is applied before using the new button.

## Hyperlink-aware content (version 2)

New content uses `schema_version: "2"`. Version 1 content is adapted for API/service use while persisted raw JSON, frozen run snapshots and ready PDFs retain their original bytes. No SQL changes are needed for this content update. `backend/content.py` owns adapters and link traversal.

- `Claim.links`, `Entry.title_links`, and `Entry.organization_links` contain `start`, `end`, `url`, `source_link_id`, and optional `unresolved_label`. Offsets are Unicode code points, start inclusive/end exclusive.
- `Contact.links` contains labelled objects (`id`, `label`, `url`, optional `source_link_id`). Old string URLs receive stable legacy IDs and identical labels/targets.
- A separately displayed entry link uses `link`, `link_label`, and `link_source_id`; inline heading links do not require appending a raw URL.
- Top-level `unresolved_links` retains destinations the parser could not associate uniquely. Unresolved/overlapping spans block approval and cannot be bypassed by the invalid-link override.

`POST /resumes/{id}/reimport` queues extraction into a new child résumé version sharing the verified original file. It leaves the active version unchanged. Concurrent re-imports of the same file hash are rejected. The new version’s parent remains available for comparison so later manual edits are not silently lost.

PDF extraction uses Poppler XML hyperlink fragments with source block/page/rectangle evidence. DOCX extraction resolves relationships per part and supports ordinary hyperlinks plus simple/complex external `HYPERLINK` fields. No target is fetched. Unsupported or ambiguous destinations are retained for review rather than guessed. Internal navigation and non-web actions are not turned into active external links.

The renderer supports links combined with bold emphasis and verifies exported destinations and linked labels after compilation. Résumés retain the fixed blue Inter styling. Cover letters use a separate Roboto template with deep teal (`#0F6B70`) role and link accents, black text and top rule, and gray dates. The approved contact block uses 10 pt text with 14 pt leading, omits the repeated name, splits saved location components at `|`, and groups location/phone, email, and professional links with fixed spacing. Website and LinkedIn headings appear above full clickable URLs; other HTTP(S) links use Website, while other link types retain their saved heading. Long URLs and emails wrap without shrinking. Text and hyperlink verification checks this displayed presentation without changing stored contact labels or destinations. Poppler may split an annotation into several fragments or associate adjacent punctuation with its rectangle; source ambiguities are exposed for user review. Approved malformed values stay escaped plain text. Prompt version is `jab-prompts-13`; résumé rendering version is `inter-3` and cover-letter rendering version is `progress-2`. New mixed preparation runs record `inter-3,progress-2`; AI revision runs record the selected template. PDF validation metadata records the template used for each newly rendered version, including manual revisions. Historical run metadata and existing PDFs remain unchanged.

New AI cover letters and AI revisions receive the computer’s local current_date and must return it as content.letter_date (YYYY-MM-DD). The returned value is validated, persisted in existing document JSON and displayed as an English date (for example, `7 November 2026`) by the renderer. Legacy letters may omit it; saved PDFs and manual revisions retain their original date unless explicitly edited. No SQL migration is required.


## Independent document selections

Each job persists a separate selected résumé and cover letter. `GET /jobs/{id}/documents` accepts `kind=resume` or `kind=cover_letter` and returns job-wide `version_number` values across preparations. `GET /jobs/{id}/document-selections` reads the pair; `POST` with `document_id` changes only that document type. Version selection accepts saved drafts for review; submission still requires ready PDFs. Successful PDF publication selects its document type; failed generation/rendering preserves existing selections. AI rewrites freeze the exact source document and selected companion in their input snapshot.

Migration 007 adds the selection table and seeds existing jobs with their latest ready version of each type. Historical PDFs, content, revision numbers, application submissions and input snapshots remain unchanged. Restart the backend to apply the migration. The document UI uses independent histories; generation attempts are retained separately as activity. See [DOCUMENT-WORKSPACE.md](../DOCUMENT-WORKSPACE.md).
