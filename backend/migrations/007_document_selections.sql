CREATE TABLE job_document_selections (
 job_id INTEGER NOT NULL REFERENCES jobs(id),
 kind TEXT NOT NULL CHECK(kind IN ('resume','cover_letter')),
 document_id INTEGER NOT NULL REFERENCES document_versions(id),
 PRIMARY KEY(job_id,kind)
);
-- Retain the newest ready version of each document when upgrading existing jobs.
INSERT INTO job_document_selections(job_id,kind,document_id)
SELECT p.job_id,doc.kind,max(doc.id)
FROM document_versions doc JOIN preparation_runs p ON p.id=doc.run_id
WHERE doc.render_status='ready' GROUP BY p.job_id,doc.kind;
