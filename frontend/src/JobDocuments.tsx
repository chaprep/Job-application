import { useEffect, useId, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CaretDown,
  DownloadSimple,
  FileText,
  Sparkle,
} from "@phosphor-icons/react";
import { activeTask, dateLabel, label, pdfUrl, post } from "./api";
import { ContentEditor } from "./ContentEditor";
import { useAction, useDirty, useResource, useWorkspace } from "./state";
import {
  Badge,
  Button,
  Empty,
  ErrorMessage,
  Link,
  Loading,
  Notice,
  Pagination,
  TaskStatus,
  Textarea,
} from "./ui";
import type {
  Accepted,
  Content,
  Document,
  DocumentSelections,
  Page,
  Job,
  ResumeContent,
  Run,
} from "./types";

export function DocumentVersionPicker({
  kind, documents, selected, selectedId, disabled, onSelect,
}: {
  kind: "resume" | "cover_letter";
  documents: Document[];
  selected?: Document | null;
  selectedId?: number;
  disabled: boolean;
  onSelect: (id: number) => void;
}) {
  const id = useId();
  const picker = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  const options = selected && !documents.some((doc) => doc.id === selected.id)
    ? [selected, ...documents] : documents;
  const current = options.find((doc) => doc.id === selectedId);
  const close = (focus = false) => {
    if (!picker.current) return;
    picker.current.open = false;
    if (focus) picker.current.querySelector("summary")?.focus();
  };
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const element = picker.current;
      if (element && event.target instanceof Node && !element.contains(event.target))
        element.open = false;
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => {
    if (disabled && picker.current) picker.current.open = false;
  }, [disabled]);
  return (
    <div className="field document-version-picker">
      <span id={`${id}-label`} className="version-picker-label">{label(kind)} version</span>
      <details ref={picker} className="version-dropdown"
        onToggle={(event) => setOpen(event.currentTarget.open)}
        onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); close(true); }
        }}>
        <summary aria-labelledby={`${id}-label ${id}-value`} aria-disabled={disabled}
          onClick={(event) => { if (disabled) event.preventDefault(); }}>
          <span id={`${id}-value`}>
            {current ? `Version ${current.version_number ?? current.revision} · ${dateLabel(current.created_at)} · ${label(current.render_status)}` : "Choose a version"}
          </span>
          <CaretDown aria-hidden="true" />
        </summary>
        <fieldset className="version-options" disabled={disabled}>
          <legend className="sr-only">{label(kind)} version</legend>
          {options.map((doc) => (
            <label key={doc.id} className="version-option">
              <input type="radio" name={id} value={doc.id} checked={doc.id === selectedId}
                onChange={() => { close(true); onSelect(doc.id); }} />
              <span>
                <strong>Version {doc.version_number ?? doc.revision}</strong>
                <small>{dateLabel(doc.created_at)} · {label(doc.render_status)}</small>
              </span>
            </label>
          ))}
        </fieldset>
      </details>
    </div>
  );
}

