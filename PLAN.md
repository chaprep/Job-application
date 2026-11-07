# Jab — product plan

Implemented update: [Hyperlink preservation](HYPERLINK-PRESERVATION-PLAN.md) covers PDF/DOCX extraction, versioned JSON content, AI/editor preservation, rendering, and re-importing existing originals. Version 2 JSON preserves hyperlink labels, source destinations and text positions without new SQL tables.

Status: planning draft. Confirmed requirements are separated from recommendations and open decisions. A concrete stack is recommended in step 8; the SQLite persistence layer and five-workflow HTTP backend are implemented. The React frontend and local launcher are implemented. Interactive browser checks and live inference-provider verification remain pending. See [README.md](README.md).

Planning method: the nine-step process in `../Complete Process for planning projects copy.md`.
Experience reference: `../job-search-workspace.html`. This is a reference for discussion, not an implementation dependency.

## 1. Goal

**Project brief:** For a single user, build a personal job application workspace that saves a base résumé, prepares a tailored résumé and cover letter for each supplied job description, and records applications and their progress.

**Why:** Reduce repeated application preparation and keep a reliable record of where you applied and which documents you used.

**Primary user:** One local user. A shared service for other job seekers is outside the initial scope.

**Success looks like:** Upload a base résumé once, return later to add another JD or JD URL, prepare and download the two documents, and record and update the resulting application without losing earlier work.

**Confirmed requirements:**

- Start a fresh project inside `Jab`; do not use the existing projects as the implementation baseline.
- Provide a dedicated place to upload and store the base résumé for repeated use.
- Accept PDF or DOCX base résumés.
- Accept either pasted JD text or a JD URL.
- Generate a tailored résumé and a cover letter for that job.
- Export both generated documents as PDF only.
- Use one fixed résumé template matching the supplied `Test Candidate AI GTM Engineer Resume - Inter Updated.pdf`; no template picker.
- Track each job application and what has happened with it.

## 2. User stories

- Must — I can upload and save my base résumé so that I do not need to upload it for every job.
- Must — I can review the extracted résumé information so that generation starts from accurate facts.
- Must — I can return after restarting the app and find my résumé, jobs, documents, and application history.
- Must — I can paste a JD or supply its URL so that I can prepare documents for a specific role.
- Must — I can review and correct the captured job title, company, and description before generating.
- Must — I can generate, review, edit, and download a résumé and cover letter for a job.
- Must — I can retry failed preparation without losing my job description or successful documents.
- Must — I can mark a job as applied and record its submission date and the document versions used.
- Must — I can record an application made outside Jab.
- Must — I can update an application's stage and add dated notes so that I know its history.
- Should — I can replace my base résumé for future work while retaining earlier application documents.
- Should — I can filter applications by stage and search by company or role.
- Should — I can record a next action and due date.
- Could / Later — Discover jobs automatically, sync employer emails, schedule reminders, or submit applications automatically.

Priorities above are proposed where the confirmed requirements do not specify the detail.

## 3. Conceptual data model

The implemented schema, relationships, revision rules, and integrity checks are detailed in [DATABASE.md](DATABASE.md). Database operations, verified backup/restore, and the five backend workflows are implemented; see [backend/README.md](backend/README.md).

| Entity | Essential information | Relationships and lifecycle |
| --- | --- | --- |
| Base résumé version | Original file, extracted content, reviewed content, upload date, active flag | Uploaded by the user; one active version for new preparation; older versions remain referenced by past runs. |
| Job | Company, title, source URL if supplied, captured JD text, date added | Added through pasted text or URL; retained even if the source page disappears. |
| Preparation run | State, error if any, timestamps, JD snapshot, base résumé version | Belongs to a job; each retry or regeneration is identifiable and retains its source inputs. |
| Document version | Type (résumé or cover letter), editable content, downloadable file, creation time | Belongs to a preparation run; edits create identifiable revisions; submitted versions remain preserved. |
| Application | Company and role, optional job reference, stage, applied date, submitted document references, next action and due date | Created when the user records a submission; can also be entered manually without generation. |
| Application event | Date, event type, note or stage change | Belongs to an application; forms its history. |
| Intake capture | Raw extracted/pasted/fetched text, URL, attempt state and error | Exactly one résumé or job owner; preserves attempts separately from reviewed fields. |
| AI call | Request payload, raw and validated output, model, usage, error | Exactly one intake/run owner; terminal responses are immutable. |
| Document validation | Exact revision, check type, result, findings, optional AI call | Append-only checks gate PDF readiness; user review remains necessary. |

