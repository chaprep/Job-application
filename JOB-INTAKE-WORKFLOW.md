# Workflow 2: Job intake

Status: backend workflow implemented and covered by HTTP integration tests with mocked AI where applicable. Real PDF rendering is exercised. The React frontend is implemented; live-provider and interactive browser verification remain pending. See [README.md](README.md) for the UI and launcher. See [backend/README.md](backend/README.md) for the implemented contracts and limits.

Purpose: turn a job URL or pasted job description into a saved, reviewed job ready for document generation.

## User and backend journey

| Step | User experience | Backend work |
| --- | --- | --- |
| 1. Add job | Opens Jobs and chooses Add job. | Opens a new intake form. |
| 2. Supply source | Enters a job URL or pastes the full JD. | Creates a draft job. For a URL, fetches the public page and extracts the JD text; for pasted text, preserves the supplied content. |
| 3. Extract details | Sees processing progress. | Uses AI to identify company, job title, location/work arrangement, and other available job details. Leaves absent information empty and preserves the full JD. |
| 4. Review and edit | Sees an editing panel containing the extracted fields and full JD; corrects or fills gaps. | Saves corrections separately from the original intake and AI extraction result. |
| 5. Save job | Clicks Save job after checking the information. | Requires company, job title, and full JD; marks the job `ready` and saves it in Jobs. |
| 6. Continue | Opens the saved job and starts document generation when ready. | Passes confirmed job information and the active reviewed base résumé into a new preparation run. Generation is the next workflow. |

## Editing panel

Required before the job becomes ready:

- Company.
- Job title.
- Full job description, editable without automatic shortening.

Optional fields:

- Source URL, populated when supplied.
- Location/work arrangement, when known.
- Expected salary: the user's desired compensation, including currency and pay period; AI must not infer this from the employer's advertised range.
- Additional tailoring instructions from the user.

Capture employer-advertised salary, employment type, application deadline, recruiter details, and job reference number when present. These remain optional; the user should not have to research missing fields to proceed. Exact field structure remains to be finalised.

## Saved information

Keep three distinguishable layers:

1. Original source: supplied URL, pasted text or fetched JD text, and capture time.
2. Extraction result: original AI response, validated extracted fields, and provider/model metadata.
3. User-confirmed job: editable business fields and full JD used for generation.

Confirmed source mapping: URL intake saves the supplied URL in `source_url` and the extracted full description in `jd_text`. Pasted intake saves the description in `jd_text` and leaves `source_url` null unless the user separately supplies a URL. URL intake with pasted fallback retains the supplied URL.

The existing `jobs` table covers the core confirmed fields with status `needs_review`, `ready`, or `archived`. Separate source/extraction histories (`intake_captures`, `ai_calls`) and the optional fields are implemented in [DATABASE.md](DATABASE.md). User tailoring instructions must also be included in each generation run's frozen inputs.

Editing a job does not rewrite inputs or documents belonging to previous runs. Merely saving a job does not generate documents or record an application.

## Fallbacks and returning

- If a URL is blocked, expired, login-only, or cannot be extracted, retain the URL and offer a pasted-JD field. The user can manually fill company and title.
- If AI extraction fails, preserve the source, allow manual completion, and offer retry. AI success is not required to save an otherwise complete job.
- Missing required fields leave the job in `needs_review` and identify what is needed.
- Returning to a saved draft restores its saved fields. Saving edits must be explicit; autosave behavior is not yet decided.
- Warn about a likely duplicate without preventing a legitimate new entry.
- A job can be saved before the base résumé is ready; generation requires an active reviewed résumé.

## Acceptance checks

1. Add and review a job through either URL or pasted text.
2. Recover from a blocked URL using pasted text while retaining the source URL.
3. Manually complete a job after extraction fails.
4. Prevent ready status when company, title, or full JD is missing.
5. Reopen a saved job without repeating intake and preserve earlier generation snapshots after job edits.
