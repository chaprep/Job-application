import { ArrowDown, ArrowUp, Plus, Trash } from "@phosphor-icons/react";
import { Button, Field, Textarea } from "./ui";
import type {
  Claim,
  Contact,
  ContactLink,
  Content,
  Entry,
  ResumeContent,
} from "./types";

import { LinkedTextEditor } from "./LinkedTextEditor";
import { remapLinks, sourceLinks } from "./links";

const id = () => "s_" + crypto.randomUUID().replaceAll("-", "");
const newClaim = (): Claim => ({
  id: id(),
  text: "",
  source_refs: [],
  emphasis: [],
});
const newEntry = (): Entry => ({
  id: id(),
  title: "",
  organization: "",
  location: "",
  dates: "",
  link: "",
  description: [],
  bullets: [],
  children: [],
});
export const emptyResume = (): ResumeContent => ({
  schema_version: "2",
  unresolved_links: [],
  contact: { name: "", email: "", phone: "", location: "", links: [] },
  summary: [],
  skills: [],
  experience: [],
  projects: [],
  education: [],
  additional_sections: [],
});

export function sourceClaims(content?: ResumeContent): Claim[] {
  if (!content) return [];
  const claims: Claim[] = [
    ...content.summary,
    ...content.skills.flatMap((s) => s.items),
  ];
  const entries = (list: Entry[]) =>
    list.forEach((e) => {
      claims.push(...e.description, ...e.bullets);
      entries(e.children);
    });
  entries([
    ...content.experience,
    ...content.projects,
    ...content.education,
    ...content.additional_sections.flatMap((s) => s.entries),
  ]);
  return claims;
}

