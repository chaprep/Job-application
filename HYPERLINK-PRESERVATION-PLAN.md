# Hyperlink preservation update

Status: implemented. Local contract, workflow, and PDF checks cover the update. Live-provider and interactive browser verification remain pending because this environment blocks network connections, loopback listening, and Chrome launch.

## 1. Goal

Preserve a résumé hyperlink’s visible wording and actual destination from PDF/DOCX upload through review, AI tailoring, manual revisions, and generated PDFs. Valid links should remain blue and clickable in the fixed Inter template, including links attached to a company name or a phrase inside a sentence.

For example, **CNEX** should remain the linked text pointing to `https://studio.example`. It should not become an unlinked name, an invented URL, or a duplicate URL appended to the heading.

The supplied `../Test Candidate AI GTM Engineer Resume.pdf` is the main acceptance fixture. Inspection identified seven destinations: email, LinkedIn, personal website, CNEX, Zebotech, Turtlecare, and GitHub.

## 2. Scope

- Capture embedded PDF hyperlink annotations and DOCX hyperlink relationships alongside visible text.
- Preserve display labels, destinations, text placement, and source provenance.
- Support contact links, linked entry/organisation titles, and links inside summaries, descriptions, bullets, skills, and cover-letter paragraphs.
- Let the user inspect and edit links in the existing structured editor.
- Keep retained links correctly associated with their subjects after AI rewriting.
- Recover links from an existing saved original through a new reviewed draft.
- Retain the existing explicit override for invalid links: approved invalid values print as plain text.

Outside this update: OCR, arbitrary rich-text formatting, custom link colours, visiting links to check availability, job-page scraping changes, template changes, and automatic URL guessing.

“Preserved” means wording, target, and attachment to the relevant text. Text may move naturally when tailoring changes content or pagination; original PDF coordinates are not used to position generated content.

## 3. Data contract and database

Use a version 2 content contract in the existing JSON columns. **No new SQL table or column is planned.** Existing JSON validity constraints allow a new content shape. The earlier link-override migration remains in place.

Recommended representation:

| Content | Version 2 representation |
| --- | --- |
| Inline linked text | A span with `start`, `end`, `url`, and `source_link_id`, attached to its owning text field. |
| Claim text | `Claim.links`, including summary statements, skill items, bullets, descriptions, and letter paragraphs. |
| Entry heading | `Entry.title_links` and `Entry.organization_links`; retain the legacy standalone `Entry.link` field for existing explicit URL entries. |
| Contact links | Labelled records containing `id`, `label`, `url`, and optional `source_link_id`, replacing the version 1 string list in the normalized representation. |
| Parser evidence | Stable source link IDs, original labels/targets, source block references, and page/rectangle or DOCX part information in the extraction input recorded by the existing AI-call request history. |

Span offsets use **Unicode code points**, with an inclusive start and exclusive end. Python slices and frontend conversion helpers must follow this convention explicitly; JavaScript UTF-16 string offsets must not be used directly. The visible text slice is the label, avoiding a second inconsistent copy of that label on inline spans.

Keep reviewed content in `resume_versions.reviewed_content_json`, drafts in `document_versions.content_json`, and frozen baselines in `preparation_runs.source_snapshot_json`. Continue preserving original files and captured text.

Build one version 1 → version 2 adapter used at API/service boundaries. Missing span lists become empty. Existing contact URL strings become labelled records using the same URL as their label. Existing standalone entry URLs retain their existing meaning. Original immutable JSON, AI-call history, and ready PDFs are not rewritten. New approvals/revisions use version 2.

Audit every direct JSON reader, not just Pydantic parsing: repository snapshots, comparison/grounding checks, renderer entry points, downloads, and frontend detail/list responses all need consistent handling. Old preparation runs must still support manual revisions and document review without changing their frozen source records.

## 4. Extraction

### PDF

Keep the current bounded text extraction and Poppler tools. Add annotation reading through a pinned, tested PDF parser; prefer making the existing optional `pypdf` path a supported required dependency rather than adding multiple PDF libraries.

Read URI annotations and their rectangles, then associate them with visible text using word positions from Poppler TSV output. Convert coordinate systems consistently, including page rotation/crop offsets. Confirm compatibility on the supplied résumé before committing to that parser combination.

Associate annotations by geometry and reading order, not by searching globally for a label. Repeated names, repeated URLs, and wrapped linked text must map to the correct occurrence. Merge rectangles only when they belong to the same contiguous linked phrase. A unique extracted link occurrence gets a stable source ID within that capture.

