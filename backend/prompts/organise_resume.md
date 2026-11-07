Organise the locally extracted resume into content and findings. This is import, not tailoring.
Each parser block can include links with source IDs, exact labels, hidden destination URLs and source
positions. Use those URLs as evidence even when they do not occur in visible text. A company name or
visible domain is a display label, not proof of a destination. Preserve contact labels and actual URLs.
Attach links to title_links/organization_links or Claim.links when embedded in that field. A separately
displayed URL in a heading uses Entry.link (actual URL), link_label (visible wording), and link_source_id.
Never append a URL to text merely to represent a hyperlink. The backend verifies parser evidence and
reconstructs associations; ambiguous links are kept for the user to place explicitly.
Preserve the extracted wording, names, numbers, capitalization, dates and qualifications exactly, apart
from whitespace normalization. Group lines into contact, summary, skills, experience, client work,
projects, education and additional sections. Do not paraphrase, infer dates or fill missing contact data.
Every text block supplied by the parser must be represented. Keep unfamiliar sections, and put material
you cannot classify into an 'Unclassified source content' additional section with a coverage warning.
Use unique stable IDs, preserve genuine public links, and flag ambiguities. Return the OrganisedResume schema.
