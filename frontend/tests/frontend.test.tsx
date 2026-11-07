import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { api, ApiError, post, pdfUrl, safeUrl, activeTask } from "../src/api";
import { ContentEditor, emptyResume, sourceClaims } from "../src/ContentEditor";
import { DocumentEditor, DocumentVersionPicker, JobDocuments } from "../src/JobDocuments";
import { RecordApplication } from "../src/ApplicationsPage";
import { DeleteButton, DeleteConfirmation, ErrorMessage } from "../src/ui";
import { LinkOverrideNotice } from "../src/ResumePage";
import { LinkedTextEditor } from "../src/LinkedTextEditor";
import { cpOffset, cpSlice, remapLinks, sourceLinks } from "../src/links";
import type { Claim, CoverLetter, Document, Job, Run } from "../src/types";
import type { LinkSpan } from "../src/types";

const claim = (id: string, text: string): Claim => ({
  id,
  text,
  source_refs: [id],
  emphasis: [],
});

test("delete controls identify their target and disable while job work is active", () => {
  const job = renderToStaticMarkup(<DeleteButton kind="job" id={1} name="Engineer at Example" disabled />);
  assert.match(job, /Delete job: Engineer at Example/);
  assert.match(job, /disabled=""/);
  const application = renderToStaticMarkup(<DeleteButton kind="application" id={2} name="Developer at Example" />);
  assert.match(application, /Delete application: Developer at Example/);
  assert.doesNotMatch(application, /disabled=""/);
});

test("delete confirmation names its target, explains retained data and keeps failures visible", () => {
  const html = renderToStaticMarkup(
    <DeleteConfirmation kind="application" name="Engineer <Example>" dirty busy
      error={new Error("Server unavailable")} onCancel={() => {}} onConfirm={() => {}} />,
  );
  assert.match(html, /<dialog/);
  assert.match(html, /role="alertdialog"/);
  assert.match(html, /aria-labelledby="[^"]+"/);
  assert.match(html, /aria-describedby="[^"]+"/);
  assert.match(html, /Engineer &lt;Example&gt;/);
  assert.match(html, /linked job and submitted documents will remain available/);
  assert.match(html, /Unsaved edits will be discarded/);
  assert.match(html, /Server unavailable/);
  assert.match(html, /Deleting…/);
  assert.equal((html.match(/disabled=""/g) || []).length, 2);
});
const content = emptyResume();
content.contact.name = "Asha Example";
content.contact.email = "asha@example.com";
content.summary = [
  claim("private_source_summary", "Builds <useful> software & tools."),
];
content.experience = [
  {
    id: "work",
    title: "Engineer",
    organization: "Example",
    dates: "2024–Present",
    location: "Bengaluru",
    link: "",
    description: [],
    bullets: [claim("private_work", "Saved 30 hours monthly.")],
    children: [
      {
        id: "nested",
        title: "Earlier role",
        organization: "",
        dates: "",
        location: "",
        link: "",
        description: [claim("private_nested", "Worked with customers.")],
        bullets: [],
        children: [],
      },
    ],
  },
];
content.additional_sections = [
  {
    title: "Volunteering",
    entries: [
      {
        ...content.experience[0],
        id: "volunteer",
        children: [],
        bullets: [claim("private_volunteer", "Helped run an event.")],
      },
    ],
  },
];
const document: Document = {
  id: 42,
  run_id: 7,
  kind: "resume",
  revision: 2,
  content,
  render_status: "ready",
  render_error: null,
  created_at: "2026-11-05",
  validations: [
    {
      id: 1,
      check_type: "facts",
      result: "warnings",
      findings: [
        {
          field: "summary",
          severity: "warning",
          explanation: "Review this wording.",
        },
      ],
    },
  ],
};

