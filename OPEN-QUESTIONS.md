# Jab — open planning questions

Updated: November 5, 2026.

This file retains the original planning questions. The backend and frontend implementation decisions at the end resolve many of them; [README.md](README.md) describes current behavior and outstanding verification.

Use this checklist alongside [PLAN.md](PLAN.md) and [DATABASE.md](DATABASE.md). Record answers in the relevant planning document and mark questions resolved here. Proposed defaults are not confirmed decisions.

## Discussed details to incorporate

These are documentation follow-ups from the conversation, rather than new questions for the user.

- [x] Document AI extraction for both a supplied URL and pasted JD text.
- [x] Document the three required fields before tailoring: company, job title, and full job description.
- [x] Document optional source URL, location/work arrangement, and additional user instructions. Capture salary, deadline, employment type, recruiter details, and job reference number when available without requiring them.
- [x] Describe the review step where the user corrects extracted job details before generation.
- [x] Specify storage of original intake content and extraction results separately from confirmed job details.
- [x] Add storage of the original AI response separately from validated document content, review findings, and user-edited revisions.

## 1. AI provider, model, and cost

- [ ] Which AI provider and model should Jab use initially?
- [ ] What budget is acceptable per application or per month?
- [ ] Should extraction, drafting, and review use the same model?
- [ ] What content needs to be sent to the provider, and what generation settings should be recorded with each run?

## 2. Résumé tailoring and factual rules

The plan already proposes that Jab must not invent facts and should preserve the approved résumé format. Define the operational rules below.

- [ ] Which sections can be rewritten, reordered, shortened, or omitted?
- [ ] Which facts must remain unchanged, including employer names, titles, dates, qualifications, and metrics?
- [ ] How should relevant JD terminology be used when the base résumé does not explicitly support it?
- [ ] How should missing or ambiguous evidence be presented for user clarification?
- [ ] What checks must a draft pass before it is ready for review and export?
- [ ] How should content be reduced to fit the one-page résumé template, and when must Jab stop and ask for edits?

## 3. AI inputs and response structure

- [ ] What is the exact input contract for job extraction, document drafting, and review?
- [ ] What structured fields should the AI return for the résumé and cover letter?
- [ ] How should review findings identify unsupported claims, missing information, and suggested corrections?
- [ ] Which parts of the original response and request metadata should be retained, excluding secrets?
- [ ] How should invalid or incomplete responses be handled without losing valid content?
- [ ] How many automatic revision attempts, if any, should occur before user review?

## 4. Cover letter

- [ ] What fixed cover-letter layout should Jab use alongside the approved résumé template?
- [ ] What length, tone, and structure should it follow?
- [ ] How should recipient details, address, salutation, and date work when information is missing?
- [ ] Which writing preferences and phrases to avoid should be included in its instructions?

## 5. Screens and editing experience

The proposed navigation is Base résumé, Jobs, and Applications. Wireframes remain pending.

- [ ] What should the first-use résumé upload and review screen show?
- [ ] How should URL entry, pasted JD entry, and extracted-field review fit together?
- [ ] How should the user edit a generated résumé while preserving its template structure?
- [ ] Should résumé and cover-letter review appear together or in separate views?
- [ ] How should previous document revisions, review findings, and PDF previews be accessed?
- [ ] What information and actions belong in the application list and detail view?
- [ ] Which proposed application stages and next-action fields should ship in the MVP?

## 6. Failures and recovery

The plan already proposes pasted-text fallback, preserving partial results, and retrying interrupted runs. Specify the exact behavior and messages.

- [ ] What happens when a PDF/DOCX is unreadable, incomplete, encrypted, or unsupported?
- [ ] Is OCR for scanned PDFs in the first release, or should Jab request a text-based file/manual correction?
- [ ] What happens when a JD URL is blocked, expired, login-only, or requires JavaScript?
- [ ] What happens when AI generation times out, returns invalid content, or produces only one document successfully?
- [ ] What happens when a generated PDF overflows, clips content, or fails text checks?
- [ ] What should the user see after closing Jab during a run and reopening it?

## 7. Database and implementation readiness

The ten-table SQLite persistence layer, integrity rules, workflow operations, and verified backup/restore are implemented. The current suite has 36 passing backend tests and eight passing frontend contract/render tests. See [DATABASE.md](DATABASE.md) and [backend/README.md](backend/README.md). Versioned content contracts and the HTTP backend are implemented. The UI is implemented; interactive browser checks and live provider/model quality verification remain open. Provider/model/key are supplied through .env using a compatible inference endpoint.

- [x] Finalise table columns, nullability, constraints, indexes, and migrations after the intake and generation contracts are settled.
- [x] Define where original AI responses and extraction results fit in that schema.
- [ ] Verify and pin compatible dependency versions in isolated project environments.
- [ ] Define exact installation, frontend build, and local start commands.
- [ ] Define API-key configuration and checks for missing credentials.
- [x] Define backup location, backup workflow, and restore verification.
- [ ] Write acceptance checks for the complete upload → prepare → review → export → record application journey.

## Suggested next planning session

1. Incorporate the already-discussed intake details into the plan and database design.
2. Define the tailoring workflow and AI input/output contracts.
3. Choose the AI provider/model and define the cover-letter format.
4. Sketch the core screens, finalise failure behavior, and complete the implementation gate.

## Backend implementation decisions

- Provider-neutral Chat Completions adapter; configured endpoint/model/key in ignored `.env`.
- Seven versioned prompts adapted from `resume-tailoring/`; see backend/prompts/README.md.
- One schema repair attempt; explicit retries for other failures.
- One-page Inter résumé and matching 250-350-word cover letter.
- Ten domain tables after the additive backend task/requirements migration.
- HTTP contracts, local start commands, recovery and verification are documented in backend/README.md.
- Live model quality/cost, optional parser-library paths, and interactive frontend behavior still need validation.

## Frontend implementation decisions

- Three navigation sections: Base résumé, Jobs, Applications; all five workflows fit within them.
- Warm light surfaces, charcoal text, green actions, a compact sidebar, and local system typography.
- Structured content editor with saved PDF beside it; résumé/letter tabs, preparation history and immutable revisions.
- Exact document selection and explicit submission confirmation before recording a Jab application.
- Table-based application tracking with dated notes, stages, follow-ups, corrections and submitted PDF access.
- React/TypeScript/Vite and plain CSS, hash navigation, polling, and same-origin FastAPI static delivery.
- Root `./start.sh` launcher and complete setup instructions in README.md.
- Interactive browser/responsive visual verification and live model quality/cost remain unverified because this sandbox blocked Chrome and loopback binding, and provider credentials are not configured.

## Hyperlink preservation implementation

- Content schema 2 stores source-backed inline spans and labelled contact links in existing JSON fields. No new SQL migration is required.
- Authoritative extraction uses installed Poppler XML and bounded DOCX relationship/field parsing. The original PDF’s seven destinations and labels were recovered.
- The editor supports phrase selection, link targets and explicit recovery after text edits. Re-import creates a separate child draft and exposes the previous reviewed version for comparison.
- Controlled PDF output preserves blue links and bold emphasis, and verifies destinations/labels. Existing invalid-link override values remain plain text.
- Version 1 records and historical PDF bytes remain readable and unchanged. Live-provider quality and interactive browser checks remain open due sandbox restrictions.
