export interface LinkSpan {
  start: number | null;
  end: number | null;
  url: string;
  source_link_id: string | null;
  unresolved_label?: string | null;
}
export interface ContactLink {
  id: string;
  label: string;
  url: string;
  source_link_id: string | null;
}
export interface UnresolvedLink extends ContactLink {
  reason: string;
}
export interface Claim {
  id: string;
  text: string;
  source_refs: string[];
  emphasis: string[];
  links?: LinkSpan[];
}
export interface Contact {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: ContactLink[];
}
export interface Entry {
  id: string;
  title: string;
  organization: string;
  location: string;
  dates: string;
  link: string;
  link_label?: string;
  link_source_id?: string | null;
  title_links?: LinkSpan[];
  organization_links?: LinkSpan[];
  description: Claim[];
  bullets: Claim[];
  children: Entry[];
}
export interface ResumeContent {
  schema_version: "1" | "2";
  unresolved_links?: UnresolvedLink[];
  contact: Contact;
  summary: Claim[];
  skills: { id: string; label: string; items: Claim[] }[];
  experience: Entry[];
  projects: Entry[];
  education: Entry[];
  additional_sections: { title: string; entries: Entry[] }[];
}
export interface CoverLetter {
  schema_version: "1" | "2";
  letter_date?: string | null;
  unresolved_links?: UnresolvedLink[];
  contact: Contact;
  salutation: string;
  paragraphs: Claim[];
  closing: string;
  signature: string;
}
export type Content = ResumeContent | CoverLetter;
export interface Finding {
  field: string;
  severity: string;
  category?: string;
  explanation: string;
}
export interface Task {
  id: number;
  status: string;
  step: string;
  error_message: string | null;
  result: {
    findings?: Finding[];
    status?: string;
    issues?: { message: string }[];
  } | null;
}
export interface Accepted {
  task_id: number;
  resume_version_id?: number;
  job_id?: number;
  run_id?: number;
  document_id?: number;
}
export interface Capture {
  id: number;
  captured_text: string | null;
  status: string;
  error_message: string | null;
  supplied_url: string | null;
}
export interface Resume {
  parent_resume_id?: number | null;
  validation_overrides?: Finding[] | null;
  id: number;
  original_filename: string;
  file_type: string;
  status: string;
  is_active: number;
  reviewed_content: ResumeContent | null;
  extracted_text: string | null;
  error_message: string | null;
  created_at: string;
  tasks?: Task[];
  captures?: Capture[];
}
export interface Requirements {
  responsibilities: string[];
  required: string[];
  preferred: string[];
}
export interface Job {
  id: number;
  deleted_at?: string | null;
  company: string | null;
  title: string | null;
  location: string | null;
  source_type: "url" | "pasted";
  source_url: string | null;
  jd_text: string | null;
  expected_salary: string | null;
  advertised_salary: string | null;
  employment_type: string | null;
  application_deadline: string | null;
  recruiter_details: string | null;
  job_reference: string | null;
  tailoring_instructions: string | null;
  requirements: Requirements | null;
  status: string;
  created_at: string;
  updated_at: string;
  tasks?: Task[];
  captures?: Capture[];
  duplicate_job_ids?: number[];
  active_tasks?: Task[];
}
export interface Run {
  id: number;
  job_id: number;
  resume_version_id: number;
  status: string;
  created_at: string;
  error_message: string | null;
  model: string | null;
  source_document_id: number | null;
  review_findings: { message?: string }[] | null;
  tasks?: Task[];
  documents?: Document[];
  source_snapshot?: {
    resume: ResumeContent;
    source_document?: { kind: "resume" | "cover_letter" };
  };
}
export interface Document {
  id: number;
  run_id: number;
  kind: "resume" | "cover_letter";
  revision: number;
  version_number?: number;
  source_resume?: ResumeContent;
  content: Content;
  render_status: string;
  render_error: string | null;
  created_at: string;
  validations?: {
    id: number;
    check_type: string;
    result: string;
    findings: Finding[];
  }[];
  tasks?: Task[];
}
export type DocumentSelections = { resume: Document | null; cover_letter: Document | null };

export const stages = [
  "applied",
  "screening",
  "interviewing",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
] as const;
export type Stage = (typeof stages)[number];
export interface Application {
  id: number;
  deleted_at?: string | null;
  company: string;
  role: string;
  origin: "jab" | "external";
  job_id: number | null;
  stage: Stage;
  applied_on: string | null;
  application_url: string | null;
  resume_document_id: number | null;
  cover_letter_document_id: number | null;
  next_action: string | null;
  next_action_due_on: string | null;
}
export interface ApplicationEvent {
  id: number;
  kind: string;
  occurred_at: string;
  note: string | null;
  details: { old?: unknown; new?: unknown; [key: string]: unknown } | null;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Readiness {
  database: boolean;
  renderer: boolean;
  ai_configured: boolean;
  model: string | null;
}
