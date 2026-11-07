import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleNotch,
  WarningCircle,
} from "@phosphor-icons/react";
import { api, ApiError, dateLabel, label } from "./api";
import { useAction, useWorkspace } from "./state";
import type { Finding, Task } from "./types";

export function Button({
  children,
  tone = "default",
  className = "",
  busy = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "default" | "primary" | "quiet" | "danger";
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`btn ${tone} ${className}`}
      aria-busy={busy || undefined}
    >
      {busy && <CircleNotch className="spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function DeleteButton({
  kind,
  id,
  name,
  disabled,
  onDeleted,
}: {
  kind: "job" | "application";
  id: number;
  name: string;
  disabled?: boolean;
  onDeleted?: () => void;
}) {
  const action = useAction();
  const [confirming, setConfirming] = useState(false);
  const { dirty, setDirty } = useWorkspace();
  const collection = kind === "job" ? "jobs" : "applications";
  return (
    <div>
      <Button
        tone="danger"
        disabled={disabled}
        busy={action.busy}
        aria-label={`Delete ${kind}: ${name}`}
        onClick={() => {
          action.clearError();
          setConfirming(true);
        }}
      >
        Delete {kind}
      </Button>
      {confirming && (
        <DeleteConfirmation
          kind={kind}
          name={name}
          dirty={dirty}
          busy={action.busy}
          error={action.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void action.run(
            async () => {
              await api(`/${collection}/${id}`, { method: "DELETE" });
              setConfirming(false);
              if (onDeleted) {
                setDirty(false);
                onDeleted();
              }
            },
            `${kind === "job" ? "Job" : "Application"} deleted.`,
          )}
        />
      )}
    </div>
  );
}

