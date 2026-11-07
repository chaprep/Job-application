-- Human review replaces automated factual approval; retain all historical checks.
DROP TRIGGER document_ready_checks;
CREATE TRIGGER document_ready_checks BEFORE UPDATE OF render_status ON document_versions
WHEN NEW.render_status='ready' AND coalesce((
 SELECT result FROM document_validations
 WHERE document_id=NEW.id AND check_type='pdf' ORDER BY id DESC LIMIT 1
),'missing')!='passed'
BEGIN SELECT RAISE(ABORT,'document has missing or failed PDF check'); END;
