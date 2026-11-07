import { useId, useRef, useState } from "react";
import { LinkSimple, Plus, Trash } from "@phosphor-icons/react";
import { Button, Field, Select } from "./ui";
import { cpOffset, cpSlice, validSpan } from "./links";
import type { ContactLink, LinkSpan } from "./types";

export function LinkedTextEditor({
  label,
  value,
  links = [],
  onTextChange,
  onLinksChange,
  sources = [],
  multiline = false,
}: {
  label: string;
  value: string;
  links?: LinkSpan[];
  onTextChange: (value: string) => void;
  onLinksChange: (links: LinkSpan[]) => void;
  sources?: ContactLink[];
  multiline?: boolean;
}) {
  const id = useId();
  const field = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const selected =
    selection.start < selection.end &&
    selection.end <= Array.from(value).length;
  const overlap = links.some(
    (link) =>
      validSpan(value, link) &&
      link.start! < selection.end &&
      selection.start < link.end!,
  );
  const update = (index: number, changes: Partial<LinkSpan>) =>
    onLinksChange(
      links.map((link, i) => (i === index ? { ...link, ...changes } : link)),
    );
  const props = {
    id,
    value,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      onTextChange(e.target.value),
    onSelect: () => {
      const node = field.current;
      if (node)
        setSelection({
          start: cpOffset(node.value, node.selectionStart || 0),
          end: cpOffset(node.value, node.selectionEnd || 0),
        });
    },
  };
  return (
    <div className="linked-text-editor">
      <div className="field">
        <label htmlFor={id}>{label}</label>
        {multiline ? (
          <textarea
            {...props}
            ref={(node) => {
              field.current = node;
            }}
            rows={Math.min(7, Math.max(2, Math.ceil(value.length / 85)))}
          />
        ) : (
          <input
            {...props}
            ref={(node) => {
              field.current = node;
            }}
          />
        )}
      </div>
      <div className="link-toolbar">
        <Button
          tone="quiet"
          disabled={!selected || overlap}
          onClick={() =>
            onLinksChange([
              ...links,
              {
                start: selection.start,
                end: selection.end,
                url: "",
                source_link_id: null,
                unresolved_label: null,
              },
            ])
          }
        >
          <LinkSimple />
          Link selected text
        </Button>
        <small>
          {overlap
            ? "Choose text outside an existing hyperlink."
            : "Select a phrase above to attach a destination."}
        </small>
      </div>
      {links.map((link, i) => (
        <div
          className={`inline-link-row ${validSpan(value, link) ? "" : "unresolved"}`}
          key={i}
        >
          <div className="section-row">
            <strong>
              {validSpan(value, link)
                ? cpSlice(value, link.start!, link.end!)
                : link.unresolved_label || "Unresolved selection"}
            </strong>
            <Button
              tone="quiet"
              aria-label={`Remove hyperlink ${i + 1} from ${label}`}
              onClick={() =>
                onLinksChange(links.filter((_, index) => index !== i))
              }
            >
              <Trash />
            </Button>
          </div>
          {!validSpan(value, link) && (
            <small>
              Text changed. Select the correct phrase above and reattach this
              link, or remove it.
            </small>
          )}
          <Field
            label={`${label} link ${i + 1} destination`}
            value={link.url}
            onChange={(e) => update(i, { url: e.target.value })}
          />
          {sources.length > 0 && (
            <Select
              label="Use a source link"
              value={
                sources.some(
                  (source) =>
                    (source.source_link_id || source.id) ===
                    link.source_link_id,
                )
                  ? link.source_link_id || ""
                  : ""
              }
              onChange={(e) => {
                const source = sources.find(
                  (source) =>
                    (source.source_link_id || source.id) === e.target.value,
                );
                if (source)
                  update(i, {
                    url: source.url,
                    source_link_id: source.source_link_id || source.id,
                  });
              }}
            >
              <option value="">Choose a source destination</option>
              {sources.map((source) => (
                <option
                  value={source.source_link_id || source.id}
                  key={source.source_link_id || source.id}
                >
                  {source.label} · {source.url}
                </option>
              ))}
            </Select>
          )}
          <Button
            tone="quiet"
            disabled={
              !selected ||
              links.some(
                (other, index) =>
                  index !== i &&
                  validSpan(value, other) &&
                  other.start! < selection.end &&
                  selection.start < other.end!,
              )
            }
            onClick={() =>
              update(i, {
                start: selection.start,
                end: selection.end,
                unresolved_label: null,
              })
            }
          >
            <Plus />
            Use selected text
          </Button>
        </div>
      ))}
    </div>
  );
}
