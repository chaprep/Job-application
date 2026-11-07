import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Briefcase,
  Check,
  FileText,
  LinkSimple,
  MagnifyingGlass,
  Plus,
  Sparkle,
} from "@phosphor-icons/react";
import { activeTask, dateLabel, post, safeUrl } from "./api";
import { useAction, useDirty, useResource, useWorkspace } from "./state";
import {
  Badge,
  Button,
  DeleteButton,
  Empty,
  ErrorMessage,
  ExternalLink,
  Field,
  Findings,
  Link,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  Select,
  Stepper,
  TaskStatus,
  Textarea,
} from "./ui";
import { JobDocuments } from "./JobDocuments";
import { RecordApplication } from "./ApplicationsPage";
import type {
  Accepted,
  Application,
  Job,
  Page,
  Readiness,
  Requirements,
  Resume,
  Run,
} from "./types";

export function JobsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const jobs = useResource<Page<Job>>(
    `/jobs?limit=20&offset=${offset}&search=${encodeURIComponent(search)}${status ? `&status=${status}` : ""}`,
    4000,
  );
  const active = useResource<Resume | null>("/resumes/active");
  return (
    <>
      <PageHeader title={`Jobs${jobs.data ? ` (${jobs.data.total})` : ""}`}>
        <Link to="/jobs/new" className="btn primary">
          <Plus />
          Add a job
        </Link>
      </PageHeader>
      {active.data === null && (
        <div className="setup-banner">
          <div className="file-symbol">
            <FileText />
          </div>
          <div>
            <strong>Upload a base résumé to prepare documents.</strong>
          </div>
          <Link to="/resume" className="btn">
            Set up résumé <ArrowRight />
          </Link>
        </div>
      )}
      <div className="toolbar">
        <label className="search-field">
          <MagnifyingGlass />
          <span className="sr-only">Search jobs</span>
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
          label="Job status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All jobs</option>
          <option value="needs_review">Needs review</option>
          <option value="ready">Ready to prepare</option>
          <option value="archived">Archived</option>
        </Select>
      </div>
      <ErrorMessage error={jobs.error} retry={jobs.reload} />
      {jobs.loading ? (
        <Loading />
      ) : (
        jobs.data &&
        (jobs.data.items.length ? (
          <>
            <div className="job-grid">
              {jobs.data.items.map((job, i) => (
                <article key={job.id} className="job-card">
                  <Link to={`/jobs/${job.id}`} className="job-card-link">
                    <div className="job-card-top">
                      <div className={`company-mark mark-${i % 4}`}>
                        {(job.company || "?").slice(0, 2).toUpperCase()}
                      </div>
                      <Badge value={job.status} />
                    </div>
                    <p className="company-name">
                      {job.company || "Company to review"}
                    </p>
                    <h3>{job.title || "New job description"}</h3>
                    <p className="job-location">
                      {job.location || "Location not specified"}
                      {job.employment_type ? ` · ${job.employment_type}` : ""}
                    </p>
                    <div className="job-card-bottom">
                      <span>Added {dateLabel(job.created_at)}</span>
                      <ArrowUpRight />
                    </div>
                  </Link>
                  <DeleteButton kind="job" id={job.id}
                    name={`${job.title || "New job description"}${job.company ? ` at ${job.company}` : ""}`}
                    onDeleted={() => setOffset(0)} />
                </article>
              ))}
            </div>
            <Pagination
              total={jobs.data.total}
              offset={offset}
              onChange={setOffset}
            />
          </>
        ) : (
          <div className="panel">
            <Empty
              icon={<Briefcase weight="light" />}
              title={
                search || status
                  ? "No matching jobs"
                  : "No jobs saved"
              }
              action={
                <Link to="/jobs/new" className="btn primary">
                  {search || status ? "Add a job" : "Add a job"}
                  <ArrowRight />
                </Link>
              }
            >
              {search || status
                ? "Try another company, role, or status."
                : "Add a job link or description to prepare documents."}
            </Empty>
          </div>
        ))
      )}
    </>
  );
}

