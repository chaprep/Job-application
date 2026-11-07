import {
  Component,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Briefcase,
  Check,
  CheckCircle,
  FileText,
  GearSix,
  HouseSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { Workspace, useResource } from "./state";
import { Link, Button, Empty, Notice, PageHeader } from "./ui";
import { ResumePage } from "./ResumePage";
import { JobDetail, JobsPage, NewJobPage } from "./JobsPage";
import {
  ApplicationDetail,
  ApplicationsPage,
  RecordApplication,
} from "./ApplicationsPage";
import type { Readiness, Resume } from "./types";

class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="panel">
        <Empty
          icon={<WarningCircle />}
          title="Unable to load this view"
          action={
            <Button onClick={() => window.location.reload()}>Reload Jab</Button>
          }
        >
          Your saved work is still on your computer. Reload this page to try
          again.
        </Empty>
      </div>
    ) : (
      this.props.children
    );
  }
}

function SetupPage() {
  const ready = useResource<Readiness>("/readiness");
  return (
    <>
      <PageHeader title="Workspace status" />
      <div className="settings-grid">
        {[
          [
            "Database",
            ready.data?.database,
            "Your résumés, jobs, documents, and application history.",
          ],
          [
            "PDF renderer",
            ready.data?.renderer,
            "LuaLaTeX, Inter, and Poppler build and check your PDFs.",
          ],
          [
            "AI provider",
            ready.data?.ai_configured,
            ready.data?.model ||
              "Configure the provider and model you want to use.",
          ],
        ].map(([title, value, text]) => (
          <section className="panel pad" key={String(title)}>
            <div className="section-row">
              <h2>{title}</h2>
              {value ? (
                <CheckCircle className="status-good" />
              ) : (
                <WarningCircle />
              )}
            </div>
            <p>{text}</p>
            <span className={`status-text ${value ? "status-good" : ""}`}>
              {ready.loading
                ? "Checking…"
                : value
                  ? "Configured"
                  : "Needs attention"}
            </span>
          </section>
        ))}
      </div>
      {ready.error && <Notice kind="error">{ready.error.message}</Notice>}
      <details className="panel pad setup-instructions">
        <summary>AI provider setup</summary>
        <p>
          Open <code>Jab/.env</code> on your computer, using{" "}
          <code>.env.example</code> as a starting point. Set these values, then
          restart Jab:
        </p>
        <pre>
          <code>
            {
              "JAB_AI_BASE_URL=https://your-provider.example/v1\nJAB_AI_MODEL=your-model-id\nJAB_AI_API_KEY=your-api-key"
            }
          </code>
        </pre>
        <p>
          Use a provider with an OpenAI-compatible Chat Completions endpoint.
          Your key stays on the backend. Résumé and job text needed for
          generation is sent to that provider.
        </p>
        <small>
          “Configured” checks that settings are present; it does not make a
          model request or verify credentials.
        </small>
      </details>
      <details className="panel pad setup-instructions">
        <summary>Available without AI</summary>
        <p>
          You can review saved content, complete job details manually, download
          ready documents, and track applications. Résumé organisation, job
          extraction and document writing use AI. You review the generated documents.
        </p>
      </details>
    </>
  );
}

function Content({ path }: { path: string }) {
  const parts = path.split("/").filter(Boolean);
  const id = Number(parts[1]);
  const validId = Number.isSafeInteger(id) && id > 0;
  if (parts[0] === "resume" && (!parts[1] || validId))
    return (
      <ResumePage
        key={parts[1] || "base"}
        selectedId={validId ? id : undefined}
      />
    );
  if (parts[0] === "jobs") {
    if (parts[1] === "new") return <NewJobPage />;
    if (
      validId &&
      (!parts[2] || ["details", "documents", "application"].includes(parts[2]))
    )
      return <JobDetail key={id} id={id} tab={parts[2] || "details"} />;
    if (!parts[1]) return <JobsPage />;
  }
  if (parts[0] === "applications") {
    if (parts[1] === "new")
      return (
        <>
          <PageHeader
            back={{ to: "/applications", label: "All applications" }}
            title="Record application"
          />
          <RecordApplication />
        </>
      );
    if (validId && parts.length === 2)
      return <ApplicationDetail key={id} id={id} />;
    if (!parts[1]) return <ApplicationsPage />;
  }
  if (parts[0] === "setup") return <SetupPage />;
  return (
    <Empty
      icon={<HouseSimple />}
      title="Page not found"
      action={
        <Link to="/jobs" className="btn primary">
          Back to jobs <ArrowRight />
        </Link>
      }
    >
      The requested page does not exist.
    </Empty>
  );
}