If a target is known but its text association is ambiguous, preserve it as an unresolved finding for user review. Do not attach it to an arbitrary company or sentence. Preserve visible bare URLs, but do not infer a destination from a company name. Continue rejecting encrypted/unreadable input and respecting size/page/time limits.

### DOCX

Resolve hyperlink relationship IDs against the owning XML part’s relationship file, including the main document, tables, headers, and footers. Preserve linked display text in paragraph order, including links split across text runs. Handle supported field-code hyperlink forms or surface them as unresolved; do not silently claim support while dropping their destinations.

Use one authoritative hyperlink-aware extraction path, or prove equivalent behaviour for every supported parser path. Keep expanded-ZIP limits and XML protections. Do not fetch relationship targets or write archive paths to disk.

### Organisation

Supply text blocks plus link evidence to the organisation prompt. The model may classify text, but only deterministic validation can accept the resulting link association. Verify that the link’s label, destination, and source reference match captured evidence. Hidden URL destinations do not need to appear in the PDF’s visible extracted text; update `source_coverage` accordingly without weakening visible-text coverage checks.

## 5. AI tailoring and validation

Update organisation, tailoring, cover-letter, revision, review, and repair contracts/prompts together; increment the prompt version.

- Preserve source destinations exactly. Never construct or “repair” a URL from a label.
- Preserve source link identity when its subject remains in the output.
- Recompute spans against the rewritten text. Source offsets cannot be copied into a changed sentence.
- Link a relevant phrase referring to the same source subject; do not attach an employer link to a different employer or project.
- Omitted source content can omit its associated links. Retained content must not silently drop required link metadata.
- Contact labels and destinations remain consistent between the reviewed base and generated documents.
- New links explicitly entered by the user become part of an approved base version. Model output may use supported reviewed destinations, not invent additional destinations.

Code validates span bounds, nonempty labels, source evidence, destination equality, allowed protocols, and nonoverlap. Use the existing semantic review to flag subject/phrase mismatches that simple source checks cannot establish. Keep exact source IDs and genuine URLs as metadata; do not include metadata IDs in printed documents.

Update protected-field grounding deliberately: names/titles/dates remain protected; contact-link comparisons and source text traversal must understand the new objects instead of accidentally treating URL metadata as candidate claims.

Version 1 override approvals must remain meaningful after normalization. Only unchanged approved malformed values become warnings and plain text. New or altered invalid targets still require correction or explicit approval on a new base version. Overrides never permit active unsafe URI schemes in PDFs or browser previews.

## 6. Editor behaviour

Extend the existing editor rather than adding a separate rich-text editor framework.

- Show a small link list under each applicable text field: linked phrase and destination.
- Let the user select text and add/edit/remove its link; convert browser selection offsets to code-point spans.
- Show a labelled contact-link editor and controls for links on company/entry headings.
- Display ambiguous imported associations for manual placement before approval.
- If text editing invalidates a span, keep the target as an unresolved annotation and ask the user to reattach or remove it. Never silently move a link to another occurrence or drop its destination.
- Preserve form inputs on request errors and apply the existing unsaved-edit navigation guard to link changes.

The saved PDF remains the preview of record. Editing does not imply that the preview has regenerated; saving creates a new checked revision as it does today.

## 7. PDF rendering

Render validated inline spans with the existing blue hyperlink style. Retain linked labels in their original semantic place instead of appending duplicate raw URLs.

Replace the claim formatter with one deterministic text-segmentation routine that handles both link spans and the existing bold emphasis. Define stable output for a bold phrase inside a hyperlink, a hyperlink inside bold text, and adjacent spans. Reject overlapping hyperlinks. Apply the same routine to supported entry heading text.

Escape all display text and destinations through controlled rendering code. Invalid targets accepted through an override render as escaped ordinary text, with no active hyperlink annotation. Preserve the fixed Inter typography, margins, one-page A4 rules, and existing layout/text checks.

Extend PDF verification beyond text extraction: compare generated link annotations with the expected labels/targets and check that invalid targets have no clickable annotations. Inspect the blue linked text visually and exercise long labels, wrapped text, and special characters.

## 8. Recover existing résumé links

Add **Re-import original with links** to the base résumé page once extraction support is ready.

Create a new child résumé version referencing the same original file/hash, then run the existing extraction task against that new version. Existing retry-extraction only accepts failed/unprocessed sources, so it must not be repurposed to mutate an approved version.