export function NewJobPage() {
  const [mode, setMode] = useState<"url" | "pasted">("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const action = useAction();
  const setDirty = useDirty();
  const { navigate } = useWorkspace();
  return (
    <>
      <PageHeader
        back={{ to: "/jobs", label: "All jobs" }}
        title="Add a job"
      />
      <div className="intake-layout">
        <section className="panel intake-panel">
          <div className="segmented" role="group" aria-label="Job source">
            <Button
              className={mode === "url" ? "selected" : ""}
              onClick={() => setMode("url")}
            >
              <LinkSimple />
              Job link
            </Button>
            <Button
              className={mode === "pasted" ? "selected" : ""}
              onClick={() => setMode("pasted")}
            >
              <FileText />
              Paste description
            </Button>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action.run(async () => {
                const result = await post<Accepted>("/jobs", {
                  source_type: mode,
                  ...(mode === "url"
                    ? { source_url: url.trim() }
                    : {
                        jd_text: text.trim(),
                        ...(url.trim() ? { source_url: url.trim() } : {}),
                      }),
                });
                setDirty(false);
                navigate(`/jobs/${result.job_id}`);
              }, "Job saved. Its details will appear for review.");
            }}
          >
            <fieldset disabled={action.busy}>
              {mode === "url" ? (
                <Field
                  label="Job posting URL"
                  type="url"
                  required
                  placeholder="https://company.com/careers/job"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    setDirty(true);
                  }}
                  hint="Use the direct public job posting. If the page blocks access, you can paste the description instead."
                />
              ) : (
                <Textarea
                  label="Full job description"
                  required
                  rows={15}
                  placeholder="Paste the complete description, including the company, role, responsibilities, and requirements…"
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setDirty(true);
                  }}
                />
              )}
              <ErrorMessage error={action.error} />
              <div className="form-end">
                <Button type="submit" tone="primary" busy={action.busy}>
                  Add job <ArrowRight />
                </Button>
              </div>
            </fieldset>
          </form>
        </section>
      </div>
    </>
  );
}

