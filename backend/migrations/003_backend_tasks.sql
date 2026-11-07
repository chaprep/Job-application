ALTER TABLE jobs ADD COLUMN requirements_json TEXT CHECK(requirements_json IS NULL OR json_valid(requirements_json));
CREATE TABLE processing_tasks (
 id INTEGER PRIMARY KEY,
 action TEXT NOT NULL CHECK(action IN ('extract_resume','intake_job','generate','revise','render')),
 resume_version_id INTEGER REFERENCES resume_versions(id), job_id INTEGER REFERENCES jobs(id),
 run_id INTEGER REFERENCES preparation_runs(id), document_id INTEGER REFERENCES document_versions(id),
 input_json TEXT NOT NULL CHECK(json_valid(input_json)),
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','interrupted')),
 step TEXT NOT NULL DEFAULT 'queued', result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
 error_code TEXT, error_message TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 CHECK((resume_version_id IS NOT NULL)+(job_id IS NOT NULL)+(run_id IS NOT NULL)+(document_id IS NOT NULL)=1),
 CHECK((action='extract_resume' AND resume_version_id IS NOT NULL) OR (action='intake_job' AND job_id IS NOT NULL) OR (action IN ('generate','revise') AND run_id IS NOT NULL) OR (action='render' AND document_id IS NOT NULL))
);
CREATE UNIQUE INDEX active_resume_task ON processing_tasks(resume_version_id) WHERE status IN ('queued','running');
CREATE UNIQUE INDEX active_job_task ON processing_tasks(job_id) WHERE status IN ('queued','running');
CREATE UNIQUE INDEX active_run_task ON processing_tasks(run_id) WHERE status IN ('queued','running');
CREATE UNIQUE INDEX active_document_task ON processing_tasks(document_id) WHERE status IN ('queued','running');
CREATE TRIGGER task_inputs_immutable BEFORE UPDATE OF action,resume_version_id,job_id,run_id,document_id,input_json ON processing_tasks BEGIN SELECT RAISE(ABORT,'task inputs are immutable'); END;
CREATE TRIGGER terminal_task_immutable BEFORE UPDATE ON processing_tasks WHEN OLD.status IN ('succeeded','failed','interrupted') BEGIN SELECT RAISE(ABORT,'task is complete; create another attempt'); END;
CREATE TRIGGER task_history_retained BEFORE DELETE ON processing_tasks BEGIN SELECT RAISE(ABORT,'task history is retained'); END;

CREATE INDEX tasks_pending ON processing_tasks(status,id);
