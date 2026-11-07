# Workflow 4: Review and download

Status: backend workflow implemented and covered by HTTP integration tests with mocked AI where applicable. Real PDF rendering is exercised. The React frontend is implemented; live-provider and interactive browser verification remain pending. See [README.md](README.md) for the UI and launcher. See [backend/README.md](backend/README.md) for the implemented contracts and limits.

Purpose: let the user inspect generated résumé and cover-letter drafts, resolve findings, make changes, and download the PDFs they intend to submit.

## User and backend journey

| Step | User experience | Backend work |
| --- | --- | --- |
| 1. Open results | Opens a generated résumé or cover letter, with PDF preview, editable content, and any review findings. | Loads the job’s independent résumé and cover-letter selections, each document’s complete history, rendering status, and findings. Shows available content even if its companion document failed. |
| 2. Review | Reads the actual wording and checks accuracy, relevance, and presentation. | Keeps the reviewed source inputs and prior revisions available for comparison. AI findings assist the user; they do not constitute user approval. |
| 3. Make changes | Edits structured content directly, or requests an AI revision with instructions. | Direct edits remain an unsaved draft until saved. A saved edit creates a new document revision under the same run. An AI revision creates a new preparation run with frozen inputs, revision instructions, and the prior content actually supplied. Its input snapshot identifies the originating document revision. |
| 4. Prepare updated PDF | Saves edits and sees rendering progress. | Validates changed content, renders a new PDF using the fixed template, and checks the output. Rechecks AI revisions through the generation workflow. Does not overwrite older ready files. |
| 5. Download | Selects a ready revision and downloads its PDF. | Serves that exact saved file. Unsaved edits are clearly identified; downloading an earlier revision never implies those edits were included. |

If no edits are needed, the user can review and download the existing ready PDF directly. Direct edits change generated documents only; they do not update the base résumé's `reviewed_content_json`.

## Database responsibilities

- `document_versions` holds saved structured content, revision numbers, rendering state, and PDF references. Content changes create a new row; rendering retries for unchanged content can update render metadata.
- `preparation_runs` retains generation provenance and validation findings. AI revision requests create new runs; their snapshots must include the previous content and originating document identity, as well as the reviewed résumé and job information used.
- Findings displayed alongside a revision must correspond to that content. Do not display an earlier revision's checks as current. The implemented `document_validations` table stores append-only findings for each exact revision and gates PDF readiness.
- No new approval table or approval status is proposed at this point. A render-ready PDF describes technical readiness, not proof that the user has approved its facts.
- Saving, reviewing, or downloading does not create an `applications` record. The user records an actual submission in workflow 5 and selects the exact document revisions used.

## Failure and revision behavior

- Preserve earlier ready revisions when saving or rendering a new edit fails.
- Retain valid saved content after rendering failure and offer retry.
- Show validation findings against the relevant content; unresolved blocking issues prevent that revision from becoming ready to download.
- Preserve the successful document when the other document fails. A partial run does not prevent access to its ready outputs.
- Keep previous revisions accessible so the user can choose an earlier ready PDF.

## Acceptance checks

1. Review and download existing ready documents without editing.
2. Edit a document, save a new revision, and verify the downloaded PDF reflects the saved edits.
3. Confirm edits do not change the base résumé, previous PDFs, or submitted document references.
4. Recover from failed rendering without losing saved content or earlier ready PDFs.
5. Request an AI revision and retain its input content, instructions, provenance, and previous results.
6. Clearly distinguish unsaved edits, saved content awaiting rendering, and the exact ready revision being downloaded.

The current independent workspace contract is documented in [DOCUMENT-WORKSPACE.md](DOCUMENT-WORKSPACE.md). Generation attempts retain provenance; they do not control the visible document pair.