function JobFieldsForm({ job, busy }: { job: Job; busy: boolean }) {
  const [draft, setDraft] = useState(job);
  const setDirty = useDirty();
  const { dirty, navigate } = useWorkspace();
  const action = useAction();
  const update = (key: keyof Job, value: unknown) => {
    setDraft((old) => ({ ...old, [key]: value }));
    setDirty(true);
  };
  const save = (confirm: boolean) =>
    void action.run(
      async () => {
        if (
          confirm &&
          (!draft.company?.trim() ||
            !draft.title?.trim() ||
            !draft.jd_text?.trim())
        )
          throw new Error(
            "Add the company, role title, and full job description before saving.",
          );
        const keys = [
          "company",
          "title",
          "location",
          "source_url",
          "jd_text",
          "expected_salary",
          "advertised_salary",
          "employment_type",
          "application_deadline",
          "recruiter_details",
          "job_reference",
          "tailoring_instructions",
          "requirements",
        ] as const;
        if (dirty || job.status === "archived")
          await post(
            `/jobs/${job.id}`,
            Object.fromEntries(keys.map((k) => [k, draft[k] || null])),
            "PATCH",
          );
        if (confirm) await post(`/jobs/${job.id}/confirm`);
        setDirty(false);
        if (confirm) navigate(`/jobs/${job.id}/documents`);
      },
      confirm
        ? "Job details confirmed. Ready to prepare."
        : "Job details saved.",
    );
  return (
    <section className="panel">
      <div className="panel-bar">
        <div>
          <h2>Job details</h2>
        </div>
        <Badge value={job.status} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(true);
        }}
      >
        <fieldset disabled={busy || action.busy} className="pad form-stack">
          <div className="form-grid">
            <Field
              label="Company"
              required
              value={draft.company || ""}
              onChange={(e) => update("company", e.target.value)}
            />
            <Field
              label="Role title"
              required
              value={draft.title || ""}
              onChange={(e) => update("title", e.target.value)}
            />
            <Field
              label="Location"
              value={draft.location || ""}
              onChange={(e) => update("location", e.target.value)}
            />
            <Field
              label="Employment type"
              value={draft.employment_type || ""}
              placeholder="Full-time, contract…"
              onChange={(e) => update("employment_type", e.target.value)}
            />
            <Field
              label="Job URL"
              wide
              value={draft.source_url || ""}
              onChange={(e) => update("source_url", e.target.value)}
            />
          </div>
          <Textarea
            label="Full job description"
            required
            rows={12}
            value={draft.jd_text || ""}
            onChange={(e) => update("jd_text", e.target.value)}
            hint="This is the description used for tailoring. Keep responsibilities and requirements intact."
          />
          <details className="optional-details">
            <summary>Salary, recruiter, and other details</summary>
            <div className="form-grid">
              <Field
                label="Advertised salary"
                value={draft.advertised_salary || ""}
                onChange={(e) => update("advertised_salary", e.target.value)}
              />
              <Field
                label="Your expected salary"
                hint="Your preference. Jab does not infer this."
                value={draft.expected_salary || ""}
                onChange={(e) => update("expected_salary", e.target.value)}
              />
              <Field
                label="Application deadline"
                hint="Keep the deadline wording as advertised."
                value={draft.application_deadline || ""}
                onChange={(e) =>
                  update("application_deadline", e.target.value || null)
                }
              />
              <Field
                label="Job reference"
                value={draft.job_reference || ""}
                onChange={(e) => update("job_reference", e.target.value)}
              />
              <Field
                label="Recruiter details"
                wide
                value={draft.recruiter_details || ""}
                onChange={(e) => update("recruiter_details", e.target.value)}
              />
            </div>
          </details>
          <details className="optional-details">
            <summary>Extracted responsibilities and requirements</summary>
            {(["responsibilities", "required", "preferred"] as const).map(
              (key) => (
                <Textarea
                  key={key}
                  label={
                    {
                      responsibilities: "Responsibilities",
                      required: "Required qualifications",
                      preferred: "Preferred qualifications",
                    }[key]
                  }
                  hint="One item per line."
                  value={draft.requirements?.[key]?.join("\n") || ""}
                  onChange={(e) =>
                    update("requirements", {
                      responsibilities: [],
                      required: [],
                      preferred: [],
                      ...draft.requirements,
                      [key]: e.target.value.split("\n"),
                    } as Requirements)
                  }
                />
              ),
            )}
          </details>
          <Textarea
            label="Tailoring instructions"
            rows={3}
            placeholder="For example: emphasise my automation projects and customer-facing experience."
            value={draft.tailoring_instructions || ""}
            onChange={(e) => update("tailoring_instructions", e.target.value)}
          />
          <ErrorMessage error={action.error} />
          <div className="form-end">
            <Button busy={action.busy} onClick={() => save(false)}>
              Save details
            </Button>
            <Button type="submit" tone="primary" busy={action.busy}>
              <Check />
              Confirm job details
            </Button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

function IntakeRecovery({ job }: { job: Job }) {
  const [text, setText] = useState("");
  const setDirty = useDirty();
  const action = useAction();
  const { dirty } = useWorkspace();
  const capture = (input: unknown) => {
    if (
      dirty &&
      !window.confirm(
        "Capture this job again? This replaces extracted job details. Save any manual edits you want to keep first.",
      )
    )
      return;
    void action.run(async () => {
      await post(`/jobs/${job.id}/intake`, input);
      setDirty(false);
      setText("");
    }, "Job extraction queued.");
  };
  return (
    <details className="panel intake-recovery">
      <summary>
        <LinkSimple />
        Retry capture or paste a description
      </summary>
      <div className="form-stack pad">
        <p className="muted">
          Blocked pages happen. Paste the full JD to extract the details again,
          or fill in the form yourself.
        </p>
        <Textarea
          label="Replacement job description"
          rows={7}
          value={text}
          disabled={action.busy}
          onChange={(e) => {
            setText(e.target.value);
            setDirty(true);
          }}
        />
        <div className="row">
          <Button
            tone="primary"
            disabled={!text.trim()}
            busy={action.busy}
            onClick={() =>
              capture({
                source_type: "pasted",
                jd_text: text,
                source_url: job.source_url,
              })
            }
          >
            <Sparkle />
            Extract pasted JD
          </Button>
          {job.source_url && (
            <Button
              busy={action.busy}
              onClick={() =>
                capture({
                  source_type: "url",
                  source_url: job.source_url,
                })
              }
            >
              Retry URL
            </Button>
          )}
        </div>
        <ErrorMessage error={action.error} />
      </div>
    </details>
  );
}