function Shell({
  path,
  toast,
  dismiss,
}: {
  path: string;
  toast: string;
  dismiss: () => void;
}) {
  const active = useResource<Resume | null>("/resumes/active", 10000);
  const ready = useResource<Readiness>("/readiness", 15000);
  const current = path.split("/")[1];
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    document.title = `Jab · ${{ resume: "Base résumé", jobs: "Jobs", applications: "Applications", setup: "Workspace status" }[current] || "Workspace"}`;
  }, [path, current]);
  const name = active.data?.reviewed_content?.contact.name;
  return (
    <>
      <a
        href="#main-content"
        className="skip-link"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to content
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <Link to="/jobs" className="brand">
            <span className="brand-symbol">
              <ArrowUpRight weight="bold" />
            </span>
            <span>
              jab<span className="brand-dot">.</span>
            </span>
          </Link>
          <div className="sidebar-label eyebrow">Your workspace</div>
          <nav className="main-nav" aria-label="Main navigation">
            {[
              { key: "resume", title: "Base résumé", icon: <FileText /> },
              { key: "jobs", title: "Jobs", icon: <Briefcase /> },
              {
                key: "applications",
                title: "Applications",
                icon: <CheckCircle />,
              },
            ].map((item) => (
              <Link
                key={item.key}
                to={`/${item.key}`}
                className={current === item.key ? "active" : ""}
                aria-current={current === item.key ? "page" : undefined}
              >
                {item.icon}
                <span>{item.title}</span>
              </Link>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <Link to="/setup" className="system-link">
              <span
                className={`connection-dot ${ready.error ? "offline" : ""}`}
              />
              <span>
                {ready.error ? "Server unavailable" : "Running locally"}
              </span>
              <GearSix />
            </Link>
            <div className="profile">
              <div className="avatar">
                {name
                  ? name
                      .split(" ")
                      .filter(Boolean)
                      .slice(0, 2)
                      .map((s) => s[0])
                      .join("")
                  : "J"}
              </div>
              <div>
                <strong>{name || "Personal workspace"}</strong>
              </div>
            </div>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <span>
              Workspace <span className="breadcrumb-slash">/</span>{" "}
              <strong>
                {{
                  resume: "Base résumé",
                  jobs: "Jobs",
                  applications: "Applications",
                  setup: "Status",
                }[current] || "Jab"}
              </strong>
            </span>
            <div className="topbar-right">
              <span className="today-date">
                {new Date().toLocaleDateString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                })}
              </span>
              <Link to="/setup" className="local-badge"
                aria-current={current === "setup" ? "page" : undefined}>
                <GearSix aria-hidden="true" />
                {ready.error ? "Connection status" : "Local workspace"}
              </Link>
            </div>
          </header>
          <main id="main-content" ref={main} tabIndex={-1}>
            <ErrorBoundary key={path}>
              <Content path={path} />
            </ErrorBoundary>
          </main>
          <footer className="workspace-footer">
            <Link to="/setup">
              {ready.error
                ? "Check server connection"
                : ready.data?.ai_configured
                  ? "Workspace status"
                  : "AI setup needed"}{" "}
              <ArrowUpRight />
            </Link>
          </footer>
        </div>
      </div>
      <div className="toast-region" aria-live="polite">
        {toast && (
          <div className="toast">
            <Check />
            <span>{toast}</span>
            <button aria-label="Dismiss notification" onClick={dismiss}>
              <X />
            </button>
          </div>
        )}
      </div>
    </>
  );
}

export default function App() {
  const [path, setPath] = useState(
    () => window.location.hash.slice(1) || "/jobs",
  );
  const [revision, setRevision] = useState(0);
  const [dirty, updateDirty] = useState(false);
  const dirtyOwners = useRef(new Set<symbol>());
  const pathRef = useRef(path);
  const [toast, setToast] = useState("");
  const markDirty = useCallback((owner: symbol, value: boolean) => {
    if (value) dirtyOwners.current.add(owner);
    else dirtyOwners.current.delete(owner);
    updateDirty(dirtyOwners.current.size > 0);
  }, []);
  const setDirty = useCallback((value: boolean) => {
    if (!value) dirtyOwners.current.clear();
    updateDirty(value);
  }, []);
  const refresh = useCallback(() => setRevision((v) => v + 1), []);
  const notify = useCallback((message: string) => setToast(message), []);
  const navigate = useCallback(
    (next: string) => {
      if (next === pathRef.current) return;
      if (
        dirtyOwners.current.size &&
        !window.confirm(
          "Leave these unsaved edits? Your saved work is preserved.",
        )
      )
        return;
      setDirty(false);
      window.location.hash = next;
    },
    [setDirty],
  );
  useEffect(() => {
    const handleHash = () => {
      const next = window.location.hash.slice(1) || "/jobs";
      if (
        next !== pathRef.current &&
        dirtyOwners.current.size &&
        !window.confirm(
          "Leave these unsaved edits? Your saved work is preserved.",
        )
      ) {
        window.history.replaceState(null, "", `#${pathRef.current}`);
        return;
      }
      setDirty(false);
      pathRef.current = next;
      setPath(next);
    };
    const handleUnload = (e: BeforeUnloadEvent) => {
      if (dirtyOwners.current.size) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("hashchange", handleHash);
    window.addEventListener("beforeunload", handleUnload);
    return () => {
      window.removeEventListener("hashchange", handleHash);
      window.removeEventListener("beforeunload", handleUnload);
    };
  }, [setDirty]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6000);
    return () => clearTimeout(timer);
  }, [toast]);
  return (
    <Workspace.Provider
      value={{
        revision,
        refresh,
        navigate,
        dirty,
        setDirty,
        markDirty,
        notify,
      }}
    >
      <Shell path={path} toast={toast} dismiss={() => setToast("")} />
    </Workspace.Provider>
  );
}
