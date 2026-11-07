# Independent document workspace

Each job has one document workspace. Résumés and cover letters have separate version histories and separate saved selections. A generation attempt records work performed; it does not determine which documents are visible together.

## Selection and history

- Each tab lists all saved versions of that document for this job, across AI generations and manual edits. Version numbers increase independently for each document type. Existing per-run revision numbers remain intact as historical metadata.
- Selecting résumé v1 and cover letter v5 persists those exact document IDs. Switching tabs, changing the activity-history view, refreshing, or restarting does not reset the other selection.
- Each preview, editor, and download uses the selected document ID. Unsaved edits are protected when changing versions or tabs. A background completion cannot discard edits to the version being viewed.
- A successful new PDF selects that version for its document type only. Failed AI generation/rendering leaves existing selections available; failed saved drafts remain in that document’s history for editing or PDF retry.
- A manual save creates a new version with the version being edited as its parent. An AI rewrite does the same in a new generation attempt. Rewriting an older version uses that exact version, even when newer versions exist.
- AI rewrite inputs freeze the selected companion document and its ID when the attempt starts. Companion text supplies consistency context; reviewed base résumé facts remain authoritative. The existing current-base-résumé and confirmed-job input behavior is unchanged.

## Submission

The submission form starts with the workspace’s saved résumé and cover-letter selections. It displays their independent version numbers and requires explicit confirmation that these are the documents submitted externally. Users may change those choices or omit a cover letter. Only saved, PDF-ready documents from the same job can be recorded. Later workspace selections and rewrites do not alter submitted document IDs.

## API and persistence

- `GET /jobs/{id}/documents?kind=resume` or `kind=cover_letter` returns that document’s paginated history and job-wide `version_number`. Status filtering preserves the original version numbers.
- `GET /jobs/{id}/document-selections` returns the independently selected documents.
- `POST /jobs/{id}/document-selections` with `document_id` changes only that document type’s selection. Documents from another job are rejected.
- Existing document-specific revision and PDF endpoints retain exact-version behavior.
- Preparation history remains available as “Generation activity.” Selecting an attempt does not change document selections.

Migration 007 adds `job_document_selections`. Existing jobs start with their newest ready résumé and newest ready cover letter independently. It does not rewrite document content, PDF files, parent relationships, earlier preparation snapshots, or submitted applications. The migration runs at backend startup; restart Jab after upgrading.