export function DeleteConfirmation({
  kind, name, dirty, busy, error, onCancel, onConfirm,
}: {
  kind: "job" | "application";
  name: string;
  dirty: boolean;
  busy: boolean;
  error?: Error;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="delete-dialog"
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-busy={busy || undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <span className="eyebrow">Your workspace</span>
      <h2 id={titleId}>Delete this {kind}?</h2>
      <div id={descriptionId} className="delete-dialog-copy">
        <p className="delete-dialog-name">{name}</p>
        <p>
          This will remove it from your {kind === "job" ? "jobs" : "applications"}.
          {kind === "job"
            ? " Linked applications and saved documents will remain available."
            : " Your linked job and submitted documents will remain available."}
          {" "}Its history will be retained.
        </p>
        {dirty && <p className="delete-dialog-warning">Unsaved edits will be discarded.</p>}
      </div>
      <ErrorMessage error={error} />
      <div className="delete-dialog-actions">
        <Button autoFocus disabled={busy} onClick={onCancel}>Cancel</Button>
        <Button tone="danger" busy={busy} onClick={onConfirm}>
          {busy ? "Deleting…" : `Delete ${kind}`}
        </Button>
      </div>
    </dialog>
  );
}
export function Link({
  to,
  children,
  className = "",
  "aria-current": ariaCurrent,
}: {
  to: string;
  children: ReactNode;
  className?: string;
  "aria-current"?: "page";
}) {
  const { navigate } = useWorkspace();
  return (
    <a
      href={`#${to}`}
      className={className}
      aria-current={ariaCurrent}
      onClick={(e) => {
        if (!e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
          e.preventDefault();
          navigate(to);
        }
      }}
    >
      {children}
    </a>
  );
}
export function ExternalLink({
  href,
  children,
}: {
  href?: string;
  children: ReactNode;
}) {
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-link"
    >
      {children}
      <ArrowUpRight aria-hidden="true" />
    </a>
  ) : null;
}
export function Field({
  label: title,
  hint,
  wide,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  wide?: boolean;
}) {
  const id = useId();
  return (
    <div className={`field ${wide ? "wide" : ""}`}>
      <label htmlFor={id}>
        {title}
        {props.required && <span className="required"> *</span>}
      </label>
      <input
        id={id}
        {...props}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  );
}
export function Textarea({
  label: title,
  hint,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>
        {title}
        {props.required && <span className="required"> *</span>}
      </label>
      <textarea
        id={id}
        rows={4}
        {...props}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  );
}
export function Select({
  label: title,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{title}</label>
      <select id={id} {...props}>
        {children}
      </select>
    </div>
  );
}
export function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <span aria-hidden="true" />
      {label(value)}
    </span>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  children,
  back,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children?: ReactNode;
  back?: { to: string; label: string };
}) {
  return (
    <>
      <div className="page-header">
        <div>
          {back && (
            <Link to={back.to} className="back-link">
              <ArrowLeft />
              {back.label}
            </Link>
          )}
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h1>{title}</h1>
          {description && <p className="lede">{description}</p>}
        </div>
        {children && <div className="header-actions">{children}</div>}
      </div>
    </>
  );
}
export function Empty({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function ErrorMessage({
  error,
  retry,
}: {
  error?: Error | null;
  retry?: () => void;
}) {
  if (!error) return null;
  const fields = error instanceof ApiError ? error.fields : undefined;
  return (
    <div className="notice error" role="alert">
      <WarningCircle aria-hidden="true" />
      <div>
        <strong>{error.message}</strong>
        {fields?.issues?.map((issue, i) => (
          <p key={i}>
            {issue.field || issue.loc?.join(" › ")}:{" "}
            {issue.message || issue.msg}
          </p>
        ))}
        {fields?.findings?.map((f, i) => (
          <p key={i}>
            {f.field}: {f.explanation}
          </p>
        ))}
        {retry && (
          <Button tone="quiet" onClick={retry}>
            Try again <ArrowRight />
          </Button>
        )}
      </div>
    </div>
  );
}
export function Notice({
  children,
  kind = "",
  icon,
}: {
  children: ReactNode;
  kind?: string;
  icon?: ReactNode;
}) {
  return (
    <div className={`notice ${kind}`}>
      {icon || <WarningCircle aria-hidden="true" />}
      <div>{children}</div>
    </div>
  );
}
export function Loading({
  text = "Loading your workspace…",
}: {
  text?: string;
}) {
  return (
    <div className="loading" role="status">
      <CircleNotch className="spin" />
      <span>{text}</span>
    </div>
  );
}
export function Pagination({
  total,
  offset,
  limit = 20,
  onChange,
}: {
  total: number;
  offset: number;
  limit?: number;
  onChange: (v: number) => void;
}) {
  if (total <= limit) return null;
  return (
    <div className="pagination">
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="row">
        <Button
          disabled={!offset}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ArrowLeft />
          Previous
        </Button>
        <Button
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}
const steps: Record<string, string> = {
  queued: "Waiting to start",
  extracting_text: "Reading your résumé",
  organising_resume: "Organising your résumé for review",
  capturing_job: "Capturing the job description",
  extracting_job_fields: "Finding the job details",
  drafting_resume: "Tailoring your résumé",
  drafting_cover_letter: "Writing your cover letter",
  reviewing_resume: "Checking résumé facts and wording",
  reviewing_cover_letter: "Checking your cover letter",
  rendering_resume: "Building and checking the résumé PDF",
  rendering_cover_letter: "Building and checking the cover letter PDF",
};
export function TaskStatus({ tasks = [] }: { tasks?: Task[] }) {
  const task = tasks[0];
  if (!task || task.status === "succeeded") return null;
  const processing = ["running", "queued"].includes(task.status);
  return (
    <div className={`task-status ${processing ? "" : "failed"}`} role="status">
      {processing ? <CircleNotch className="spin" /> : <WarningCircle />}
      <div>
        <strong>
          {processing
            ? steps[task.step] || "Working on it"
            : task.status === "interrupted"
              ? "Work was interrupted"
              : "This step needs attention"}
        </strong>
        <p>
          {processing
            ? "You can leave this page. Saved progress stays in Jab."
            : task.error_message ||
              "Your saved source is still available. Review it and retry."}
        </p>
      </div>
    </div>
  );
}
export function Findings({ findings = [] }: { findings?: Finding[] }) {
  if (!findings.length) return null;
  return (
    <details
      className="findings"
      open={findings.some((f) => f.severity === "error")}
    >
      <summary>
        <WarningCircle />
        {findings.length} review{" "}
        {findings.length === 1 ? "finding" : "findings"}
      </summary>
      <ul>
        {findings.map((f, i) => (
          <li key={i}>
            <span className={`finding-severity ${f.severity}`}>
              {f.severity}
            </span>
            <strong>{f.field}</strong>
            <p>{f.explanation}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
export function SavedDate({ value }: { value: string }) {
  return <span className="muted">Added {dateLabel(value)}</span>;
}
export function Stepper({ current }: { current: number }) {
  return (
    <ol className="stepper">
      {[
        "Job details",
        "Prepare documents",
        "Review and download",
        "Record application",
      ].map((step, i) => (
        <li
          key={step}
          className={i < current ? "complete" : i === current ? "current" : ""}
          aria-current={i === current ? "step" : undefined}
        >
          <span>
            {i < current ? <Check /> : String(i + 1).padStart(2, "0")}
          </span>
          {step}
        </li>
      ))}
    </ol>
  );
}