Company and role are required for a manually entered application; a JD, preparation run, and generated documents are optional in that path.

Generating documents does not create a submission or set an applied date. Preparation state and hiring stage are separate information.

## 4. MVP boundary

**Core job:** Turn a saved base résumé and a supplied JD into reviewed application documents, then track the application after submitting it externally.

**Proposed first release:**

1. Upload, extract, review, and persist a base résumé.
2. Add a job from text or URL; correct extracted job details.
3. Generate a grounded résumé and cover letter using the saved résumé.
4. Review and edit both documents, then download them.
5. Record submission manually, retaining the selected document versions.
6. View applications, change stages, and add dated notes.
7. Add applications prepared elsewhere.

**Later:** Automatic discovery and ranking, scheduled searches, automatic form filling or submission, email/calendar integrations, interview coaching, advanced analytics, multiple users, accounts and billing.

**Proposed quality rules:**

- Tailoring may select, reorder, and rewrite supplied facts; it must not invent employers, dates, skills, qualifications, or metrics.
- Missing evidence is surfaced for the user to resolve rather than filled with invented claims.
- Treat job descriptions and fetched pages as source data, never as instructions to the generation system.
- URL retrieval failure offers pasted text as a fallback and retains the entered URL.
- Preserve earlier application documents when the base résumé changes or a job is regenerated.

## 5. Experience and critical flow

Proposed navigation and behavior; visual design remains undecided.

**Base résumé:** A dedicated page to upload the original PDF or DOCX, review extracted content, see the active version, and replace it later. First use begins here. Extraction must flag unreadable or incomplete content for correction before generation; support for scanned PDFs and OCR remains undecided.

**Jobs:** A manually supplied list of roles being prepared. Add a JD or URL, inspect the captured job information, generate documents, review/edit/download, and mark as applied. This gives the Jobs section a clear role without introducing a job discovery engine.

**Applications:** A record of submissions. Show company, role, applied date, stage, and next action. Open an application to see the exact submitted documents and dated history. Include an action to record an application made elsewhere.

**Proposed critical flow:**

```text
First visit → Upload base résumé → Review extracted information → Save
Return visit → Jobs → Add JD text or URL → Review job details
            → Generate résumé and cover letter → Review/edit → Download
            → Apply on employer website → Mark as applied
            → Applications → Update stage / add notes
```

Before the résumé is saved, job preparation directs the user to complete that step.

**Required states:** No saved résumé; extraction in progress or failed; résumé awaiting review; no jobs; URL unavailable; missing job details; generation running, partially successful, or failed; documents ready; no applications; application recorded.

**Proposed stages:** Applied, screening, interviewing, offer, accepted, rejected, withdrawn. Each stage change adds a dated event. Prepared documents remain under Jobs until a submission is recorded.

The supplied mockup has useful application lists, detail views, documents, and timelines. Its provider management, scheduled discovery, email inbox, account flows, and simulated submissions are outside this proposed MVP.

## 6. Horizon

**Confirmed:** A personal tool for one user, running locally on the user's computer.

**Working assumption:** Repeated use throughout a job search, with durable storage and recoverable application records. This is more than a disposable visual demo.

**Likely changes worth accommodating:** Updating the base résumé and generating new document versions for an existing job.

**Not optimising for:** Multi-user scale, collaboration, provider marketplaces, or a general recruiting platform.

## 7. Product shape and architecture