test("only public web protocols become external links; PDF URLs retain exact revision IDs", () => {
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,hello",
    "file:///etc/passwd",
    "/relative",
    "not a url",
    undefined,
  ])
    assert.equal(safeUrl(value), undefined);
  assert.equal(
    safeUrl("https://example.com/job?a=1"),
    "https://example.com/job?a=1",
  );
  assert.equal(pdfUrl(42), "/api/v1/documents/42/pdf?download=false");
  assert.equal(pdfUrl(42, true), "/api/v1/documents/42/pdf?download=true");
  assert.equal(
    activeTask([{ status: "succeeded" }, { status: "running" }]),
    true,
  );
  assert.equal(activeTask([{ status: "failed" }]), false);
});

test("request helper sends correct JSON and multipart boundaries and preserves field errors", async () => {
  const original = globalThis.fetch;
  const requests: { path: string; options: RequestInit }[] = [];
  globalThis.fetch = async (input, options = {}) => {
    requests.push({ path: String(input), options });
    return new Response(JSON.stringify({ id: 12 }), { status: 201 });
  };
  try {
    const value = await post<{ id: number }>("/applications", {
      company: "Example",
    });
    assert.equal(value.id, 12);
    assert.equal(requests[0].path, "/api/v1/applications");
    assert.equal(
      new Headers(requests[0].options.headers).get("Content-Type"),
      "application/json",
    );
    assert.deepEqual(JSON.parse(requests[0].options.body as string), {
      company: "Example",
    });
    const form = new FormData();
    form.append("file", new Blob(["test"]), "base.pdf");
    await api("/resumes", { method: "POST", body: form });
    assert.equal(
      new Headers(requests[1].options.headers).has("Content-Type"),
      false,
    );
    assert.equal(requests[1].options.body, form);
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          error: {
            message: "Check your fields.",
            fields: { issues: [{ field: "company", message: "Required" }] },
          },
        }),
        { status: 422 },
      );
    await assert.rejects(
      api("/applications"),
      (error: ApiError) =>
        error instanceof ApiError &&
        error.fields?.issues?.[0].field === "company",
    );
    globalThis.fetch = async () => {
      throw new TypeError("Network failed");
    };
    await assert.rejects(api("/jobs"), /could not reach the local server/);
  } finally {
    globalThis.fetch = original;
  }
});

test("résumé editor exposes nested and additional source facts without printing provenance IDs or unsafe HTML", () => {
  const html = renderToStaticMarkup(
    <ContentEditor value={content} onChange={() => {}} />,
  );
  assert.ok(html.includes("Asha Example"));
  assert.ok(html.includes("Earlier role"));
  assert.ok(html.includes("Volunteering"));
  assert.ok(html.includes("Worked with customers."));
  assert.ok(html.includes("Builds &lt;useful&gt; software &amp; tools."));
  assert.ok(!html.includes("private_source_summary"));
  assert.ok(!html.includes("private_nested"));
  assert.deepEqual(
    sourceClaims(content).map((c) => c.id),
    [
      "private_source_summary",
      "private_work",
      "private_nested",
      "private_volunteer",
    ],
  );
});

test("cover-letter editor preserves content without mandatory factual evidence controls", () => {
  const letter: CoverLetter = {
    schema_version: "1",
    contact: content.contact,
    salutation: "Dear hiring team,",
    paragraphs: [claim("letter", "I build useful software.")],
    closing: "Kind regards,",
    signature: "Asha Example",
  };
  const html = renderToStaticMarkup(
    <ContentEditor value={letter} source={content} onChange={() => {}} />,
  );
  for (const value of [
    "Dear hiring team,",
    "I build useful software.",
    "Kind regards,",
    "Asha Example",
    "250–350",
  ])
    assert.ok(html.includes(value), value);
});

