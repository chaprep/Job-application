import { useRef, useState, type DragEvent } from "react";
import {
  ArrowRight,
  Check,
  DownloadSimple,
  FileArrowUp,
  FileText,
  ShieldCheck,
  UploadSimple,
} from "@phosphor-icons/react";
import { api, ApiError, activeTask, dateLabel, post } from "./api";
import { ContentEditor } from "./ContentEditor";
import { useAction, useDirty, useResource, useWorkspace } from "./state";
import {
  Badge,
  Button,
  ErrorMessage,
  Findings,
  Link,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  TaskStatus,
} from "./ui";
import type {
  Accepted,
  Content,
  Page,
  Readiness,
  Resume,
  ResumeContent,
} from "./types";

function Upload({ compact = false }: { compact?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const action = useAction();
  const { navigate } = useWorkspace();
  const upload = (file?: File) => {
    if (!file) return;
    void action.run(async () => {
      if (!/\.(pdf|docx)$/i.test(file.name))
        throw new Error("Choose a PDF or DOCX résumé.");
      if (file.size > 10 * 1024 * 1024)
        throw new Error("Choose a file smaller than 10 MiB.");
      const data = new FormData();
      data.append("file", file);
      const accepted = await api<Accepted>("/resumes", {
        method: "POST",
        body: data,
      });
      navigate(`/resume/${accepted.resume_version_id}`);
    }, "Résumé uploaded. Extraction queued.");
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length > 1)
      void action.run(async () => {
        throw new Error("Upload one base résumé at a time.");
      });
    else upload(e.dataTransfer.files[0]);
  };
  return (
    <>
      <div
        className={`upload-zone ${compact ? "compact" : ""} ${over ? "dragover" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!action.busy) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          if (!action.busy) drop(e);
          else e.preventDefault();
        }}
      >
        <div className="upload-symbol">
          <FileArrowUp weight="light" />
        </div>
        <h2>{compact ? "Replace résumé" : "Upload résumé"}</h2>
        <p>Drop a file here or choose one below.</p>
        <input
          ref={input}
          type="file"
          className="sr-only"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          aria-label="Upload base résumé"
          disabled={action.busy}
          onChange={(e) => {
            upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          tone="primary"
          busy={action.busy}
          onClick={() => input.current?.click()}
        >
          <UploadSimple />
          Choose résumé
        </Button>
        <small>PDF or DOCX · up to 10 MiB</small>
      </div>
      <ErrorMessage error={action.error} />
    </>
  );
}

export function LinkOverrideNotice({
  error,
  confirmed,
  busy,
  onOverride,
}: {
  error?: Error;
  confirmed: boolean;
  busy: boolean;
  onOverride: () => void;
}) {
  if (!(error instanceof ApiError) || !error.fields?.can_override_links)
    return null;
  return (
    <Notice>
      <p>
        You can keep these links exactly as entered. They will appear as plain
        text in PDFs. Your other résumé checks still apply.
      </p>
      <Button disabled={!confirmed} busy={busy} onClick={onOverride}>
        Override and activate as is
      </Button>
    </Notice>
  );
}

function ResumeReview({
  resume,
  readiness,
}: {
  resume: Resume;
  readiness?: Readiness;
}) {
  const [content, setContent] = useState<ResumeContent | null>(
    resume.reviewed_content,
  );
  const [confirmed, setConfirmed] = useState(false);
  const setDirty = useDirty();
  const action = useAction();
  const { navigate, refresh } = useWorkspace();
  const { dirty } = useWorkspace();
  const parent = useResource<Resume>(
    resume.parent_resume_id ? `/resumes/${resume.parent_resume_id}` : null,
  );
  const working = activeTask(resume.tasks);
  const update = (value: Content) => {
    setContent(value as ResumeContent);
    setDirty(true);
    setConfirmed(false);
    action.clearError();
  };
  const save = (activate: boolean, overrideInvalidLinks = false) =>
    void action.run(
      async () => {
        const result = await post<{ resume_version_id: number }>(
          `/resumes/${resume.id}/${activate ? "activate" : "draft"}`,
          {
            content,
            ...(activate
              ? {
                  confirmed: true,
                  override_invalid_links: overrideInvalidLinks,
                }
              : {}),
          },
          activate ? "POST" : "PATCH",
        );
        setDirty(false);
        setConfirmed(false);
        refresh();
        if (result.resume_version_id !== resume.id)
          navigate(`/resume/${result.resume_version_id}`);
      },
      activate
        ? "Base résumé activated."
        : "Résumé draft saved.",
    );
  return (
    <>
      <div className="section-row resume-title">
        <div>
          <span className="eyebrow">Version {resume.id}</span>
          <h2>{resume.original_filename}</h2>
          <p className="muted">Uploaded {dateLabel(resume.created_at)}</p>
        </div>
        <Badge value={resume.is_active ? "active" : resume.status} />
      </div>
      <div className="reimport-resume">
        <Button
          disabled={working}
          busy={action.busy}
          onClick={() => {
            if (
              dirty &&
              !window.confirm(
                "Re-import the original file? Unsaved edits in this panel will not be included. Your saved versions stay preserved.",
              )
            )
              return;
            void action.run(async () => {
              const result = await post<Accepted>(
                `/resumes/${resume.id}/reimport`,
              );
              setDirty(false);
              navigate(`/resume/${result.resume_version_id}`);
            }, "A new résumé draft is being imported with its hyperlinks.");
          }}
        >
          Re-import original with links
        </Button>
        <small>
          Creates a new draft from the original file. Your current active résumé
          stays in use until you review and activate the new version.
        </small>
      </div>
      {parent.data?.reviewed_content && (
        <details className="panel previous-resume">
          <summary>
            Compare with previous reviewed version (v{parent.data.id})
          </summary>
          <p className="editor-intro">
            Re-importing the original does not include edits made later in Jab.
            Compare here and carry across any changes you want to keep.
          </p>
          <fieldset disabled>
            <ContentEditor
              value={parent.data.reviewed_content}
              onChange={() => {}}
            />
          </fieldset>
        </details>
      )}
      <ErrorMessage error={parent.error} retry={parent.reload} />
      <TaskStatus tasks={resume.tasks} />
      <Findings findings={resume.validation_overrides || []} />
      <Findings
        findings={
          resume.tasks?.find((t) => t.result?.findings)?.result?.findings
        }
      />
      {resume.error_message && (
        <Notice kind="error">{resume.error_message}</Notice>
      )}
      {!content && !working && (
        <div className="panel pad">
          <p>
            Your original file is saved. Retry extraction to organise its
            contents for review.
          </p>
          <Button
            busy={action.busy}
            onClick={() =>
              void action.run(async () => {
                await post(`/resumes/${resume.id}/retry-extraction`);
              }, "Extraction queued.")
            }
          >
            <ArrowRight />
            Retry extraction
          </Button>
        </div>
      )}
      {content && (
        <>
          <div className="split-workspace">
            <section className="panel editor-panel">
              <div className="panel-bar">
                <div>
                  <h2>Review résumé</h2>
                </div>
                <ShieldCheck />
              </div>
              <p className="editor-intro">
                Check the extracted content before activating this résumé.
              </p>
              <fieldset disabled={action.busy || working}>
                <ContentEditor value={content} onChange={update} />
              </fieldset>
              <div className="editor-footer">
                <ErrorMessage error={action.error} />
                <LinkOverrideNotice
                  error={action.error}
                  confirmed={confirmed}
                  busy={action.busy || working}
                  onOverride={() => save(true, true)}
                />
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>
                    I’ve reviewed this content and confirm it accurately
                    represents my experience.
                  </span>
                </label>
                <div className="row">
                  <Button
                    busy={action.busy}
                    disabled={working}
                    onClick={() => save(false)}
                  >
                    Save draft
                  </Button>
                  <Button
                    tone="primary"
                    busy={action.busy}
                    disabled={!confirmed || working}
                    onClick={() => save(true)}
                  >
                    <Check />
                    Save and activate
                  </Button>
                </div>
                {resume.status === "ready" && (
                  <small>
                    Changes create a new version. Past application documents
                    stay preserved.
                  </small>
                )}
              </div>
            </section>
            <aside className="preview-panel">
              <div className="panel-bar">
                <h2>Original résumé</h2>
                <a
                  className="btn quiet"
                  href={`/api/v1/resumes/${resume.id}/original`}
                >
                  <DownloadSimple />
                  Original
                </a>
              </div>
              {resume.file_type === "pdf" ? (
                <iframe
                  title="Original base résumé PDF"
                  src={`/api/v1/resumes/${resume.id}/original?download=false#toolbar=0`}
                  className="pdf-preview"
                />
              ) : (
                <div className="source-text">
                  <span className="eyebrow">Extracted text</span>
                  <p>
                    {resume.extracted_text ||
                      "Original DOCX available to download above."}
                  </p>
                </div>
              )}
            </aside>
          </div>
        </>
      )}
      {!content && <ErrorMessage error={action.error} />}
      {readiness && !readiness.ai_configured && (
        <Notice>
          AI isn’t configured yet. Your file stays saved; connect your provider
          before retrying extraction.
        </Notice>
      )}
    </>
  );
}

