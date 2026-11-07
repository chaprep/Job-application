# Workflow 5: Application tracking

Status: backend workflow implemented and covered by HTTP integration tests with mocked AI where applicable. Real PDF rendering is exercised. The React frontend is implemented; live-provider and interactive browser verification remain pending. See [README.md](README.md) for the UI and launcher. See [backend/README.md](backend/README.md) for the implemented contracts and limits.

Purpose: record actual job submissions and track their progress, retaining the exact documents used.

## User and backend journey

| Step | User experience | Backend work |
| --- | --- | --- |
| 1. Apply externally | Submits the application on the employer website or through another channel. | Does not infer submission from generating or downloading documents. |
| 2. Record submission | Opens the job, clicks Mark as applied, enters the applied date, and selects the exact résumé revision used. Selects a cover letter only if submitted. | Validates the selected documents are ready, correctly typed, and associated with that job. |
| 3. Save application | Sees the submission in Applications. | Creates an `applications` row with company/role snapshots, job reference, date, stage `applied`, and selected document references. Creates its initial `application_events` entry in the same transaction. |
| 4. Track progress | Opens the application, changes its stage, or adds dated notes. | Updates current application fields and appends corresponding timeline events atomically. |
| 5. Plan follow-up | Optionally enters a next action and due date. | Saves the next action and appends a history event. This does not imply scheduled notifications. |
| 6. Return later | Searches or filters applications and opens their history and submitted PDFs. | Loads stored records and exact document versions without needing the original job page to remain available. |

Proposed stages: `applied`, `screening`, `interviewing`, `offer`, `accepted`, `rejected`, `withdrawn`. Stage changes are explicit user actions; AI does not automatically infer hiring progress.

## Applications prepared outside Jab

Provide Add application for submissions made without Jab-generated documents. Require company and role; allow optional job URL, applied date, current stage, notes, and next action. An unknown historical submission date may remain empty. Job and document references may also be empty.

## Database responsibilities

- `applications` stores the current submission record, stage, exact submitted document references, and next action.
- `application_events` stores append-only submission, stage, note, follow-up, and correction history. Distinguish when an event occurred from when it was recorded.
- Later job edits or document revisions do not change the submission snapshots or selected files.
- Correcting an incorrectly recorded date, detail, or submitted-document selection is explicit and adds an event with old/new values. Never rewrite the referenced document content.
- A subsequent real submission to the same job can create a separate application; company and role are not unique identifiers.

## Acceptance checks

1. Record a Jab-prepared submission with its date and exact résumé revision, adding the cover letter only when used.
2. Confirm downloads alone never create applications.
3. Update a stage or next action and verify both current state and history survive restart.
4. Add an external application without generated documents or a known historical submission date.
5. Generate later document revisions and confirm the original submitted versions remain linked and accessible.
6. Correct a recording error while preserving its audit history.
