# Prompt provenance and boundaries

All prompts are Jab adaptations, version `jab-prompts-13`; source files remain unchanged in `resume-tailoring/`.
Shared instructions are assembled with the operation prompt, Pydantic JSON schema and explicit JSON inputs,
except job extraction, which uses a dedicated prompt without candidate-writing style instructions.
Exact assembled messages and version are stored with each call. Content contracts live in `schemas.py`.

| Prompt | Reference | Adaptation |
| --- | --- | --- |
| organise_resume | `.claude/commands/setup.md`, single CV import | JSON sections, exact wording, complete source coverage; no conversational onboarding or filesystem access |
| extract_job | `apply.md` intake, posting-fetcher, `04-job-evaluation.md` | One-call HTML cleanup, complete description, fields, requirements and informational evidence; no scores, salary inference, eligibility gates or research cache |
| tailor_resume | `05-cv-templates.md` section tailoring/relevance cutting | One-page Inter, structured content, source IDs; excludes moderncv/two-page/LaTeX instructions |
| write_cover_letter | `06-cover-letter-templates.md`, `03-writing-style.md`, `cover.md` transcript | Meaningful company connection, research required in the prompt for new letters and substantive rewrites through supplied tools, 250-350 words, 3-4 paragraphs; fixed template |
| review_document | `apply.md` Step 3, application-reviewer | Field-based findings and grounded suggestions; no agents, file edits or independent research |
| revise_document | `apply.md` Step 4 | Explicit user requests, immutable revisions; no silent application of all reviewer suggestions |
| repair_response | New for Jab | One schema repair for other operations; job extraction never auto-repairs |

Retained: factual grounding, honest domain transfer, interview-backtrack test, concrete writing, meaningful
keywords, verifiable links, relevance-weighted cuts, degree completion status, untrusted-posting boundary.
Excluded: old candidate/behavioral facts, hardcoded contacts, unrestricted tools, automatic tracker writes,
agent-specific APIs, multi-template registration, two-page requirements, company research outside cover-letter writing/revisions.
Candidate facts always come from the user-reviewed resume. The backend, not the model, fetches, validates,
compiles, writes files, advances states and records submissions. Generated documents go directly to PDF creation for human review.

Adapted reference material is MIT licensed; attribution and license are preserved in `REFERENCE-LICENSE`.

Version 2 teaches semantic review to respect explicitly approved base résumé link warnings. Matching malformed source values print as escaped plain text; new invalid links and other factual errors still block publication.

Version 3 uses content schema 2 and explicit hyperlink evidence, source IDs, labels and code-point spans throughout organisation, rewriting, revision and review.

Version 4 integrates the expanded evidence-based tailoring prompt with actual JSON inputs, item-level skill references and existing group IDs. Resume AI revisions receive the same tailoring guidance before the revision-specific scope/output instructions; cover letter revisions remain separate. Review explicitly checks retention of the highest qualification when identifiable from the approved baseline. Python still checks only that an original education entry remains; no new degree-ranking heuristic or automatic render/rewrite loop is introduced.

Version 5 aligns the expanded cover-letter prompt with actual inputs, the LetterDraft content wrapper, paragraph claims, source references, preserved hyperlinks and the enforced 250–350-word budget. Cover letter AI revisions receive the same writing guidance before the revision-specific scope/output instructions. No database or schema changes.

Version 6 supplies the local current_date for letter drafting and AI revisions. The model returns letter_date, which is saved with the document and rendered. Historical undated documents remain supported.

Version 7 tightened literal job evidence excerpts for the previous parser-based import path.

Version 8 sends rendered HTML directly to job extraction. A single response supplies the full cleaned
description and structured fields. Job extraction omits candidate-writing style rules, local metadata
overrides, evidence matching, and automatic repair. Pasted descriptions remain exactly as entered.

Version 9 requires verbatim source wording for every extracted job value and requirement, including
deadlines. Only markup removal, HTML entity decoding, and layout whitespace/bullet cleanup are allowed.
No paraphrasing, translation, grammar correction, location assembly, salary conversion, date
normalization, or rewriting of qualifications is permitted. Findings can explain ambiguities in the
model's own words; evidence remains quoted. The supplied job URL is preserved by the backend.

Version 10 removes mandatory claim citations and automated factual approval from document writing and revisions. Users review rendered PDFs; factual-preservation instructions and technical rendering checks remain.

Version 11 adds connection-led cover-letter writing and optional company research in the same model
conversation. The backend exposes only search_web and read_page, validates requests, enforces time and
request limits, and records observations in AI history. Revisions can reuse previously captured pages.
External sources establish company context only. Missing tools or failed research fall back to supplied
evidence. Tool-bearing history entries store assistant_message, tool_results, and research metadata;
final entries store the validated document and optional _research audit metadata, which is not part of
the document output contract. The letter still uses three or four paragraphs and 250-350 body words.


Version 12 requires research in the cover-letter instructions for new letters and substantive rewrites,
including broad retries and stronger openings/company connections. Small wording edits may reuse
inspected sources. Research seeks a specific employer concern or ambition connected to reviewed
candidate experience; openings and internal quality checks develop that connection without invented
feelings, motivation or personal experience. Tool failures and runtime limits retain the existing
grounded fallback. This is a prompt requirement: backend tool choice remains automatic and does not
enforce a minimum number of searches or page reads. Document schemas and saved history are unchanged.

Version 13 requires fresh search and page inspection for every AI cover-letter revision, including small edits. The backend forces the missing tool until both steps succeed, rejects premature final answers, and records observed completion rather than asserting sufficient evidence. Existing failure, configuration, and budget fallbacks remain explicit.