export function ResumePage({ selectedId }: { selectedId?: number }) {
  const [offset, setOffset] = useState(0);
  const list = useResource<Page<Resume>>(
    `/resumes?limit=20&offset=${offset}`,
    3000,
  );
  const active = useResource<Resume | null>("/resumes/active", 3000);
  const readiness = useResource<Readiness>("/readiness");
  const id = selectedId || active.data?.id || list.data?.items[0]?.id;
  const detail = useResource<Resume>(id ? `/resumes/${id}` : null, 2000);
  return (
    <>
      <PageHeader title="Base résumé" />
      {list.error && <ErrorMessage error={list.error} retry={list.reload} />}
      {list.loading ? (
        <Loading />
      ) : list.data?.total === 0 ? (
        <Upload />
      ) : (
        <>
          <div className="resume-overview">
            <div className="active-base">
              <div className="file-symbol">
                <FileText />
              </div>
              <div>
                <span className="eyebrow">Active base résumé</span>
                <strong>
                  {active.data?.original_filename || "No active résumé yet"}
                </strong>
                <span className="muted">
                  {active.data
                    ? `Version ${active.data.id} · ready for new applications`
                    : "Review and activate a version below to start tailoring."}
                </span>
              </div>
              {active.data && (
                <Link to="/jobs" className="text-link">
                  Go to jobs <ArrowRight />
                </Link>
              )}
            </div>
            <details className="replace-resume">
              <summary>
                <UploadSimple />
                Upload a new résumé
              </summary>
              <Upload compact />
            </details>
          </div>
          <div className="version-picker">
            <span>Version history</span>
            {list.data?.items.map((r) => (
              <Link
                key={r.id}
                to={`/resume/${r.id}`}
                className={`version-chip ${r.id === id ? "selected" : ""}`}
              >
                v{r.id}
                {r.is_active ? <Check /> : null}
                <span className="sr-only">{r.original_filename}</span>
              </Link>
            ))}
          </div>
          {list.data && (
            <Pagination
              total={list.data.total}
              offset={offset}
              onChange={setOffset}
            />
          )}
          <ErrorMessage error={detail.error} retry={detail.reload} />
          {detail.loading ? (
            <Loading text="Loading résumé…" />
          ) : (
            detail.data && (
              <ResumeReview
                key={`${detail.data.id}-${!!detail.data.reviewed_content}`}
                resume={detail.data}
                readiness={readiness.data}
              />
            )
          )}
        </>
      )}
    </>
  );
}