export function DocumentEditor({
  doc,
  source,
  onSelect,
  onNewRun,
  jobId,
}: {
  doc: Document;
  source?: ResumeContent;
  onSelect: (id: number) => void;
  onNewRun: (id: number) => void;
  jobId: number;
}) {
  const [content, setContent] = useState<Content>(doc.content);
  const [instructions, setInstructions] = useState("");
  const setDirty = useDirty();
  const { dirty } = useWorkspace();
  const action = useAction();
  const working = activeTask(doc.tasks);
  const update = (value: Content) => {
    setContent(value);
    setDirty(true);
  };
  return (
    <>
      <TaskStatus tasks={doc.tasks} />
      {doc.render_error && (
        doc.render_error.includes("structural or factual issues") ||
        doc.render_error.includes("AI review found unsupported") ? (
          <Notice>
            This draft was stopped by earlier review checks. Use Retry PDF creation
            below to render it for your review.
          </Notice>
        ) : <Notice kind="error">{doc.render_error}</Notice>
      )}
      <div className="split-workspace document-workspace">
        <section className="panel editor-panel">
          <div className="panel-bar">
            <div>
              <span className="eyebrow">
                Version {doc.version_number ?? doc.revision}
              </span>
              <h2>{doc.kind === "resume" ? "Edit résumé" : "Edit cover letter"}</h2>
            </div>
            <Badge value={doc.render_status} />
          </div>
          <p className="editor-intro">
            Review the wording and facts before applying.
          </p>
          <fieldset disabled={action.busy || working}>
            <ContentEditor value={content} source={source} onChange={update} />
          </fieldset>
          <div className="editor-footer">
            <ErrorMessage error={action.error} />
            <div className="row">
              <Button
                tone="primary"
                busy={action.busy}
                disabled={!dirty || working}
                onClick={() =>
                  void action.run(async () => {
                    const result = await post<Accepted>(
                      `/documents/${doc.id}/revisions`,
                      { content },
                    );
                    setDirty(false);
                    onSelect(result.document_id!);
                  }, "New revision saved. PDF creation is running.")
                }
              >
                Save new revision
              </Button>
              {doc.render_status !== "ready" && (
                <Button
                  disabled={working || dirty}
                  busy={action.busy}
                  onClick={() =>
                    void action.run(async () => {
                      await post(`/documents/${doc.id}/render`);
                    }, "PDF creation queued.")
                  }
                >
                  Retry PDF creation
                </Button>
              )}
            </div>
            {dirty && <small>Unsaved edits. The preview shows the saved version.</small>}
          </div>
          <div className="ai-revision">
            <div className="section-row">
              <h3>
                <Sparkle />AI revision
              </h3>
            </div>
            <Textarea
              label="Revision instructions"
              maxLength={10000}
              rows={3}
              placeholder="For example: make the opening more direct and emphasise my customer-facing experience."
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
            <Button
              disabled={!instructions.trim() || dirty || working}
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  const result = await post<Accepted>(
                    `/documents/${doc.id}/ai-revisions`,
                    { instructions },
                  );
                  setDirty(false);
                  onNewRun(result.run_id!);
                }, "AI revision started. Your previous version is preserved.")
              }
            >
              <Sparkle />
              Request revision <ArrowRight />
            </Button>
            {dirty && (
              <small>Save your edits before requesting an AI revision.</small>
            )}
          </div>
        </section>
        <aside className="preview-panel">
          <div className="panel-bar">
            <div>
              <h2>{label(doc.kind)}</h2>
            </div>
            {doc.render_status === "ready" && (
              <a href={pdfUrl(doc.id, true)} className="btn">
                <DownloadSimple />
                Download
              </a>
            )}
          </div>
          {doc.render_status === "ready" ? (
            <iframe
              title={`${label(doc.kind)} PDF preview`}
              className="pdf-preview"
              src={`${pdfUrl(doc.id)}#toolbar=0&view=FitH`}
            />
          ) : (
            <div className="preview-placeholder">
              <FileText weight="light" />
              <h3>
                {working
                  ? "Your PDF is being prepared."
                  : "Your draft is saved."}
              </h3>
              <p>
                {working
                  ? "The preview appears when PDF creation completes."
                  : "Edit and save a revision, or retry PDF creation."}
              </p>
            </div>
          )}
          <div className="preview-foot">
            <Check />
            {doc.kind === "cover_letter"
              ? "Cover letter · One page"
              : "Fixed Inter template · A4 · One page"}
          </div>
          {doc.render_status === "ready" && (
            <Link
              to={`/jobs/${jobId}/application`}
              className="btn primary record-cta"
            >
              Record application <ArrowRight />
            </Link>
          )}
        </aside>
      </div>
    </>
  );
}

