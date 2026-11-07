import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Briefcase,
  CalendarBlank,
  Check,
  Clock,
  DownloadSimple,
  FileText,
  MagnifyingGlass,
  NotePencil,
  Plus,
} from "@phosphor-icons/react";
import { dateLabel, label, pdfUrl, post, safeUrl, today } from "./api";
import { useAction, useDirty, useResource, useWorkspace } from "./state";
import {
  Badge,
  Button,
  DeleteButton,
  Empty,
  ErrorMessage,
  ExternalLink,
  Field,
  Link,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  Select,
  Textarea,
} from "./ui";
import {
  stages,
  type Application,
  type ApplicationEvent,
  type Document,
  type DocumentSelections,
  type Job,
  type Page,
  type Stage,
} from "./types";

export function RecordApplication({ job }: { job?: Job }) {
  const [company, setCompany] = useState(job?.company || "");
  const [role, setRole] = useState(job?.title || "");
  const [date, setDate] = useState(today());
  const [url, setUrl] = useState(job?.source_url || "");
  const [stage, setStage] = useState<Stage>("applied");
  const [confirmed, setConfirmed] = useState(false);
  const [resumeId, setResumeId] = useState("");
  const [letterId, setLetterId] = useState("");
  const [offset, setOffset] = useState(0);
  const documents = useResource<Page<Document>>(
    job
      ? `/jobs/${job.id}/documents?status=ready&limit=100&offset=${offset}`
      : null,
    3000,
  );
  const selections = useResource<DocumentSelections>(job ? `/jobs/${job.id}/document-selections` : null);
  const initialized = useRef(false);
  useEffect(() => {
    if (!initialized.current && selections.data) {
      initialized.current = true;
      setResumeId(selections.data.resume ? String(selections.data.resume.id) : "");
      setLetterId(selections.data.cover_letter ? String(selections.data.cover_letter.id) : "");
    }
  }, [selections.data]);
  const selectedResume = useResource<Document>(resumeId ? `/documents/${resumeId}` : null, 3000);
  const selectedLetter = useResource<Document>(letterId ? `/documents/${letterId}` : null, 3000);
  const ready = selectedResume.data?.render_status === "ready" &&
    (!letterId || selectedLetter.data?.render_status === "ready");
  const resume = resumeId;
  const letter = letterId;
  const action = useAction();
  const setDirty = useDirty();
  const { navigate } = useWorkspace();
  return (
    <section className="panel record-panel">
      {job && (
        <div className="panel-bar">
          <h2>Record application</h2>
          <Briefcase />
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            if (job && (!confirmed || !ready)) return;
            const result = await post<Application>("/applications", {
              origin: job ? "jab" : "external",
              company: company.trim(),
              role: role.trim(),
              job_id: job?.id || null,
              applied_on: date || null,
              application_url: url.trim() || null,
              stage,
              resume_document_id: resume ? Number(resume) : null,
              cover_letter_document_id: letter ? Number(letter) : null,
            });
            setDirty(false);
            navigate(`/applications/${result.id}`);
          }, "Application recorded.");
        }}
      >
        <fieldset
          disabled={action.busy}
          className="pad form-stack"
          onChange={() => setDirty(true)}
        >
          <div className="form-grid">
            <Field
              label="Company"
              required
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
            <Field
              label="Role"
              required
              value={role}
              onChange={(e) => setRole(e.target.value)}
            />
            <Field
              label="Applied on"
              type="date"
              required={!!job}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              hint={job ? undefined : "Leave blank if the date is unknown."}
            />
            <Select
              label="Current stage"
              value={stage}
              onChange={(e) => setStage(e.target.value as Stage)}
            >
              {stages.map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </Select>
            <Field
              wide
              label="Application or posting URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          {job && (
            <>
              <div className="submission-files">
                <h3>Submitted documents</h3>
                <p className="muted">
                  Select the versions submitted to the employer.
                </p>
                <ErrorMessage error={selections.error} retry={selections.reload} />
                <ErrorMessage error={selectedResume.error} retry={selectedResume.reload} />
                <ErrorMessage error={selectedLetter.error} retry={selectedLetter.reload} />
                <ErrorMessage
                  error={documents.error}
                  retry={documents.reload}
                />
                <div className="form-grid">
                  <Select
                    label="Submitted résumé"
                    required
                    value={resume}
                    onChange={(e) => {
                      initialized.current = true;
                      setResumeId(e.target.value);
                      setConfirmed(false);
                    }}
                  >
                    <option value="">Choose a ready résumé</option>
                    {resume &&
                      !documents.data?.items.some(
                        (d) => String(d.id) === resume,
                      ) && (
                        <option value={resume}>
                          Résumé version {selectedResume.data?.version_number ?? "…"} · document #{resume}
                        </option>
                      )}
                    {documents.data?.items
                      .filter((d) => d.kind === "resume")
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          Version {d.version_number ?? d.revision} ·
                          document #{d.id}
                        </option>
                      ))}
                  </Select>
                  <Select
                    label="Submitted cover letter (optional)"
                    value={letter}
                    onChange={(e) => {
                      initialized.current = true;
                      setLetterId(e.target.value);
                      setConfirmed(false);
                    }}
                  >
                    <option value="">No cover letter submitted</option>
                    {letter &&
                      !documents.data?.items.some(
                        (d) => String(d.id) === letter,
                      ) && (
                        <option value={letter}>
                          Cover-letter version {selectedLetter.data?.version_number ?? "…"} · document #{letter}
                        </option>
                      )}
                    {documents.data?.items
                      .filter((d) => d.kind === "cover_letter")
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          Version {d.version_number ?? d.revision} ·
                          document #{d.id}
                        </option>
                      ))}
                  </Select>
                </div>
                {documents.data && (
                  <Pagination
                    limit={100}
                    total={documents.data.total}
                    offset={offset}
                    onChange={(value) => {
                      setResumeId(resume);
                      setLetterId(letter);
                      setOffset(value);
                    }}
                  />
                )}
                <div className="row">
                  {resume && (
                    <ExternalLink href={pdfUrl(Number(resume))}>
                      Review selected résumé
                    </ExternalLink>
                  )}
                  {letter && (
                    <ExternalLink href={pdfUrl(Number(letter))}>
                      Review selected letter
                    </ExternalLink>
                  )}
                </div>
                {!documents.loading && documents.data?.total === 0 && (
                  <Notice>
                    Prepare a ready résumé before recording a Jab application.{" "}
                    <Link
                      to={`/jobs/${job.id}/documents`}
                      className="text-link"
                    >
                      Go to documents <ArrowRight />
                    </Link>
                  </Notice>
                )}
              </div>
              <p>
                Recording: résumé version {selectedResume.data?.version_number ?? "…"}
                {letter ? ` + cover-letter version ${selectedLetter.data?.version_number ?? "…"}` : " + no cover letter"}.
              </p>
              {(resume || letter) && !ready && <Notice>Choose saved, PDF-ready versions before confirming your submission.</Notice>}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={!ready}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                <span>
                  I’ve submitted this application on the employer’s website and
                  checked the selected document versions.
                </span>
              </label>
            </>
          )}
          <ErrorMessage error={action.error} />
          <div className="form-end">
            {job && <p className="muted">Downloading documents does not record a submission.</p>}
            <Button
              tone="primary"
              type="submit"
              busy={action.busy}
              disabled={!!job && (!confirmed || !ready)}
            >
              <Check />
              Record application
            </Button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