function ItemActions({
  index,
  count,
  onMove,
  onRemove,
  title,
}: {
  index: number;
  count: number;
  onMove: (index: number) => void;
  onRemove: () => void;
  title: string;
}) {
  return (
    <div className="item-actions">
      <Button
        tone="quiet"
        disabled={index === 0}
        onClick={() => onMove(index - 1)}
        aria-label={`Move ${title} up`}
      >
        <ArrowUp />
      </Button>
      <Button
        tone="quiet"
        disabled={index === count - 1}
        onClick={() => onMove(index + 1)}
        aria-label={`Move ${title} down`}
      >
        <ArrowDown />
      </Button>
      <Button tone="quiet" onClick={onRemove} aria-label={`Remove ${title}`}>
        <Trash />
      </Button>
    </div>
  );
}
function moved<T>(items: T[], from: number, to: number) {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function ClaimsEditor({
  title,
  values,
  onChange,
  linkSources = [],
}: {
  title: string;
  values: Claim[];
  onChange: (values: Claim[]) => void;
  sources?: Claim[];
  linkSources?: ContactLink[];
}) {
  function update(index: number, changes: Partial<Claim>) {
    onChange(
      values.map((item, i) => (i === index ? { ...item, ...changes } : item)),
    );
  }
  return (
    <div className="claims-editor">
      <div className="section-row">
        <h3>{title}</h3>
        <Button tone="quiet" onClick={() => onChange([...values, newClaim()])}>
          <Plus />
          Add
        </Button>
      </div>
      {values.map((claim, index) => (
        <div className="claim-editor" key={claim.id}>
          <div className="claim-content">
            <LinkedTextEditor
              label={`${title} ${index + 1}`}
              multiline
              value={claim.text}
              links={claim.links || []}
              sources={linkSources}
              onTextChange={(text) =>
                update(index, {
                  text,
                  links: remapLinks(claim.text, text, claim.links || []),
                  emphasis: claim.emphasis.filter((t) => text.includes(t)),
                })
              }
              onLinksChange={(links) => update(index, { links })}
            />
            <details className="evidence-picker">
              <summary>
                Bold emphasis
                {claim.emphasis.length ? ` · ${claim.emphasis.length}` : ""}
              </summary>
              <Textarea
                label="Exact phrases to bold"
                hint="One phrase per line. Each phrase must appear exactly in the text above."
                rows={2}
                value={claim.emphasis.join("\n")}
                onChange={(e) =>
                  update(index, {
                    emphasis: e.target.value.split("\n"),
                  })
                }
                onBlur={() =>
                  update(index, {
                    emphasis: claim.emphasis
                      .map((t) => t.trim())
                      .filter(Boolean),
                  })
                }
              />
            </details>
          </div>
          <ItemActions
            title={`${title.toLowerCase()} ${index + 1}`}
            index={index}
            count={values.length}
            onMove={(to) => onChange(moved(values, index, to))}
            onRemove={() => onChange(values.filter((_, i) => i !== index))}
          />
        </div>
      ))}
    </div>
  );
}

function ContactEditor({
  value,
  onChange,
}: {
  value: Contact;
  onChange: (v: Contact) => void;
}) {
  return (
    <div className="form-grid">
      {(["name", "email", "phone", "location"] as const).map((key) => (
        <Field
          key={key}
          label={
            {
              name: "Full name",
              email: "Email",
              phone: "Phone",
              location: "Location",
            }[key]
          }
          value={value[key]}
          onChange={(e) => onChange({ ...value, [key]: e.target.value })}
        />
      ))}
      <div className="wide contact-links-editor">
        <h3>Contact links</h3>
        {value.links.map((link, index) => (
          <div className="inline-link-row" key={link.id}>
            <div className="form-grid">
              <Field
                label={`Contact link ${index + 1} label`}
                value={link.label}
                onChange={(e) =>
                  onChange({
                    ...value,
                    links: value.links.map((item, i) =>
                      i === index ? { ...item, label: e.target.value } : item,
                    ),
                  })
                }
              />
              <Field
                label={`Contact link ${index + 1} destination`}
                value={link.url}
                onChange={(e) =>
                  onChange({
                    ...value,
                    links: value.links.map((item, i) =>
                      i === index ? { ...item, url: e.target.value } : item,
                    ),
                  })
                }
              />
            </div>
            <Button
              tone="quiet"
              aria-label={`Remove contact link ${index + 1}`}
              onClick={() =>
                onChange({
                  ...value,
                  links: value.links.filter((_, i) => i !== index),
                })
              }
            >
              <Trash />
              Remove link
            </Button>
          </div>
        ))}
        <Button
          onClick={() =>
            onChange({
              ...value,
              links: [
                ...value.links,
                { id: id(), label: "", url: "", source_link_id: null },
              ],
            })
          }
        >
          <Plus />
          Add contact link
        </Button>
      </div>
    </div>
  );
}

function EntriesEditor({
  values,
  onChange,
  sources,
  noun = "entry",
  linkSources = [],
}: {
  values: Entry[];
  onChange: (v: Entry[]) => void;
  sources: Claim[];
  noun?: string;
  linkSources?: ContactLink[];
}) {
  const update = (i: number, changes: Partial<Entry>) =>
    onChange(
      values.map((entry, n) => (n === i ? { ...entry, ...changes } : entry)),
    );
  return (
    <div className="entries-editor">
      {values.map((entry, index) => (
        <div key={entry.id} className="entry-editor">
          <div className="section-row">
            <h3>{entry.title || entry.organization || `New ${noun}`}</h3>
            <ItemActions
              title={`${noun} ${index + 1}`}
              index={index}
              count={values.length}
              onMove={(to) => onChange(moved(values, index, to))}
              onRemove={() => onChange(values.filter((_, i) => i !== index))}
            />
          </div>
          <div className="form-grid">
            <LinkedTextEditor
              label="Title or qualification"
              value={entry.title}
              links={entry.title_links || []}
              sources={linkSources}
              onTextChange={(title) =>
                update(index, {
                  title,
                  title_links: remapLinks(
                    entry.title,
                    title,
                    entry.title_links || [],
                  ),
                })
              }
              onLinksChange={(title_links) => update(index, { title_links })}
            />
            <LinkedTextEditor
              label="Organisation"
              value={entry.organization}
              links={entry.organization_links || []}
              sources={linkSources}
              onTextChange={(organization) =>
                update(index, {
                  organization,
                  organization_links: remapLinks(
                    entry.organization,
                    organization,
                    entry.organization_links || [],
                  ),
                })
              }
              onLinksChange={(organization_links) =>
                update(index, { organization_links })
              }
            />
            <Field
              label="Dates"
              value={entry.dates}
              onChange={(e) => update(index, { dates: e.target.value })}
            />
            <Field
              label="Location"
              value={entry.location}
              onChange={(e) => update(index, { location: e.target.value })}
            />
            <Field
              wide
              label="Standalone link destination"
              value={entry.link}
              onChange={(e) => update(index, { link: e.target.value })}
            />
            <Field
              wide
              label="Standalone link label"
              value={entry.link_label || ""}
              onChange={(e) => update(index, { link_label: e.target.value })}
              hint="Use a label when the displayed text differs from the destination. Leave both standalone fields empty if the link is attached to a heading above."
            />
          </div>
          <ClaimsEditor
            linkSources={linkSources}
            title="Description"
            values={entry.description}
            sources={sources}
            onChange={(description) => update(index, { description })}
          />
          <ClaimsEditor
            linkSources={linkSources}
            title="Bullet points"
            values={entry.bullets}
            sources={sources}
            onChange={(bullets) => update(index, { bullets })}
          />
          <details className="nested-section" open={entry.children.length > 0}>
            <summary>
              Related roles or subentries ({entry.children.length})
            </summary>
            <EntriesEditor
              linkSources={linkSources}
              values={entry.children}
              sources={sources}
              onChange={(children) => update(index, { children })}
            />
          </details>
        </div>
      ))}
      <Button onClick={() => onChange([...values, newEntry()])}>
        <Plus />
        Add {noun}
      </Button>
    </div>
  );
}

export function ContentEditor({
  value,
  onChange,
  source,
}: {
  value: Content;
  onChange: (v: Content) => void;
  source?: ResumeContent;
}) {
  const sources = sourceClaims(source);
  const linkSources = sourceLinks(source || value);
  const unresolved =
    (value.unresolved_links || []).length > 0 ? (
      <div className="unresolved-imports">
        <h3>Place your imported links</h3>
        <p>
          These destinations could not be matched uniquely. Attach each to the
          appropriate text below, then remove it from this list.
        </p>
        {value.unresolved_links!.map((link) => (
          <div className="inline-link-row unresolved" key={link.id}>
            <strong>{link.label}</strong>
            <p>{link.url || "Destination not available"}</p>
            <small>{link.reason}</small>
            <Button
              onClick={() =>
                onChange({
                  ...value,
                  unresolved_links: value.unresolved_links!.filter(
                    (item) => item.id !== link.id,
                  ),
                })
              }
            >
              Remove from unresolved list
            </Button>
          </div>
        ))}
      </div>
    ) : null;
  if ("paragraphs" in value) {
    return (
      <div className="content-editor">
        {unresolved}
        <details className="editor-section">
          <summary>Contact details</summary>
          <ContactEditor
            value={value.contact}
            onChange={(contact) => onChange({ ...value, contact })}
          />
        </details>
        <div className="editor-pad">
          <Field
            label="Letter date"
            type="date"
            value={value.letter_date ?? ""}
            onChange={(e) => onChange({ ...value, letter_date: e.target.value || null })}
          />
          <Field
            label="Salutation"
            value={value.salutation}
            onChange={(e) => onChange({ ...value, salutation: e.target.value })}
          />
          <ClaimsEditor
            linkSources={linkSources}
            title="Paragraphs"
            sources={sources}
            values={value.paragraphs}
            onChange={(paragraphs) => onChange({ ...value, paragraphs })}
          />
          <div className="word-count">
            {
              value.paragraphs
                .map((p) => p.text)
                .join(" ")
                .trim()
                .split(/\s+/)
                .filter(Boolean).length
            }{" "}
            words · target 250–350 words in 3–4 paragraphs
          </div>
          <div className="form-grid">
            <Field
              label="Closing"
              value={value.closing}
              onChange={(e) => onChange({ ...value, closing: e.target.value })}
            />
            <Field
              label="Signature"
              value={value.signature}
              onChange={(e) =>
                onChange({ ...value, signature: e.target.value })
              }
            />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="content-editor">
      {unresolved}
      <details className="editor-section" open>
        <summary>Contact details</summary>
        <ContactEditor
          value={value.contact}
          onChange={(contact) => onChange({ ...value, contact })}
        />
      </details>
      <details className="editor-section" open>
        <summary>
          Summary <span>{value.summary.length}</span>
        </summary>
        <ClaimsEditor
          linkSources={linkSources}
          title="Summary statements"
          sources={sources}
          values={value.summary}
          onChange={(summary) => onChange({ ...value, summary })}
        />
      </details>
      <details className="editor-section">
        <summary>
          Skills <span>{value.skills.length} groups</span>
        </summary>
        {value.skills.map((group, i) => (
          <div className="entry-editor" key={group.id}>
            <div className="section-row">
              <Field
                label="Group name"
                value={group.label}
                onChange={(e) =>
                  onChange({
                    ...value,
                    skills: value.skills.map((g, n) =>
                      n === i ? { ...g, label: e.target.value } : g,
                    ),
                  })
                }
              />
              <ItemActions
                title={`skill group ${i + 1}`}
                index={i}
                count={value.skills.length}
                onMove={(to) =>
                  onChange({ ...value, skills: moved(value.skills, i, to) })
                }
                onRemove={() =>
                  onChange({
                    ...value,
                    skills: value.skills.filter((_, n) => n !== i),
                  })
                }
              />
            </div>
            <ClaimsEditor
              linkSources={linkSources}
              title="Skills"
              values={group.items}
              sources={sources}
              onChange={(items) =>
                onChange({
                  ...value,
                  skills: value.skills.map((g, n) =>
                    n === i ? { ...g, items } : g,
                  ),
                })
              }
            />
          </div>
        ))}
        <Button
          onClick={() =>
            onChange({
              ...value,
              skills: [...value.skills, { id: id(), label: "", items: [] }],
            })
          }
        >
          <Plus />
          Add skill group
        </Button>
      </details>
      {(["experience", "projects", "education"] as const).map((section) => (
        <details
          className="editor-section"
          key={section}
          open={section === "experience"}
        >
          <summary>
            {
              {
                experience: "Experience",
                projects: "Projects",
                education: "Education",
              }[section]
            }{" "}
            <span>{value[section].length}</span>
          </summary>
          <EntriesEditor
            linkSources={linkSources}
            values={value[section]}
            sources={sources}
            noun={
              section === "experience"
                ? "role"
                : section === "projects"
                  ? "project"
                  : "qualification"
            }
            onChange={(entries) => onChange({ ...value, [section]: entries })}
          />
        </details>
      ))}
      <details className="editor-section">
        <summary>
          Additional sections <span>{value.additional_sections.length}</span>
        </summary>
        {value.additional_sections.map((section, i) => (
          <div className="extra-section" key={i}>
            <div className="section-row">
              <Field
                label="Section title"
                value={section.title}
                onChange={(e) =>
                  onChange({
                    ...value,
                    additional_sections: value.additional_sections.map(
                      (s, n) => (n === i ? { ...s, title: e.target.value } : s),
                    ),
                  })
                }
              />
              <Button
                tone="quiet"
                aria-label={`Remove ${section.title || "section"}`}
                onClick={() =>
                  onChange({
                    ...value,
                    additional_sections: value.additional_sections.filter(
                      (_, n) => n !== i,
                    ),
                  })
                }
              >
                <Trash />
              </Button>
            </div>
            <EntriesEditor
              linkSources={linkSources}
              values={section.entries}
              sources={sources}
              onChange={(entries) =>
                onChange({
                  ...value,
                  additional_sections: value.additional_sections.map((s, n) =>
                    n === i ? { ...s, entries } : s,
                  ),
                })
              }
            />
          </div>
        ))}
        <Button
          onClick={() =>
            onChange({
              ...value,
              additional_sections: [
                ...value.additional_sections,
                { title: "Additional information", entries: [] },
              ],
            })
          }
        >
          <Plus />
          Add section
        </Button>
      </details>
    </div>
  );
}