export function JobDocuments({
  run,
  job,
  onNewRun,
}: {
  run?: Run;
  job: Job;
  onNewRun: (id: number) => void;
}) {
  const [kind, setKind] = useState<"resume" | "cover_letter">(
    run?.source_snapshot?.source_document?.kind || "resume",
  );
  const [offsets, setOffsets] = useState({ resume: 0, cover_letter: 0 });
  const { dirty, setDirty } = useWorkspace();
  const action = useAction();
  const selections = useResource<DocumentSelections>(`/jobs/${job.id}/document-selections`, 2000);
  const versions = useResource<Page<Document>>(
    `/jobs/${job.id}/documents?kind=${kind}&limit=25&offset=${offsets[kind]}`, 2000,
  );
  const docs = versions.data?.items || [];
  const chosen = selections.data?.[kind];
  const viewed = useRef<Partial<Record<"resume" | "cover_letter", number>>>({});
  // A completed background rewrite must not discard unsaved edits to the viewed version.
  if (!dirty) viewed.current[kind] = chosen?.id || docs[0]?.id;
  const chosenId = selections.data ? viewed.current[kind] || chosen?.id || docs[0]?.id : undefined;
  const detail = useResource<Document>(chosenId ? `/documents/${chosenId}` : null, 2000);
  const shown = detail.data || chosen;
  const selectVersion = async (id: number) => {
    await post(`/jobs/${job.id}/document-selections`, { document_id: id });
    selections.reload();
    versions.reload();
  };
  const switchTo = (action: () => void) => {
    if (
      dirty &&
      !window.confirm(
        "Leave these unsaved edits? Saved revisions are preserved.",
      )
    )
      return;
    setDirty(false);
    action();
  };
  return (
    <>
      <div className="document-tabs">
        <div className="segmented" role="group" aria-label="Document type">
          {(["resume", "cover_letter"] as const).map((value) => {
            const latest = selections.data?.[value];
            return (
              <Button
                key={value}
                className={value === kind ? "selected" : ""}
                onClick={() =>
                  switchTo(() => {
                    setKind(value);
                  })
                }
              >
                <FileText />
                {label(value)}
                {latest?.render_status === "ready" && (
                  <Check className="ready-check" />
                )}
              </Button>
            );
          })}
        </div>
        {shown && <Badge value={shown.render_status} />}
      </div>
      {run && (run.status === "failed" || run.status === "partial" || run.status === "interrupted") && (
        <Notice>
          Generation attempt #{run.id} had an issue. Your selected documents and earlier versions remain available.
          {run.review_findings?.map((finding, index) => <p key={index}>{finding.message}</p>)}
        </Notice>
      )}
      <TaskStatus tasks={run?.tasks || []} />
      <ErrorMessage error={selections.error} retry={selections.reload} />
      <ErrorMessage error={versions.error} retry={versions.reload} />
      <ErrorMessage error={action.error} />
      {docs.length > 0 && (
        <div className="document-version-row">
          <DocumentVersionPicker
            kind={kind}
            documents={docs}
            selected={shown}
            selectedId={chosenId}
            disabled={action.busy || !!selections.error}
            onSelect={(id) =>
              switchTo(() => void action.run(() => selectVersion(id)))
            }
          />
          <span className="muted">
            Your résumé and cover-letter versions are selected independently.
          </span>
        </div>
      )}
      {versions.data && (
        <Pagination limit={25} total={versions.data.total} offset={offsets[kind]}
          onChange={(offset) => switchTo(() => setOffsets((current) => ({ ...current, [kind]: offset })))} />
      )}
      <ErrorMessage error={detail.error} retry={detail.reload} />
      {detail.loading || versions.loading || selections.loading ? (
        <Loading text="Opening document…" />
      ) : selections.error && !selections.data ? (
        <Notice>Retry loading your document selections above to restore the saved versions.</Notice>
      ) : detail.data ? (
        <DocumentEditor
          key={detail.data.id}
          doc={detail.data}
          source={detail.data.source_resume}
          onSelect={(id) => void action.run(() => selectVersion(id))}
          onNewRun={(id) => switchTo(() => onNewRun(id))}
          jobId={job.id}
        />
      ) : (
        <div className="panel">
          <Empty
            icon={<FileText />}
            title={
              ["running", "queued"].includes(run?.status || "")
                ? `Preparing your ${label(kind).toLowerCase()}…`
                : `No ${label(kind).toLowerCase()} draft yet.`
            }
          >
            {["running", "queued"].includes(run?.status || "")
              ? "It will appear here as preparation progresses."
              : "Prepare documents to create the first version. Each document keeps its own history."}
          </Empty>
        </div>
      )}
    </>
  );
}
