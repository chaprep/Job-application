ALTER TABLE jobs ADD COLUMN deleted_at TEXT;
ALTER TABLE applications ADD COLUMN deleted_at TEXT;

CREATE TABLE activity_events (
 id INTEGER PRIMARY KEY,
 job_id INTEGER REFERENCES jobs(id), application_id INTEGER REFERENCES applications(id),
 kind TEXT NOT NULL, details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json)),
 created_at TEXT NOT NULL,
 CHECK((job_id IS NOT NULL)+(application_id IS NOT NULL)=1)
);
CREATE INDEX activity_job ON activity_events(job_id,id);
CREATE INDEX activity_application ON activity_events(application_id,id);
CREATE TRIGGER activity_no_update BEFORE UPDATE ON activity_events BEGIN SELECT RAISE(ABORT,'activity is append-only'); END;
CREATE TRIGGER activity_no_delete BEFORE DELETE ON activity_events BEGIN SELECT RAISE(ABORT,'activity is append-only'); END;

CREATE TRIGGER deleted_job_readonly BEFORE UPDATE ON jobs WHEN OLD.deleted_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'deleted job is read-only'); END;
CREATE TRIGGER deleted_application_readonly BEFORE UPDATE ON applications WHEN OLD.deleted_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'deleted application is read-only'); END;
CREATE TRIGGER job_deleted AFTER UPDATE OF deleted_at ON jobs WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL BEGIN
 INSERT INTO activity_events(job_id,kind,created_at) VALUES (NEW.id,'deleted',NEW.deleted_at);
END;
CREATE TRIGGER application_deleted AFTER UPDATE OF deleted_at ON applications WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL BEGIN
 INSERT INTO activity_events(application_id,kind,created_at) VALUES (NEW.id,'deleted',NEW.deleted_at);
END;
CREATE TRIGGER job_no_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT,'jobs are soft-deleted'); END;
CREATE TRIGGER application_no_delete BEFORE DELETE ON applications BEGIN SELECT RAISE(ABORT,'applications are soft-deleted'); END;
CREATE TRIGGER application_active_job BEFORE INSERT ON applications WHEN NEW.job_id IS NOT NULL AND EXISTS (SELECT 1 FROM jobs WHERE id=NEW.job_id AND deleted_at IS NOT NULL) BEGIN SELECT RAISE(ABORT,'cannot submit a deleted job'); END;
CREATE TRIGGER deleted_application_no_events BEFORE INSERT ON application_events WHEN EXISTS (SELECT 1 FROM applications WHERE id=NEW.application_id AND deleted_at IS NOT NULL) BEGIN SELECT RAISE(ABORT,'deleted application is read-only'); END;
