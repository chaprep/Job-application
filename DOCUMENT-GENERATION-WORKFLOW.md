# Workflow 3: Document generation

Status: backend workflow implemented and covered by HTTP integration tests with mocked AI where applicable. Real PDF rendering is exercised. The React frontend is implemented; live-provider and interactive browser verification remain pending. See [README.md](README.md) for the UI and launcher. See [backend/README.md](backend/README.md) for the implemented contracts and limits.

Purpose: produce a tailored résumé and cover letter from reviewed source facts and a confirmed job. User review, editing, and downloading the outputs belong to workflow 4.

## User and backend journey

| Step | User experience | Backend work |
| --- | --- | --- |
| 1. Start | Opens a saved job and clicks Generate documents, optionally supplying tailoring instructions. | Checks for an active, ready base résumé and a ready job with company, title, and full JD. Shows missing prerequisites before starting. |
| 2. Freeze inputs | Sees generation begin. | Creates a `preparation_runs` record referencing the job and résumé version. Saves a frozen snapshot of the reviewed résumé, confirmed job details, and instructions actually used. |
| 3. Draft | Sees that drafting is in progress. | Sends those inputs and controlled drafting instructions to the selected AI provider. Requests structured résumé and cover-letter content rather than arbitrary LaTeX. |
| 4. Validate | Sees that drafts are being checked. | Validates response structure and required fields. Checks factual consistency against the source, records unsupported or ambiguous claims as findings, and does not treat model output as approved facts. |
| 5. Render | Sees PDF preparation progress. | Saves valid document content, inserts it into controlled templates, and generates both PDFs. The résumé uses the approved fixed template; the letter template remains to be decided. Checks compilation, extracted text, and layout/overflow. |
| 6. Finish | Sees each document's readiness and any review findings. | Saves PDF locations and hashes for successful documents, updates run status, and makes available content accessible in the next review workflow. |

## Inputs and factual boundaries

- Use reviewed résumé content, not an unreviewed re-extraction of the original upload.
- Use confirmed job fields and the full JD captured in `jd_text`; generation does not depend on fetching the URL again.
- Record any user instructions with the frozen run inputs.
- Job descriptions are source material, not instructions that override Jab's factual rules.
- Do not invent employment, skills, qualifications, dates, or metrics to match the JD. Missing evidence should be flagged for user resolution.
- Validation can identify problems but cannot guarantee factual correctness. Generated documents remain drafts until the user reviews them.
- Exact permission to rewrite, reorder, shorten, or omit source content remains to be finalised.

## Stored results

Use the entities already proposed in [DATABASE.md](DATABASE.md):

- `preparation_runs`: job and résumé references, frozen inputs, provider/model, prompt/template versions, run status, timestamps, findings, and errors.
- `document_versions`: separate résumé and cover-letter records, each with validated `content_json`, revision, rendering status, and successful PDF path/hash.

Preserve the raw AI response and request metadata separately from validated content and user edits, excluding secrets. The implemented `ai_calls` table stores these artifacts and links them to the preparation run. No application is created during generation.

## Failures and retries

- A run moves from `queued` to `running`, then `succeeded`, `partial`, or `failed`. Unfinished runs become `interrupted` after restart.
- If only one document succeeds, preserve it, mark the run `partial`, and show the failure for the other document.
- Preserve valid structured content if PDF rendering fails. Retrying rendering of unchanged content may update that revision's render metadata; changing content creates a new revision.
- Invalid structure or unresolved blocking factual/rendering issues must not produce a ready PDF. Retain available response artifacts and explain what needs attention.
- A new AI generation attempt creates a new run and preserves earlier results. Automatic repair-attempt limits remain undecided.
- Never keep a database transaction open during AI requests or PDF compilation.

## Handoff to workflow 4

The user opens the generated drafts, reads findings, makes edits or requests changes, and chooses final PDFs to download. Finishing generation does not mark the job as applied.

## Acceptance checks

1. Generate both documents using the saved reviewed résumé and confirmed JD without reuploading or refetching either.
2. Confirm the run retains its exact inputs after later résumé or job edits.
3. Retain the successful document when its companion fails.
4. Preserve structured content after a rendering failure and allow a rendering retry.
5. Flag unsupported claims and prevent unresolved blocking outputs from being marked ready.
6. Preserve previous runs when regenerating and identify interrupted work after restart.