test("document version picker preserves exact IDs, off-page selection, and disabled controls", () => {
  const older = { ...document, id: 43, revision: 2, version_number: 2 };
  const html = renderToStaticMarkup(
    <DocumentVersionPicker kind="resume" documents={[document]} selected={older}
      selectedId={43} disabled={false} onSelect={() => {}} />,
  );
  assert.ok(html.includes("Résumé version"));
  assert.match(html, /type="radio"[^>]*checked=""[^>]*value="43"/);
  assert.match(html, /type="radio"[^>]*value="42"/);
  assert.equal((html.match(/class="version-option"/g) || []).length, 2);
  assert.ok(!html.includes("<select"));
  const disabled = renderToStaticMarkup(
    <DocumentVersionPicker kind="cover_letter" documents={[document]} selected={document}
      selectedId={42} disabled onSelect={() => {}} />,
  );
  assert.ok(disabled.includes("Cover letter version"));
  assert.ok(disabled.includes('aria-disabled="true"'));
  assert.match(disabled, /<fieldset[^>]*disabled=""/);
});

test("document review previews downloads and hides historical factual blockers", () => {
  const render = (doc: Document) =>
    renderToStaticMarkup(
      <DocumentEditor
        doc={doc}
        source={content}
        onSelect={() => {}}
        onNewRun={() => {}}
        jobId={3}
      />,
    );
  const ready = render(document);
  assert.ok(ready.includes("/documents/42/pdf?download=false"));
  assert.ok(ready.includes("/documents/42/pdf?download=true"));
  assert.ok(!ready.includes("Review this wording."));
  assert.ok(ready.includes("Review the wording and facts"));
  assert.ok(!ready.includes("Source facts"));
  assert.ok(ready.includes("Save new revision"));
  assert.ok(ready.includes("Request revision"));
  const failed = render({
    ...document,
    render_status: "failed",
    render_error: "PDF overflow.",
  });
  assert.ok(!failed.includes("/documents/42/pdf?download=true"));
  assert.ok(failed.includes("PDF overflow."));
  assert.ok(failed.includes("Retry PDF creation"));
  const historical = render({
    ...document,
    render_status: "failed",
    render_error: "The saved draft has structural or factual issues. Review findings and save a corrected revision.",
  });
  assert.ok(historical.includes("stopped by earlier review checks"));
  assert.ok(!historical.includes("56 review findings"));
  assert.ok(!historical.includes("Review this wording."));
  assert.ok(historical.includes("Retry PDF creation"));

});

test("Jab submissions require an explicitly selected résumé and submission confirmation; external records do not", () => {
  const job = {
    id: 3,
    company: "Example",
    title: "Engineer",
    source_url: "https://example.com/job",
  } as Job;
  const jab = renderToStaticMarkup(<RecordApplication job={job} />);
  assert.ok(jab.includes("Choose a ready résumé"));
  assert.ok(jab.includes("I’ve submitted this application"));
  assert.match(jab, /<button[^>]*disabled=""[^>]*>.*?Record application/s);
  const external = renderToStaticMarkup(<RecordApplication />);
  assert.ok(external.includes("Company"));
  assert.ok(external.includes("Role"));
  assert.doesNotMatch(external, /<button[^>]*disabled=""[^>]*>.*?Record application/s);
  assert.ok(!external.includes("I’ve submitted this application"));
});

test("a targeted cover-letter revision opens on the letter and partial output errors remain readable", () => {
  const run = {
    id: 8,
    job_id: 3,
    status: "partial",
    documents: [],
    source_snapshot: {
      resume: content,
      source_document: { kind: "cover_letter" },
    },
    review_findings: [{ message: "Résumé could not be prepared." }],
  } as Run;
  const html = renderToStaticMarkup(
    <JobDocuments run={run} job={{ id: 3 } as Job} onNewRun={() => {}} />,
  );
  assert.match(html, /class="[^"]*selected"[^>]*>.*?Cover letter/s);
  assert.ok(html.includes("Generation attempt #8 had an issue."));
  assert.ok(html.includes("selected documents and earlier versions remain available"));
});