Keep the current active résumé in use while the new draft is processing. Show the imported links for review and make the prior reviewed content available for comparison, because re-importing the original cannot automatically recover manual edits made later inside Jab. Require explicit activation of the new version. Existing runs, submitted document references, and ready PDFs remain unchanged.

The action returns the usual task/resource IDs and supports progress/failure recovery. Repeated clicks cannot create concurrent imports of the same source. A fresh upload also benefits from the new extractor without requiring this action.

## 9. Implementation order

1. **Contracts and compatibility:** version 2 schemas, shared adapters, span utilities, source traversal, and backward-compatibility tests. Do not switch production writes until all consumers can read version 2.
2. **Extraction:** recover the supplied PDF’s seven destinations and labels, add DOCX fixtures, and expose ambiguous associations with evidence.
3. **Validation, prompts, and renderer:** enforce source-backed targets, handle link/bold segmentation, produce real blue clickable PDFs, and verify annotations/layout. Include old override and old-run regression cases.
4. **Editor and re-import:** wire link controls, invalidated-span recovery, review findings, and a new draft/version task for existing originals.
5. **End-to-end verification and release:** complete the journeys below, document any parser limits, rebuild the frontend, and restart Jab. The user then reviews and activates the recovered résumé.

## 10. Acceptance checks

- Recover all seven destinations from the supplied résumé and attach each to the correct visible label; do not assume that seven recovered URLs alone proves correct placement.
- Render CNEX, Zebotech, Turtlecare, LinkedIn, website, email, and GitHub with the intended blue clickable labels when their content is retained, without duplicate appended URLs.
- Preserve links inside a sentence across manual edits and a grounded AI revision; verify the actual destinations in the resulting PDFs.
- Exercise repeated labels, wrapped links, punctuation, accents, emoji/non-BMP characters, bold/link overlap, malformed targets, and unsupported annotation types.
- Test DOCX relationships in paragraphs, tables, headers, and footers; report unsupported field-code cases explicitly.
- Retain known targets for ambiguous imports/text edits so the user can resolve them rather than losing them.
- Read/revise version 1 records and old frozen runs; download historical PDFs unchanged.
- Preserve the explicit invalid-link override through version adaptation and generation. An altered invalid target is not covered by an earlier approval.
- Re-import without modifying the active résumé or existing submitted documents; keep the previous version active if extraction fails.
- Pass backend/contract tests, real PDF checks, the frontend production build, and frontend interaction tests. Run desktop/mobile and keyboard checks in a real browser; if the execution sandbox still prevents this, record that limit instead of claiming visual verification.
- With the configured provider, run one reviewed real-job trial and inspect wording, retained links, model usage, and final PDFs. Do not automatically regenerate all historical applications.

## Completion condition

After reviewing a hyperlink-aware import of the supplied résumé, the user can prepare, edit, and download a tailored résumé whose retained linked labels have the right destinations and blue styling. Existing records still work, and ambiguous or overridden links remain visible and under user control.

## Implementation notes

- The installed Poppler `pdftohtml -xml` path recovers the supplied PDF’s URI destinations and visible labels directly. This tested path replaced the proposed additional `pypdf` dependency and separate coordinate-system join. Poppler (`pdfinfo`, `pdftotext`, `pdftohtml`) and bounded standard-library DOCX XML parsing are now the authoritative intake paths. No Python dependency or SQL migration was added for this update.
- Version 2 adds `Claim.links`, entry heading spans, labelled contact records, unresolved-link records, and `Entry.link_label`/`link_source_id` for separately displayed heading links. Version 1 JSON is adapted on read without rewriting immutable history.
- Source evidence remains in the original file and the organisation AI call’s parser-block input. Link approval continues using migration 004’s existing metadata.
- New source IDs for manually added spans are frozen on approval. Schema/structure checks reject overlapping or unresolved spans and conflicting source destinations.
- Re-import creates a child draft sharing the verified original file. The UI exposes the prior reviewed version for comparison; activation remains explicit.
- Actual PDF annotation destinations and blue text fragments were verified on a seven-link rendered sample, and its raster was inspected. Poppler can split one annotation into several text fragments, including adjacent punctuation; checks distinguish these fragments from actual annotation counts. Ambiguous imports remain visible for review.
- The live provider connectivity probe failed with `ConnectError` and included no résumé/JD data. A real model-quality trial and desktop/mobile browser interaction checks are still required outside the sandbox.
