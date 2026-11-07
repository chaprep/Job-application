CREATE TABLE resume_versions (
 id INTEGER PRIMARY KEY, original_filename TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL CHECK(file_type IN ('pdf','docx')), sha256 TEXT NOT NULL,
 extracted_text TEXT, reviewed_content_json TEXT CHECK(reviewed_content_json IS NULL OR json_valid(reviewed_content_json)),
 status TEXT NOT NULL CHECK(status IN ('uploaded','extracting','needs_review','ready','failed')), error_message TEXT,
 is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reviewed_at TEXT,
 CHECK(is_active=0 OR (status='ready' AND reviewed_content_json IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE UNIQUE INDEX one_active_resume ON resume_versions(is_active) WHERE is_active=1;
CREATE TABLE jobs (
 id INTEGER PRIMARY KEY, company TEXT, title TEXT, location TEXT, expected_salary TEXT, advertised_salary TEXT, employment_type TEXT, application_deadline TEXT, recruiter_details TEXT, job_reference TEXT, tailoring_instructions TEXT,
 source_type TEXT NOT NULL CHECK(source_type IN ('url','pasted')), source_url TEXT, jd_text TEXT,
 status TEXT NOT NULL CHECK(status IN ('needs_review','ready','archived')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(source_type != 'url' OR length(trim(coalesce(source_url,'')))>0),
 CHECK(status != 'ready' OR (length(trim(coalesce(company,'')))>0 AND length(trim(coalesce(title,'')))>0 AND length(trim(coalesce(jd_text,'')))>0))
);
CREATE TABLE preparation_runs (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), resume_version_id INTEGER NOT NULL REFERENCES resume_versions(id), source_document_id INTEGER REFERENCES document_versions(id),
 source_snapshot_json TEXT NOT NULL CHECK(json_valid(source_snapshot_json)), status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','partial','failed','interrupted')),
 provider TEXT, model TEXT, prompt_version TEXT, template_version TEXT, review_findings_json TEXT CHECK(review_findings_json IS NULL OR json_valid(review_findings_json)), error_message TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE TABLE document_versions (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES preparation_runs(id), parent_document_id INTEGER REFERENCES document_versions(id), kind TEXT NOT NULL CHECK(kind IN ('resume','cover_letter')), revision INTEGER NOT NULL CHECK(revision>0),
 content_json TEXT NOT NULL CHECK(json_valid(content_json)), pdf_path TEXT, pdf_sha256 TEXT, render_status TEXT NOT NULL CHECK(render_status IN ('pending','ready','failed')), render_error TEXT, created_at TEXT NOT NULL, rendered_at TEXT,
 UNIQUE(run_id,kind,revision), CHECK(render_status != 'ready' OR (pdf_path IS NOT NULL AND pdf_sha256 IS NOT NULL AND rendered_at IS NOT NULL))
);
CREATE TABLE applications (
 id INTEGER PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('jab','external')), job_id INTEGER REFERENCES jobs(id), company TEXT NOT NULL CHECK(length(trim(company))>0), role TEXT NOT NULL CHECK(length(trim(role))>0), application_url TEXT, applied_on TEXT,
 stage TEXT NOT NULL CHECK(stage IN ('applied','screening','interviewing','offer','accepted','rejected','withdrawn')), resume_document_id INTEGER REFERENCES document_versions(id), cover_letter_document_id INTEGER REFERENCES document_versions(id), next_action TEXT, next_action_due_on TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(origin != 'jab' OR (job_id IS NOT NULL AND applied_on IS NOT NULL AND resume_document_id IS NOT NULL))
);
CREATE TABLE application_events (
 id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES applications(id), kind TEXT NOT NULL CHECK(kind IN ('submission_recorded','stage_changed','note_added','next_action_changed','submission_corrected','details_corrected')), occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, note TEXT, details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json)), CHECK(kind != 'note_added' OR length(trim(coalesce(note,'')))>0)
);
CREATE TABLE intake_captures (
 id INTEGER PRIMARY KEY, resume_version_id INTEGER REFERENCES resume_versions(id), job_id INTEGER REFERENCES jobs(id), capture_type TEXT NOT NULL CHECK(capture_type IN ('resume_text','pasted_jd','fetched_jd')), supplied_url TEXT, captured_text TEXT, status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','interrupted')), error_message TEXT, created_at TEXT NOT NULL,
 CHECK((resume_version_id IS NOT NULL)+(job_id IS NOT NULL)=1), CHECK((capture_type='resume_text')=(resume_version_id IS NOT NULL))
);
CREATE TABLE ai_calls (
 id INTEGER PRIMARY KEY, intake_capture_id INTEGER REFERENCES intake_captures(id), run_id INTEGER REFERENCES preparation_runs(id), purpose TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, request_json TEXT CHECK(request_json IS NULL OR json_valid(request_json)), raw_response TEXT, validated_response_json TEXT CHECK(validated_response_json IS NULL OR json_valid(validated_response_json)), status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','interrupted')), error_message TEXT, token_usage_json TEXT CHECK(token_usage_json IS NULL OR json_valid(token_usage_json)), started_at TEXT, finished_at TEXT,
 CHECK((intake_capture_id IS NOT NULL)+(run_id IS NOT NULL)=1)
);
CREATE TABLE document_validations (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES document_versions(id), check_type TEXT NOT NULL CHECK(check_type IN ('structure','facts','ai_review','pdf')), result TEXT NOT NULL CHECK(result IN ('passed','warnings','failed')), findings_json TEXT NOT NULL CHECK(json_valid(findings_json)), ai_call_id INTEGER REFERENCES ai_calls(id), created_at TEXT NOT NULL
);
CREATE TRIGGER no_event_update BEFORE UPDATE ON application_events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER no_event_delete BEFORE DELETE ON application_events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER no_document_content_update BEFORE UPDATE OF content_json,run_id,kind,revision,parent_document_id ON document_versions BEGIN SELECT RAISE(ABORT,'document content is immutable'); END;
CREATE TRIGGER no_ready_pdf_update BEFORE UPDATE OF pdf_path,pdf_sha256,render_status,rendered_at ON document_versions WHEN OLD.render_status='ready' BEGIN SELECT RAISE(ABORT,'ready PDF is immutable'); END;
CREATE TRIGGER no_run_inputs_update BEFORE UPDATE OF job_id,resume_version_id,source_document_id,source_snapshot_json ON preparation_runs BEGIN SELECT RAISE(ABORT,'run inputs are immutable'); END;
CREATE INDEX runs_job_created ON preparation_runs(job_id,created_at);
CREATE INDEX runs_resume ON preparation_runs(resume_version_id);
CREATE INDEX runs_source_document ON preparation_runs(source_document_id);
CREATE INDEX documents_run ON document_versions(run_id);
CREATE INDEX documents_parent ON document_versions(parent_document_id);
CREATE INDEX applications_stage_date ON applications(stage,applied_on);
CREATE INDEX applications_job ON applications(job_id);
CREATE INDEX applications_resume ON applications(resume_document_id);
CREATE INDEX applications_cover ON applications(cover_letter_document_id);
CREATE INDEX events_timeline ON application_events(application_id,occurred_at,id);
CREATE INDEX captures_resume ON intake_captures(resume_version_id);
CREATE INDEX captures_job ON intake_captures(job_id);
CREATE INDEX calls_capture ON ai_calls(intake_capture_id);
CREATE INDEX calls_run ON ai_calls(run_id);
CREATE INDEX validations_document ON document_validations(document_id,created_at);
CREATE INDEX validations_call ON document_validations(ai_call_id);