export function JobDetail({
  id,
  tab = "details",
}: {
  id: number;
  tab?: string;
}) {
  const job = useResource<Job>(`/jobs/${id}`, 2500);
  const [runOffset, setRunOffset] = useState(0);
  const runs = useResource<Page<Run>>(
    `/jobs/${id}/runs?limit=20&offset=${runOffset}`,
    2500,
  );
  const applications = useResource<Page<Application>>(
    `/applications?job_id=${id}&limit=100`,
    4000,
  );
  const readiness = useResource<Readiness>("/readiness");
  const active = useResource<Resume | null>("/resumes/active");
  const action = useAction();
  const { dirty, navigate } = useWorkspace();
  const [selectedRun, setSelectedRun] = useState<number>();
  const [instructions, setInstructions] = useState("");
  useEffect(() => {
    setSelectedRun(undefined);
    setRunOffset(0);
  }, [id]);
  const chosenRun = selectedRun || runs.data?.items[0]?.id;
  const run = useResource<Run>(chosenRun ? `/runs/${chosenRun}` : null, 2000);
  const working =
    activeTask(job.data?.active_tasks) ||
    activeTask(job.data?.tasks) ||
    runs.data?.items.some((r) => ["queued", "running"].includes(r.status)) ||
    activeTask(run.data?.tasks);
  const existing =
    applications.data?.items.filter((a) => a.job_id === id) || [];
  if (job.loading) return <Loading text="Opening job…" />;
  if (!job.data) return <ErrorMessage error={job.error} retry={job.reload} />;
  const j = job.data;
  if (j.deleted_at) return (
    <>
      <PageHeader back={{ to: "/jobs", label: "All jobs" }}
        eyebrow={j.company || "Job workspace"} title={j.title || "Job"} />
      <Notice>Deleted job. These retained details are read-only. Linked applications and documents remain available from Applications.</Notice>
      <section className="panel pad"><h2>Job description</h2><p className="preserved-text">{j.jd_text || "No description captured."}</p></section>
    </>
  );
  const current = existing.length
    ? 3
    : run.data?.documents?.length
      ? 2
      : j.status === "ready"
        ? 1
        : 0;
  return (
    <>
      <PageHeader
        back={{ to: "/jobs", label: "All jobs" }}
        eyebrow={j.company || "Job workspace"}
        title={j.title || "Job details"}
        description={[j.location, j.employment_type]
          .filter(Boolean)
          .join(" · ")}
      >
        <ExternalLink href={safeUrl(j.source_url)}>
          Original posting
        </ExternalLink>
        <Badge value={j.status} />
        <DeleteButton kind="job" id={id}
          name={`${j.title || "New job description"}${j.company ? ` at ${j.company}` : ""}`}
          disabled={working} onDeleted={() => navigate("/jobs")} />
      </PageHeader>
      <Stepper current={current} />
      <div className="tabs" role="navigation" aria-label="Job workspace">
        <Link
          to={`/jobs/${id}`}
          className={tab === "details" ? "selected" : ""}
        >
          Job details
        </Link>
        <Link
          to={`/jobs/${id}/documents`}
          className={tab === "documents" ? "selected" : ""}
        >
          Documents{" "}
          {runs.data?.total ? (
            <span className="count">{runs.data.total}</span>
          ) : null}
        </Link>
        <Link
          to={`/jobs/${id}/application`}
          className={tab === "application" ? "selected" : ""}
        >
          Record application {existing.length ? <Check /> : null}
        </Link>
      </div>
      <ErrorMessage error={job.error} retry={job.reload} />
      <TaskStatus tasks={j.tasks} />
      <TaskStatus tasks={run.data?.tasks} />
      {j.duplicate_job_ids?.length ? (
        <Notice>
          This may be a job you’ve already saved.{" "}
          {j.duplicate_job_ids.map((other) => (
            <Link key={other} to={`/jobs/${other}`} className="text-link">
              View job #{other} <ArrowUpRight />
            </Link>
          ))}
        </Notice>
      ) : null}
      {tab === "details" ? (
        <div className="job-details-layout">
          <div className="form-stack">
            <Findings
              findings={
                j.tasks?.find((t) => t.result?.findings)?.result?.findings
              }
            />
            <JobFieldsForm
              key={`${id}-${j.tasks?.[0]?.id}-${activeTask(j.tasks)}`}
              job={j}
              busy={working}
            />
            {!working && <IntakeRecovery job={j} />}
          </div>
          <aside className="job-aside">
            <span className="eyebrow">Base résumé</span>
            <strong>
              {active.data?.original_filename || "No active résumé"}
            </strong>
            <Link to="/resume" className="text-link">
              {active.data ? "Review base résumé" : "Set up your résumé"}
              <ArrowRight />
            </Link>
            {j.status !== "archived" && (
              <Button
                tone="quiet"
                disabled={working}
                busy={action.busy}
                onClick={() =>
                  void action.run(async () => {
                    await post(`/jobs/${id}/archive`);
                  }, "Job archived. You can restore it by confirming its details.")
                }
              >
                Archive job
              </Button>
            )}
            <ErrorMessage error={action.error} />
          </aside>
        </div>
      ) : tab === "documents" ? (
        <>
          <div className="prepare-bar">
            <Button
              tone="primary"
              busy={action.busy || working}
              disabled={
                j.status !== "ready" ||
                !active.data ||
                dirty ||
                readiness.data?.ai_configured !== true
              }
              onClick={() =>
                void action.run(async () => {
                  const result = await post<Accepted>(`/jobs/${id}/runs`, {
                    instructions: instructions.trim() || null,
                  });
                  setSelectedRun(result.run_id);
                  setRunOffset(0);
                }, "Preparation started.")
              }
            >
              <Sparkle />
              {runs.data?.total ? "Prepare new versions" : "Prepare documents"}
            </Button>
          </div>
          {j.status !== "ready" && (
            <Notice>
              <Link to={`/jobs/${id}`} className="text-link">
                Confirm the job details <ArrowRight />
              </Link>{" "}
              before preparing documents.
            </Notice>
          )}
          {active.data === null && (
            <Notice>
              <Link to="/resume" className="text-link">
                Activate a base résumé <ArrowRight />
              </Link>{" "}
              to start tailoring.
            </Notice>
          )}
          {readiness.data && !readiness.data.ai_configured && (
            <Notice>
              Connect an AI provider in Jab’s local configuration, then restart.
              Your saved jobs and applications remain available.
            </Notice>
          )}
          {readiness.data && !readiness.data.renderer && (
            <Notice>
              The PDF renderer needs attention. Check that LuaLaTeX, Inter, and
              Poppler are installed.
            </Notice>
          )}
          <details className="run-instructions">
            <summary>Instructions for the next preparation</summary>
            <Textarea
              label="What should this preparation focus on?"
              value={instructions}
              maxLength={10000}
              onChange={(e) => setInstructions(e.target.value)}
            />
          </details>
          <ErrorMessage error={action.error} />
          <ErrorMessage error={runs.error} retry={runs.reload} />
          <JobDocuments key={id} run={run.data} job={j} onNewRun={setSelectedRun} />
          {!!runs.data?.total && (
            <details className="run-instructions">
              <summary>Generation activity</summary>
              <Select label="Generation attempt" value={chosenRun || ""}
                onChange={(e) => setSelectedRun(Number(e.target.value))}>
                {runs.data.items.map((r) => (
                  <option key={r.id} value={r.id}>
                    Attempt #{r.id} · {dateLabel(r.created_at)} · {r.status}
                  </option>
                ))}
              </Select>
              <Pagination total={runs.data.total} offset={runOffset}
                onChange={(offset) => { setSelectedRun(undefined); setRunOffset(offset); }} />
              <ErrorMessage error={run.error} retry={run.reload} />
              <p className="muted">Generation activity records individual attempts. Document versions are selected above.</p>
            </details>
          )}
        </>
      ) : (
        <>
          {existing.map((a) => (
            <Notice key={a.id} kind="success" icon={<Check />}>
              Application recorded on {dateLabel(a.applied_on)}.{" "}
              <Link to={`/applications/${a.id}`} className="text-link">
                View application <ArrowRight />
              </Link>
            </Notice>
          ))}
          <RecordApplication key={id} job={j} />
        </>
      )}
    </>
  );
}