test("API validation issues render actionable field details with escaped text", () => {
  const html = renderToStaticMarkup(
    <ErrorMessage
      error={
        new ApiError("Check these fields.", {
          issues: [{ field: "company", message: "<required>" }],
        })
      }
    />,
  );
  assert.ok(html.includes('role="alert"'));
  assert.ok(html.includes("company"));
  assert.ok(html.includes("&lt;required&gt;"));
});
test("resume override appears only for eligible link errors and still requires review confirmation", () => {
  const render = (error?: Error, confirmed = false) =>
    renderToStaticMarkup(
      <LinkOverrideNotice
        error={error}
        confirmed={confirmed}
        busy={false}
        onOverride={() => {}}
      />,
    );
  assert.equal(render(), "");
  assert.equal(
    render(new ApiError("Missing name", { can_override_links: false })),
    "",
  );
  const error = new ApiError("Invalid links", { can_override_links: true });
  assert.match(render(error), /disabled=""/);
  const approved = render(error, true);
  assert.ok(approved.includes("Override and activate as is"));
  assert.ok(approved.includes("plain text in PDFs"));
  assert.ok(!approved.includes('disabled=""'));
});
test("browser UTF-16 selections are converted to Unicode code-point spans", () => {
  const text = "A 😀 CNEX";
  assert.equal(cpOffset(text, 5), 4);
  assert.equal(cpSlice(text, 4, 8), "CNEX");
  const link: LinkSpan = {
    start: 4,
    end: 8,
    url: "https://cnex.studio",
    source_link_id: "cnex",
    unresolved_label: null,
  };
  const moved = remapLinks(text, "Hi " + text, [link])[0];
  assert.deepEqual([moved.start, moved.end], [7, 11]);
  assert.deepEqual(remapLinks(text, text + ".", [link])[0], link);
  assert.deepEqual([link.start, link.end], [4, 8]);
});

test("editing through a linked phrase retains the target for explicit reattachment", () => {
  const link: LinkSpan = {
    start: 0,
    end: 4,
    url: "https://cnex.studio",
    source_link_id: "cnex",
    unresolved_label: null,
  };
  const broken = remapLinks("CNEX and CNEX", "Studio and CNEX", [link])[0];
  assert.equal(broken.start, null);
  assert.equal(broken.end, null);
  assert.equal(broken.unresolved_label, "CNEX");
  assert.equal(broken.url, "https://cnex.studio");
  assert.equal(broken.source_link_id, "cnex");
});

test("link editor displays labels and targets plus recovery controls without active unsafe links", () => {
  const html = renderToStaticMarkup(
    <LinkedTextEditor
      label="Achievement"
      value="Built at CNEX"
      links={[
        {
          start: null,
          end: null,
          url: "javascript:alert(1)",
          source_link_id: "cnex",
          unresolved_label: "CNEX",
        },
      ]}
      onTextChange={() => {}}
      onLinksChange={() => {}}
    />,
  );
  assert.ok(html.includes("Text changed."));
  assert.ok(html.includes("Use selected text"));
  assert.ok(html.includes("javascript:alert(1)"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(html.includes("Remove hyperlink 1 from Achievement"));
});

test("contact links keep separate labels and destinations and unresolved imports remain visible", () => {
  const linked = structuredClone(content);
  linked.contact.links = [
    {
      id: "website",
      label: "My website",
      url: "https://example.com",
      source_link_id: "website",
    },
  ];
  linked.unresolved_links = [
    {
      id: "unplaced",
      label: "GitHub",
      url: "https://github.com/example/project",
      source_link_id: "unplaced",
      reason: "Choose the linked phrase.",
    },
  ];
  const html = renderToStaticMarkup(
    <ContentEditor value={linked} onChange={() => {}} />,
  );
  assert.ok(html.includes("My website"));
  assert.ok(html.includes("https://example.com"));
  assert.ok(html.includes("Place your imported links"));
  assert.ok(html.includes("https://github.com/example/project"));
  assert.ok(html.includes("Remove from unresolved list"));
  assert.equal(sourceLinks(linked).length, 2);
});
