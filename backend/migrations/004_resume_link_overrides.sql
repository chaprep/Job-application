ALTER TABLE resume_versions ADD COLUMN validation_overrides_json TEXT CHECK(validation_overrides_json IS NULL OR json_valid(validation_overrides_json));
CREATE TRIGGER ready_resume_overrides_immutable BEFORE UPDATE OF validation_overrides_json ON resume_versions WHEN OLD.status='ready' BEGIN SELECT RAISE(ABORT,'approved resume overrides are immutable; create a version'); END;
