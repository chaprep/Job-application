import type { Content, ContactLink, Entry, LinkSpan } from "./types";

export const cpSlice = (text: string, start: number, end?: number) =>
  Array.from(text).slice(start, end).join("");
export const cpOffset = (text: string, utf16Offset: number) =>
  Array.from(text.slice(0, utf16Offset)).length;
export const validSpan = (text: string, span: LinkSpan) =>
  span.start !== null &&
  span.end !== null &&
  span.start >= 0 &&
  span.end > span.start &&
  span.end <= Array.from(text).length &&
  !span.unresolved_label;

export function remapLinks(
  old: string,
  next: string,
  links: LinkSpan[],
): LinkSpan[] {
  const a = Array.from(old),
    b = Array.from(next);
  let prefix = 0,
    suffix = 0;
  while (prefix < Math.min(a.length, b.length) && a[prefix] === b[prefix])
    prefix++;
  while (
    suffix < Math.min(a.length, b.length) - prefix &&
    a[a.length - suffix - 1] === b[b.length - suffix - 1]
  )
    suffix++;
  return links.map((link) => {
    if (!validSpan(old, link)) return link;
    const start = link.start!,
      end = link.end!;
    if (end <= prefix) return link;
    if (start >= a.length - suffix)
      return {
        ...link,
        start: start + b.length - a.length,
        end: end + b.length - a.length,
      };
    return {
      ...link,
      start: null,
      end: null,
      unresolved_label: cpSlice(old, start, end),
    };
  });
}

export function sourceLinks(content?: Content): ContactLink[] {
  if (!content) return [];
  const links = [...content.contact.links, ...(content.unresolved_links || [])];
  const spans = (text: string, values: LinkSpan[] = []) =>
    values.forEach((span) => {
      if (span.source_link_id)
        links.push({
          id: span.source_link_id,
          source_link_id: span.source_link_id,
          label: validSpan(text, span)
            ? cpSlice(text, span.start!, span.end!)
            : span.unresolved_label || "Unresolved link",
          url: span.url,
        });
    });
  const entries = (values: Entry[]) =>
    values.forEach((entry) => {
      spans(entry.title, entry.title_links);
      spans(entry.organization, entry.organization_links);
      if (entry.link)
        links.push({
          id: entry.link_source_id || `legacy_entry_${entry.id}`.slice(0, 64),
          source_link_id:
            entry.link_source_id || `legacy_entry_${entry.id}`.slice(0, 64),
          label: entry.link_label || entry.link,
          url: entry.link,
        });
      [...entry.description, ...entry.bullets].forEach((claim) =>
        spans(claim.text, claim.links),
      );
      entries(entry.children);
    });
  if ("paragraphs" in content)
    content.paragraphs.forEach((claim) => spans(claim.text, claim.links));
  else {
    [
      ...content.summary,
      ...content.skills.flatMap((group) => group.items),
    ].forEach((claim) => spans(claim.text, claim.links));
    entries([
      ...content.experience,
      ...content.projects,
      ...content.education,
      ...content.additional_sections.flatMap((section) => section.entries),
    ]);
  }
  return [
    ...new Map(
      links.map((link) => [link.source_link_id || link.id, link]),
    ).values(),
  ];
}