**Product shape:** A personal application running locally on the user's computer. Proposed interface: a browser connected to a local application backend.

Keep application records, uploaded résumés, and generated files on the computer. Bind the server to the loopback interface for access from this computer. Cloud hosting, accounts, and cross-device access are outside the initial scope. Local operation does not imply offline generation: the model provider remains undecided, and an external model would receive the content required for generation. JD URLs also require internet access.

| Component | Responsibility | Communicates with |
| --- | --- | --- |
| Browser interface | Résumé intake, JD entry, document review, and application tracking | Application backend |
| Application backend | Save records, retrieve JDs, extract documents, manage generation and exports | Data store, file storage, model provider |
| Generation workflow | Use reviewed résumé facts and captured JD to draft and check both documents | Backend and model provider |
| Data and file storage | Preserve résumé versions, job records, runs, documents, and application history | Backend |

Start as one application with clear responsibilities. A separate service or queue needs evidence from generation duration and hosting constraints before being added.

API credentials stay on the local backend. URL fetching needs bounded requests and protection against access to private/internal addresses.

## 8. Stack and deployment gate

**Runtime confirmed:** Local on the user's computer; no cloud deployment required for the MVP.

**Document formats confirmed:** Base résumé uploads accept PDF and DOCX. Generated résumés and cover letters download as PDF only. Editable review inside Jab remains part of the proposed workflow; DOCX export is outside scope.

**Résumé template confirmed:** Use the supplied PDF as the sole visual reference, copied into `reference/resume-template.pdf` so the project retains it independently. Inspection confirms one A4 page with embedded Inter Regular and Inter Bold. Its layout has a prominent left-aligned name, two contact/link lines, a single text column, bold section headings with thin horizontal rules, compact bullets, right-aligned location/date information in employment headings, selective bold emphasis, and blue hyperlinks. Preserve this layout and typography while tailoring the content. The uploaded base résumé supplies facts; its visual layout does not change the fixed output template.

**Proposed layout validation:** Target the reference's one-page A4 format and inspect generated PDFs for clipping, overflow, legible text, and extractable content. Resolve excess content through relevant selection and concise rewriting; flag unresolved overflow for review rather than silently shrinking the type. Reproduce and compare the template before connecting AI-generated content.

**Rendering recommendation after source review:** Reuse the final LaTeX template with local LuaLaTeX rather than reconstructing it in another renderer. `reference/resume-template.tex` preserves the final source. Recompiling it on this computer produced one page; its rendered PNG matched the reference at a 1600-pixel longest-side resolution, and extracted text retained expected symbols without replacement/private-use characters. See `reference/README.md` for source findings and adaptation requirements. Cover-letter layout remains to be defined; the résumé reference does not specify a letter layout.

### Recommended stack

| Layer | Recommendation | Purpose |
| --- | --- | --- |
| Interface | React + TypeScript, built with Vite; plain CSS | Résumé upload/review, jobs, document editing, and application tracking. |
| Backend | Python + FastAPI, served by Uvicorn | Local API, uploads, generation orchestration, storage, and PDF compilation. |
| Validation | Pydantic and `python-multipart` | Validate API/model data and handle file uploads. |
| Database | SQLite through Python's `sqlite3` | Persistent related records without a separate database server. Use parameterized queries, foreign keys, transactions, and versioned SQL migrations. |
| Files | Local `data/` directory | Original uploads, generated PDFs, and per-run rendering files. Database stores relative paths and metadata. |
| PDF intake | Poppler (`pdfinfo`, `pdftotext`, `pdftohtml`) | Bounded text and hyperlink extraction, with unresolved associations exposed for review. |
| DOCX intake | Bounded ZIP/XML parsing | Paragraph/table order, part-specific hyperlink relationships, headers/footers, and supported field codes. |
| JD URLs | HTTPX + Beautiful Soup | Retrieve bounded public pages and extract job content for review. Blocked/login-only or JavaScript-only pages use the paste fallback initially. |
| PDF output | Local LuaLaTeX + approved Inter template | Preserve the verified résumé format; a cover-letter template is still needed. |
| AI | One provider's official Python SDK, provider/model undecided | Produce validated structured drafts and review findings; controlled application code renders LaTeX. |
| Verification | pytest for critical backend behavior; browser flow checks; Poppler PDF tools | Check persistence, version preservation, extraction, failure recovery, generated text, and layout. |