export function ApplicationsPage() {
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const [due, setDue] = useState(false);
  const [offset, setOffset] = useState(0);
  const apps = useResource<Page<Application>>(
    `/applications?limit=20&offset=${offset}&search=${encodeURIComponent(search)}${stage ? `&stage=${stage}` : ""}${due ? `&due_before=${today()}` : ""}`,
    5000,
  );
  const total = useResource<Page<Application>>("/applications?limit=1");
  const interviews = useResource<Page<Application>>(
    "/applications?stage=interviewing&limit=1",
  );
  const followups = useResource<Page<Application>>(
    `/applications?due_before=${today()}&limit=1`,
  );
  return (
    <>
      <PageHeader
        title="Applications"
      >
        <Link to="/applications/new" className="btn primary">
          <Plus />
          Record application
        </Link>
      </PageHeader>
      <div className="stats-strip">
        <div>
          <Briefcase />
          <span>Total applications</span>
          <strong>{total.data?.total ?? "…"}</strong>
        </div>
        <div>
          <CalendarBlank />
          <span>Interviewing</span>
          <strong>{interviews.data?.total ?? "…"}</strong>
        </div>
        <div>
          <Clock />
          <span>Follow-ups due</span>
          <strong>{followups.data?.total ?? "…"}</strong>
        </div>
      </div>
      <div className="toolbar">
        <label className="search-field">
          <MagnifyingGlass />
          <span className="sr-only">Search applications</span>
          <input
            type="search"
            placeholder="Search company or role…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <Select
          label="Application stage"
          value={stage}
          onChange={(e) => {
            setStage(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All stages</option>
          {stages.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </Select>
        <label className="filter-checkbox">
          <input
            type="checkbox"
            checked={due}
            onChange={(e) => {
              setDue(e.target.checked);
              setOffset(0);
            }}
          />
          Follow-ups due
        </label>
      </div>
      <ErrorMessage error={apps.error} retry={apps.reload} />
      {apps.loading ? (
        <Loading />
      ) : apps.data?.items.length ? (
        <>
          <div className="table-wrap panel">
            <table className="applications-table">
              <thead>
                <tr>
                  <th>Company and role</th>
                  <th>Stage</th>
                  <th>Applied</th>
                  <th>Next action</th>
                  <th>
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {apps.data.items.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Link
                        className="table-title"
                        to={`/applications/${a.id}`}
                      >
                        {a.company}
                        <span>{a.role}</span>
                      </Link>
                    </td>
                    <td>
                      <Badge value={a.stage} />
                    </td>
                    <td className="date-cell">{dateLabel(a.applied_on)}</td>
                    <td>
                      <span className="next-action-text">
                        {a.next_action || "No next action"}
                      </span>
                      {a.next_action_due_on && (
                        <span
                          className={`due-date ${a.next_action_due_on <= today() ? "overdue" : ""}`}
                        >
                          {dateLabel(a.next_action_due_on)}
                        </span>
                      )}
                    </td>
                    <td>
                      <Link to={`/applications/${a.id}`} className="icon-link">
                        <ArrowUpRight />
                        <span className="sr-only">
                          Open {a.company} application
                        </span>
                      </Link>
                      <DeleteButton kind="application" id={a.id}
                        name={`${a.role} at ${a.company}`} onDeleted={() => setOffset(0)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            total={apps.data.total}
            offset={offset}
            onChange={setOffset}
          />
        </>
      ) : (
        <div className="panel">
          <Empty
            icon={<Briefcase weight="light" />}
            title={
              search || stage || due
                ? "No matching applications"
                : "No applications recorded"
            }
            action={
              <Link to="/applications/new" className="btn">
                Record an application <Plus />
              </Link>
            }
          >
            {search || stage || due
              ? "Try changing your search, stage, or follow-up filter."
              : "Record a submitted application to track its status and follow-ups."}
          </Empty>
        </div>
      )}
    </>
  );
}

function StageEditor({ application }: { application: Application }) {
  const [stage, setStage] = useState<Stage>(application.stage);
  const [occurred, setOccurred] = useState("");
  const action = useAction();
  const dirty = useDirty();
  return (
    <fieldset disabled={action.busy} className="panel pad form-stack">
      <h2>Status</h2>
      <Select
        label="Stage"
        value={stage}
        onChange={(e) => {
          setStage(e.target.value as Stage);
          dirty(true);
        }}
      >
        {stages.map((s) => (
          <option key={s} value={s}>
            {label(s)}
          </option>
        ))}
      </Select>
      <details className="optional-details">
        <summary>Record an earlier update</summary>
        <Field
          label="When this happened"
          type="datetime-local"
          value={occurred}
          onChange={(e) => {
            setOccurred(e.target.value);
            dirty(true);
          }}
          hint="Leave blank to record it now."
        />
      </details>
      <Button
        tone="primary"
        disabled={stage === application.stage}
        busy={action.busy}
        onClick={() =>
          void action.run(async () => {
            await post(`/applications/${application.id}/stage`, {
              stage,
              ...(occurred
                ? { occurred_at: new Date(occurred).toISOString() }
                : {}),
            });
            dirty(false);
          }, "Application stage updated.")
        }
      >
        Update stage <ArrowRight />
      </Button>
      <ErrorMessage error={action.error} />
    </fieldset>
  );
}

function FollowUpEditor({ application }: { application: Application }) {
  const [next, setNext] = useState(application.next_action || "");
  const [date, setDate] = useState(application.next_action_due_on || "");
  const action = useAction();
  const dirty = useDirty();
  return (
    <fieldset disabled={action.busy} className="panel pad form-stack">
      <div className="section-row">
        <h2>Follow-up</h2>
        <Clock />
      </div>
      <Textarea
        label="Next action"
        rows={3}
        value={next}
        placeholder="Follow up with the recruiter…"
        onChange={(e) => {
          setNext(e.target.value);
          dirty(true);
        }}
      />
      <Field
        label="Due date"
        type="date"
        value={date}
        onChange={(e) => {
          setDate(e.target.value);
          dirty(true);
        }}
      />
      <div className="row">
        <Button
          busy={action.busy}
          onClick={() =>
            void action.run(async () => {
              await post(
                `/applications/${application.id}/follow-up`,
                { next_action: next.trim() || null, due_on: date || null },
                "PUT",
              );
              dirty(false);
            }, "Next action saved.")
          }
        >
          Save next action
        </Button>
        {application.next_action && (
          <Button
            tone="quiet"
            busy={action.busy}
            onClick={() =>
              void action.run(async () => {
                await post(
                  `/applications/${application.id}/follow-up`,
                  { next_action: null, due_on: null },
                  "PUT",
                );
                setNext("");
                setDate("");
                dirty(false);
              }, "Follow-up cleared.")
            }
          >
            Clear
          </Button>
        )}
      </div>
      <small>Due dates appear in Jab. Notifications aren’t scheduled.</small>
      <ErrorMessage error={action.error} />
    </fieldset>
  );
}

function AddNote({ id }: { id: number }) {
  const [note, setNote] = useState("");
  const [occurred, setOccurred] = useState("");
  const action = useAction();
  const dirty = useDirty();
  return (
    <form
      className="note-form form-stack"
      onSubmit={(e) => {
        e.preventDefault();
        void action.run(async () => {
          await post(`/applications/${id}/notes`, {
            note: note.trim(),
            ...(occurred
              ? { occurred_at: new Date(occurred).toISOString() }
              : {}),
          });
          setNote("");
          setOccurred("");
          dirty(false);
        }, "Note added to your timeline.");
      }}
    >
      <fieldset disabled={action.busy} className="form-stack">
        <Textarea
          label="Add a note"
          required
          maxLength={100000}
          rows={3}
          placeholder="Add a note…"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            dirty(true);
          }}
        />
        <div className="form-end">
          <details className="optional-details">
            <summary>Set event date</summary>
            <Field
              label="When this happened"
              type="datetime-local"
              value={occurred}
              onChange={(e) => {
                setOccurred(e.target.value);
                dirty(true);
              }}
            />
          </details>
          <Button type="submit" disabled={!note.trim()} busy={action.busy}>
            <Plus />
            Add note
          </Button>
        </div>
        <ErrorMessage error={action.error} />
      </fieldset>
    </form>
  );
}

function CorrectionForm({ application }: { application: Application }) {
  const [company, setCompany] = useState(application.company);
  const [role, setRole] = useState(application.role);
  const [date, setDate] = useState(application.applied_on || "");
  const [url, setUrl] = useState(application.application_url || "");
  const [reason, setReason] = useState("");
  const [resume, setResume] = useState(
    String(application.resume_document_id || ""),
  );
  const [letter, setLetter] = useState(
    String(application.cover_letter_document_id || ""),
  );
  const docs = useResource<Page<Document>>(
    application.job_id
      ? `/jobs/${application.job_id}/documents?status=ready&limit=100`
      : null,
  );
  const action = useAction();
  const dirty = useDirty();
  return (
    <details className="panel correction-panel">
      <summary>
        <NotePencil />
        Correct application details
      </summary>
      <form
        className="pad form-stack"
        onChange={() => dirty(true)}
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            await post(`/applications/${application.id}/corrections`, {
              reason: reason.trim(),
              company,
              role,
              applied_on: date || null,
              application_url: url || null,
              resume_document_id: resume ? Number(resume) : null,
              cover_letter_document_id: letter ? Number(letter) : null,
            });
            setReason("");
            dirty(false);
          }, "Correction saved with an audit record.");
        }}
      >
        <fieldset disabled={action.busy} className="form-stack">
          <p className="muted">
            Corrections preserve the original values and your reason in the
            timeline.
          </p>
          <div className="form-grid">
            <Field
              label="Company"
              required
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
            <Field
              label="Role"
              required
              value={role}
              onChange={(e) => setRole(e.target.value)}
            />
            <Field
              label="Applied on"
              type="date"
              required={application.origin === "jab"}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
            <Field
              label="Application URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          {application.job_id && (
            <>
              <ErrorMessage error={docs.error} retry={docs.reload} />
              <div className="form-grid">
                <Select
                  label="Submitted résumé"
                  required={application.origin === "jab"}
                  value={resume}
                  onChange={(e) => setResume(e.target.value)}
                >
                  <option value="">None</option>
                  {resume &&
                    !docs.data?.items.some((d) => String(d.id) === resume) && (
                      <option value={resume}>Document #{resume}</option>
                    )}
                  {docs.data?.items
                    .filter((d) => d.kind === "resume")
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        Preparation #{d.run_id} · revision {d.revision} · #
                        {d.id}
                      </option>
                    ))}
                </Select>
                <Select
                  label="Submitted cover letter"
                  value={letter}
                  onChange={(e) => setLetter(e.target.value)}
                >
                  <option value="">None</option>
                  {letter &&
                    !docs.data?.items.some((d) => String(d.id) === letter) && (
                      <option value={letter}>Document #{letter}</option>
                    )}
                  {docs.data?.items
                    .filter((d) => d.kind === "cover_letter")
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        Preparation #{d.run_id} · revision {d.revision} · #
                        {d.id}
                      </option>
                    ))}
                </Select>
              </div>
            </>
          )}
          <Textarea
            label="Reason for correction"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <ErrorMessage error={action.error} />
          <Button type="submit" busy={action.busy}>
            Save correction
          </Button>
        </fieldset>
      </form>
    </details>
  );
}