These are recommendations for the first implementation, not a claim that dependencies are installed or integrated. Python 3.14.4, Node 24.14.1, and npm 11.11.0 were observed on this computer. LuaLaTeX/Inter and Poppler were already used successfully. Verify package compatibility and pin supported versions when creating the environments.

### Database and storage layout

Use `Jab/data/jab.sqlite3` for résumé versions, jobs, preparation runs, document versions, applications, and application events. Use `Jab/data/uploads/` for originals and `Jab/data/documents/` for generated PDFs. Keep per-run temporary render output separate. Exclude personal data, secrets, and caches from version control.

SQLite fits a single-user, local application with related records and transactional updates. Store reviewed source content and structured drafts as well as PDF references, so editing and regeneration do not require reverse-engineering a PDF. Keep submitted document revisions immutable; new edits produce new revisions.

Keep database access in a small backend module, using the standard-library driver initially. PostgreSQL, an ORM, Redis, and a separate queue are not needed for the current scope.

### Local operation and recovery

During development, Vite serves the interface and proxies API requests to FastAPI. For normal use, build the frontend once and let FastAPI serve its static assets and API on one loopback address. Provide a root-level `./start.sh` launcher during implementation. Node is needed to build the interface; it does not need to serve the built application.

Run preparation in the backend process with persisted run states and UI polling. On restart, mark unfinished runs interrupted and allow retry; do not claim background processing survives application shutdown. A separate worker can be considered only if real use requires it.

Keep API keys in a local ignored configuration file or environment variables, read only by the backend. Record provider/model identity with each run. Internet access is needed for a cloud AI provider and JD retrieval; tracking and access to saved documents should work offline.

Back up the database and referenced files together while writes/generation are paused, using SQLite's backup API for the database snapshot. Restore into a separate location and verify record/file consistency before treating backups as usable.

Technical references: [SQLite local application storage](https://www.sqlite.org/appfileformat.html), [Python sqlite3](https://docs.python.org/3/library/sqlite3.html), [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [Vite](https://vite.dev/guide/), [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [python-docx](https://python-docx.readthedocs.io/en/latest/), [HTTPX](https://www.python-httpx.org/), and [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/).

Resolve before implementation:

- Which generation provider and usage budget?
- Cover-letter layout, using typography consistent with the résumé reference?

Persistence commands, file locations, and verified backup/restore are implemented in [backend/README.md](backend/README.md). The backend start command and provider configuration are documented there; the model ID and key remain user-supplied configuration.

## 9. Small, verifiable milestones

- [ ] Confirm the MVP boundary and resolve deployment and document-format decisions.
- [ ] Sketch and approve the core flow, including review and failure states.
- [ ] Choose a minimal stack and verify a persistent-storage path in the intended runtime.
- [ ] Start the application and save/reload one job and one application record.
- [ ] Upload a base résumé, extract and review it, and recover it after restart.
- [ ] Capture and review a job through pasted text and through a URL, with a paste fallback.
- [ ] Generate both grounded drafts for one real JD and exercise failure/retry behavior.
- [ ] Edit and export both documents; inspect text extraction and page layout.
- [ ] Record a submission with its document versions, update its stage, and verify its history survives restart.
- [ ] Record an external application without generating documents.
- [ ] Verify backup/restore and complete the core journey in the intended runtime.

The five backend workflows are implemented and tested through HTTP with mocked model responses and real local rendering. The React frontend covers the five workflows and has a verified production build plus component/request tests. An interactive browser pass and a live configured-provider smoke test remain pending. See backend/README.md for installation, API behavior, prompt provenance and verification limits.