function EventContent({ event }: { event: ApplicationEvent }) {
  const details = event.details;
  if (event.kind === "stage_changed")
    return (
      <p>
        {label(String(details?.old || ""))} <ArrowRight />{" "}
        {label(String(details?.new || ""))}
      </p>
    );
  if (event.kind === "next_action_changed") {
    const next = details?.new as
      | { action?: string; due_on?: string }
      | undefined;
    return (
      <p>
        {next?.action || "Follow-up cleared"}
        {next?.due_on ? ` · due ${dateLabel(next.due_on)}` : ""}
      </p>
    );
  }
  if (
    event.kind === "details_corrected" ||
    event.kind === "submission_corrected"
  ) {
    const old = (details?.old || {}) as Record<string, unknown>;
    const next = (details?.new || {}) as Record<string, unknown>;
    return (
      <>
        <p>{event.note}</p>
        <details>
          <summary>See changes</summary>
          <dl className="event-changes">
            {Object.entries(next).map(([key, value]) => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>
                  {String(old[key] ?? "Not recorded")} →{" "}
                  {String(value ?? "Not recorded")}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      </>
    );
  }
  if (event.kind === "submission_recorded")
    return (
      <p>
        Application recorded
        {details?.resume_document_id
          ? ` with résumé #${details.resume_document_id}`
          : ""}
        {details?.cover_letter_document_id
          ? ` and cover letter #${details.cover_letter_document_id}`
          : ""}
        .
      </p>
    );
  return <p>{event.note}</p>;
}

export function ApplicationDetail({ id }: { id: number }) {
  const { navigate } = useWorkspace();
  const application = useResource<Application>(`/applications/${id}`);
  const [offset, setOffset] = useState(0);
  const events = useResource<Page<ApplicationEvent>>(
    `/applications/${id}/events?limit=20&offset=${offset}`,
  );
  if (application.loading) return <Loading text="Opening application…" />;
  if (!application.data)
    return (
      <ErrorMessage error={application.error} retry={application.reload} />
    );
  const a = application.data;
  return (
    <>
      <PageHeader
        back={{ to: "/applications", label: "All applications" }}
        eyebrow={a.company}
        title={a.role}
        description={`Applied ${dateLabel(a.applied_on)} · ${a.origin === "jab" ? "Prepared in Jab" : "Prepared elsewhere"}`}
      >
        <Badge value={a.stage} />
        <ExternalLink href={safeUrl(a.application_url)}>
          Application link
        </ExternalLink>
        {!a.deleted_at && <DeleteButton kind="application" id={id}
          name={`${a.role} at ${a.company}`} onDeleted={() => navigate("/applications")} />}
      </PageHeader>
      {a.deleted_at && <Notice>Deleted application. This history and its submitted documents are retained and read-only.</Notice>}
      <ErrorMessage error={application.error} retry={application.reload} />
      <div className="application-layout">
        <div className="form-stack">
          <section className="panel">
            <div className="panel-bar">
              <h2>History</h2>
              <Clock />
            </div>
            {!a.deleted_at && <AddNote id={id} />}
            <ErrorMessage error={events.error} retry={events.reload} />
            <ol className="timeline">
              {events.data?.items.map((event) => (
                <li key={event.id}>
                  <div className="timeline-dot" />
                  <div className="timeline-meta">
                    <strong>
                      {
                        {
                          submission_recorded: "Application recorded",
                          stage_changed: "Stage updated",
                          note_added: "Note added",
                          next_action_changed: "Next action updated",
                          submission_corrected: "Submission corrected",
                          details_corrected: "Details corrected",
                        }[event.kind]
                      }
                    </strong>
                    <time dateTime={event.occurred_at}>
                      {dateLabel(event.occurred_at)}
                    </time>
                  </div>
                  <div className="timeline-content">
                    <EventContent event={event} />
                  </div>
                </li>
              ))}
            </ol>
            {events.loading && <Loading text="Loading history…" />}
            {events.data && (
              <div className="pad">
                <Pagination
                  total={events.data.total}
                  offset={offset}
                  onChange={setOffset}
                />
              </div>
            )}
          </section>
          {!a.deleted_at && <CorrectionForm
            key={`correction-${a.id}-${a.company}-${a.role}-${a.applied_on}-${a.resume_document_id}-${a.cover_letter_document_id}`}
            application={a}
          />}
        </div>
        <aside className="form-stack">
          {!a.deleted_at && <StageEditor key={`stage-${a.id}-${a.stage}`} application={a} />}
          {!a.deleted_at && <FollowUpEditor
            key={`followup-${a.id}-${a.next_action}-${a.next_action_due_on}`}
            application={a}
          />}
          <section className="panel pad submitted-documents">
            <h2>Submitted documents</h2>
            {a.resume_document_id ? (
              <a
                href={pdfUrl(a.resume_document_id, true)}
                className="document-download"
              >
                <FileText />
                <div>
                  <strong>Résumé</strong>
                  <small>Saved document #{a.resume_document_id}</small>
                </div>
                <DownloadSimple />
              </a>
            ) : (
              <p className="muted">No résumé linked.</p>
            )}
            {a.cover_letter_document_id && (
              <a
                href={pdfUrl(a.cover_letter_document_id, true)}
                className="document-download"
              >
                <FileText />
                <div>
                  <strong>Cover letter</strong>
                  <small>Saved document #{a.cover_letter_document_id}</small>
                </div>
                <DownloadSimple />
              </a>
            )}
            {a.job_id && (
              <Link to={`/jobs/${a.job_id}`} className="text-link">
                Open job workspace <ArrowUpRight />
              </Link>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
