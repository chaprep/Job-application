"""Persistence integration tests; fake parser/model/PDF results avoid external services."""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import database as d
import repository as r
import storage

PDF = b'%PDF-1.7\nfixture; not a compiled document\n%%EOF'


class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.db = d.connect(self.base / 'live' / 'jab.sqlite3')
        d.migrate(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def resume(self, name='Original'):
        resume = r.upload_resume(self.db, 'base.pdf', PDF)
        r.start_extraction(self.db, resume)
        capture = r.create_capture(self.db, capture_type='resume_text', resume_version_id=resume)
        r.finish_capture(self.db, capture, captured_text=name)
        r.finish_extraction(self.db, resume, name, {'name': name, 'skills': ['Python']})
        d.activate_resume(self.db, resume, {'name': name, 'skills': ['Python']})
        return resume

    def job(self, title='Engineer'):
        job = r.create_job(self.db, source_type='pasted', jd_text='Build useful software')
        r.save_job(self.db, job, company='Example', title=title, confirm=True)
        return job

    def make_run(self, job=None):
        if self.db.execute('SELECT count(*) FROM resume_versions WHERE is_active=1').fetchone()[0] == 0:
            self.resume()
        run = r.create_run(self.db, job_id=job or self.job(), provider='fixture', model='fixture', prompt_version='1', template_version='1')
        r.start_run(self.db, run)
        return run

    def document(self, run, kind='resume', ready=True):
        doc = r.save_document(self.db, run, kind, {'text': 'A factual draft'})
        if ready:
            self.ready(doc)
        return doc

    def ready(self, doc):
        for kind in ('pdf',):
            r.add_validation(self.db, doc, kind, 'passed', [])
        r.publish_pdf(self.db, doc, PDF)

    def test_all_five_workflows_and_history(self):
        resume = self.resume()
        job = self.job()
        run = self.make_run(job)
        ai = r.create_ai_call(self.db, purpose='generate', provider='fixture', model='test', request={'input': 'facts'}, run_id=run)
        r.finish_ai_call(self.db, ai, raw_response='raw model output', validated_response={'resume': {'text': 'draft'}, 'cover_letter': {'text': 'letter'}}, token_usage={'input': 20})
        first = r.save_document(self.db, run, 'resume', {'text': 'draft'}, ai_call_id=ai)
        self.ready(first)
        letter = self.document(run, 'cover_letter')
        self.assertEqual(r.finish_run(self.db, run), 'succeeded')
        app = d.record_application(self.db, origin='jab', company='Example', role='Engineer', job_id=job, applied_on='2026-11-05', resume_document_id=first, cover_letter_document_id=letter)
        edited = r.save_document(self.db, run, 'resume', {'text': 'user edit'})
        self.ready(edited)
        self.assertEqual(r.get(self.db, 'applications', app)['resume_document_id'], first)
        self.assertEqual(r.get(self.db, 'document_versions', edited)['parent_document_id'], first)
        revision = r.create_run(self.db, job_id=job, source_document_id=edited, instructions='Shorten the summary')
        snap = json.loads(r.get(self.db, 'preparation_runs', revision)['source_snapshot_json'])
        self.assertEqual(snap['source_document']['content']['text'], 'user edit')
        d.change_stage(self.db, app, 'interviewing', '2026-11-06T10:00:00+05:30')
        r.add_note(self.db, app, 'First interview arranged')
        r.update_followup(self.db, app, next_action='Prepare', due_on='2026-11-07')
        r.correct_application(self.db, app, reason='Selected the wrong PDF initially', resume_document_id=edited)
        r.correct_application(self.db, app, reason='Role name corrected', role='AI Engineer')
        events = r.history(self.db, 'application_events', application_id=app)
        self.assertEqual([e['kind'] for e in events], ['submission_recorded','stage_changed','note_added','next_action_changed','submission_corrected','details_corrected'])
        self.assertEqual(json.loads(events[4]['details_json'])['old']['resume_document_id'], first)
        self.assertEqual(r.download_pdf(self.db, first).read_bytes(), PDF)
        self.assertEqual(r.get(self.db, 'resume_versions', resume)['status'], 'ready')
        d.check(self.db)
        storage.verify_files(self.db)

    def test_approved_resume_edit_clones_and_inputs_stay_frozen(self):
        original = self.resume()
        job = self.job()
        run = self.make_run(job)
        snapshot = r.get(self.db, 'preparation_runs', run)['source_snapshot_json']
        clone = r.save_resume_draft(self.db, original, {'name': 'Changed'})
        self.assertEqual(r.get(self.db, 'resume_versions', clone)['parent_resume_id'], original)
        r.save_resume_draft(self.db, clone, {'name': 'Reviewed change'})
        self.assertEqual(self.db.execute('SELECT id FROM resume_versions WHERE is_active=1').fetchone()[0], original)
        d.activate_resume(self.db, clone, {'name': 'Reviewed change'})
        r.save_job(self.db, job, title='New title', confirm=True)
        self.assertEqual(snapshot, r.get(self.db, 'preparation_runs', run)['source_snapshot_json'])
        self.assertEqual(json.loads(r.get(self.db, 'resume_versions', original)['reviewed_content_json'])['name'], 'Original')
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("UPDATE resume_versions SET reviewed_content_json='{}' WHERE id=?", (original,))
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("UPDATE preparation_runs SET source_snapshot_json='{}' WHERE id=?", (run,))

    def test_url_failure_paste_fallback_and_ai_extraction_history(self):
        job = r.create_job(self.db, source_type='url', source_url='https://example.com/job')
        capture = r.create_capture(self.db, capture_type='fetched_jd', job_id=job, supplied_url='https://example.com/job')
        r.finish_capture(self.db, capture, error='Page blocked')
        pasted = r.create_capture(self.db, capture_type='pasted_jd', job_id=job, supplied_url='https://example.com/job')
        r.finish_capture(self.db, pasted, captured_text='Full pasted JD')
        ai = r.create_ai_call(self.db, purpose='extract_job', provider='fixture', model='fixture', request={'text': 'Full pasted JD'}, intake_capture_id=pasted)
        r.finish_ai_call(self.db, ai, raw_response='{"company":"Example"}', validated_response={'company': 'Example'})
        r.save_job(self.db, job, company='Example', title='Role', jd_text='Full pasted JD', expected_salary='INR 25 lakh/year', advertised_salary='INR 20 lakh/year', confirm=True)
        self.assertEqual(r.get(self.db, 'jobs', job)['source_url'], 'https://example.com/job')
        self.assertIsNone(r.get(self.db, 'jobs', self.job())['source_url'])
        with self.assertRaises(sqlite3.IntegrityError):
            r.finish_capture(self.db, pasted, captured_text='overwrite')
        with self.assertRaises(sqlite3.IntegrityError):
            r.finish_ai_call(self.db, ai, raw_response='overwrite', validated_response={'x': 1})
        self.assertEqual(r.get(self.db, 'ai_calls', ai)['raw_response'], '{"company":"Example"}')

    def test_partial_failed_render_retry_and_no_submission_on_download(self):
        run = self.make_run()
        first = self.document(run)
        letter = self.document(run, 'cover_letter', ready=False)
        r.render_failed(self.db, letter, 'Compilation failed')
        self.assertEqual(r.finish_run(self.db, run, error='One PDF failed'), 'partial')
        self.assertEqual(r.get(self.db, 'document_versions', letter)['content_json'], '{"text": "A factual draft"}')
        self.ready(letter)
        r.download_pdf(self.db, first)
        self.assertEqual(r.history(self.db, 'applications'), [])
        self.assertEqual(r.get(self.db, 'document_versions', letter)['render_status'], 'ready')
        with self.assertRaises(ValueError):
            r.publish_pdf(self.db, first, PDF)

    def test_missing_and_failed_checks_block_pdf(self):
        doc = self.document(self.make_run(), ready=False)
        with self.assertRaises(sqlite3.IntegrityError):
            r.publish_pdf(self.db, doc, PDF)
        r.add_validation(self.db, doc, 'facts', 'failed', ['Historical unsupported claim'])
        r.add_validation(self.db, doc, 'pdf', 'failed', ['Overflow'])
        with self.assertRaises(sqlite3.IntegrityError):
            r.publish_pdf(self.db, doc, PDF)
        r.add_validation(self.db, doc, 'ai_review', 'failed', ['Historical AI review'])
        r.add_validation(self.db, doc, 'pdf', 'passed', [])
        r.publish_pdf(self.db, doc, PDF)
        with self.assertRaises(sqlite3.IntegrityError):
            r.add_validation(self.db, doc, 'facts', 'failed', [])
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("UPDATE document_versions SET content_json='{}' WHERE id=?", (doc,))
        self.assertTrue(storage.orphan_files(self.db))

    def test_render_only_migration_preserves_failed_draft_and_findings(self):
        old_migrations = self.base / 'old_migrations'
        old_migrations.mkdir()
        for migration in sorted(d.MIGRATIONS.glob('*.sql'))[:5]:
            shutil.copyfile(migration, old_migrations / migration.name)
        current = self.db
        self.db = d.connect(self.base / 'old.sqlite3')
        try:
            with patch.object(d, 'MIGRATIONS', old_migrations):
                d.migrate(self.db)
            doc = self.document(self.make_run(), ready=False)
            r.add_validation(self.db, doc, 'facts', 'failed', ['Old source references'])
            r.render_failed(self.db, doc, 'Old factual failure')
            before = r.get(self.db, 'document_versions', doc)['content_json']
            history = r.history(self.db, 'document_validations', document_id=doc)
            d.migrate(self.db)
            d.migrate(self.db)
            self.assertEqual(r.history(self.db, 'document_validations', document_id=doc), history)
            self.assertEqual(r.get(self.db, 'document_versions', doc)['content_json'], before)
            r.add_validation(self.db, doc, 'pdf', 'passed', [])
            r.publish_pdf(self.db, doc, PDF)
            self.assertEqual(r.get(self.db, 'document_versions', doc)['render_status'], 'ready')
            self.assertEqual(r.get(self.db, 'document_versions', doc)['render_error'], None)
        finally:
            self.db.close()
            self.db = current

    def test_submission_rejects_wrong_job_kind_pending_and_corrupt_files(self):
        run = self.make_run()
        job = r.get(self.db, 'preparation_runs', run)['job_id']
        resume = self.document(run)
        letter = self.document(run, 'cover_letter')
        pending = self.document(run, ready=False)
        args = dict(origin='jab', company='Example', role='Role', applied_on='2026-11-05')
        for job_id, doc in ((job, letter), (job, pending), (self.job(), resume)):
            with self.assertRaises(ValueError):
                d.record_application(self.db, **args, job_id=job_id, resume_document_id=doc)
        with self.assertRaises(ValueError):
            d.record_application(self.db, **{**args, 'applied_on': '2026-02-30'}, job_id=job, resume_document_id=resume)
        self.assertEqual(r.history(self.db, 'applications'), [])
        path = r.download_pdf(self.db, resume)
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            r.download_pdf(self.db, resume)
        with self.assertRaises(ValueError):
            d.record_application(self.db, **args, job_id=job, resume_document_id=resume)
        with self.assertRaises(ValueError):
            storage.verify_files(self.db)
        path.unlink()
        with self.assertRaises(ValueError):
            r.download_pdf(self.db, resume)

    def test_cross_run_parent_and_ai_provenance(self):
        run = self.make_run()
        doc = self.document(run)
        other = self.make_run()
        with self.assertRaises(sqlite3.IntegrityError):
            r.save_document(self.db, other, 'resume', {'text': 'x'}, parent_document_id=doc)
        job = r.get(self.db, 'preparation_runs', run)['job_id']
        revision = r.create_run(self.db, job_id=job, source_document_id=doc, instructions='Shorten')
        r.start_run(self.db, revision)
        child = self.document(revision)
        self.assertEqual(r.get(self.db, 'document_versions', child)['parent_document_id'], doc)
        ai = r.create_ai_call(self.db, purpose='draft', provider='p', model='m', request={'x': 1}, run_id=run)
        with self.assertRaises(sqlite3.IntegrityError):
            r.save_document(self.db, run, 'resume', {'x': 1}, ai_call_id=ai)
        r.finish_ai_call(self.db, ai, raw_response='x', validated_response={'x': 1})
        with self.assertRaises(sqlite3.IntegrityError):
            r.add_validation(self.db, child, 'ai_review', 'passed', [], ai_call_id=ai)

    def test_restart_recovery_preserves_completed_results(self):
        run = self.make_run()
        doc = self.document(run)
        call = r.create_ai_call(self.db, purpose='draft', provider='p', model='m', request={'x': 1}, run_id=run)
        upload = r.upload_resume(self.db, 'new.docx', b'PK\x03\x04fixture')
        capture = r.create_capture(self.db, capture_type='resume_text', resume_version_id=upload)
        d.recover_interrupted(self.db)
        d.recover_interrupted(self.db)
        for table, row in (('preparation_runs', run), ('ai_calls', call), ('intake_captures', capture)):
            self.assertEqual(r.get(self.db, table, row)['status'], 'interrupted')
        self.assertEqual(r.get(self.db, 'resume_versions', upload)['status'], 'failed')
        self.assertEqual(r.get(self.db, 'document_versions', doc)['render_status'], 'ready')
        r.start_extraction(self.db, upload)
        r.finish_extraction(self.db, upload, 'Retry worked', {'name': 'Retry'})

    def test_backup_restore_complete_and_no_overwrite(self):
        run = self.make_run()
        self.document(run)
        bundle = storage.backup(self.db, self.base / 'backup')
        restored = storage.restore(bundle, self.base / 'restored')
        db = d.connect(restored / 'jab.sqlite3')
        try:
            d.check(db)
            storage.verify_files(db)
            self.assertEqual(r.history(db, 'document_versions'), r.history(self.db, 'document_versions'))
            d.migrate(db)
        finally:
            db.close()
        with self.assertRaises(FileExistsError):
            storage.restore(bundle, restored)
        with self.assertRaises(ValueError):
            storage.backup(self.db, storage.root(self.db) / 'bad')
        pdf = next((bundle / 'pdfs').glob('*.pdf'))
        pdf.write_bytes(b'corrupt')
        target = self.base / 'failed-restore'
        with self.assertRaises(ValueError):
            storage.restore(bundle, target)
        self.assertFalse(target.exists())
        storage.verify_files(self.db)

    def test_backup_releases_write_lock_and_rejects_missing_files(self):
        self.resume()
        path = storage.resolve(self.db, r.history(self.db, 'resume_versions')[0]['file_path'])
        path.unlink()
        with self.assertRaises(ValueError):
            storage.backup(self.db, self.base / 'bad-backup')
        self.assertFalse(self.db.in_transaction)
        self.assertFalse((self.base / 'bad-backup').exists())
        self.job()

    def test_migrations_unknown_changed_and_failed_are_safe(self):
        d.migrate(self.db)
        with self.db:
            self.db.execute("INSERT INTO schema_migrations VALUES ('999_future.sql','hash',?)", (d.now(),))
        with self.assertRaises(RuntimeError):
            d.migrate(self.db)
        with self.db:
            self.db.execute("DELETE FROM schema_migrations WHERE version='999_future.sql'")
        with tempfile.TemporaryDirectory() as directory:
            migrations = Path(directory)
            for file in d.MIGRATIONS.glob('*.sql'):
                (migrations / file.name).write_bytes(file.read_bytes())
            first = migrations / '001_initial.sql'
            first.write_text(first.read_text() + '\n-- changed')
            with patch.object(d, 'MIGRATIONS', migrations), self.assertRaises(RuntimeError):
                d.migrate(self.db)
            first.write_bytes((d.MIGRATIONS / first.name).read_bytes())
            next_version = max(int(file.name.split('_', 1)[0]) for file in migrations.glob('*.sql')) + 1
            (migrations / f'{next_version:03d}_broken.sql').write_text('CREATE TABLE transient(id); INVALID SQL;')
            with patch.object(d, 'MIGRATIONS', migrations), self.assertRaises(sqlite3.OperationalError):
                d.migrate(self.db)
            self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='transient'").fetchone())

    def test_application_update_and_event_roll_back_together(self):
        app = d.record_application(self.db, origin='external', company='Outside', role='Role')
        self.assertIsNone(r.get(self.db, 'applications', app)['applied_on'])
        with self.db:
            self.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON application_events BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            r.update_followup(self.db, app, next_action='Call', due_on='2026-11-06')
        self.assertIsNone(r.get(self.db, 'applications', app)['next_action'])
        with self.assertRaises(sqlite3.IntegrityError):
            r.correct_application(self.db, app, reason='Fix title', role='New role')
        self.assertEqual(r.get(self.db, 'applications', app)['role'], 'Role')

    def test_backup_holds_write_reservation_during_file_copy(self):
        self.resume()
        other = d.connect(storage.root(self.db) / 'jab.sqlite3')
        other.execute('PRAGMA busy_timeout=1')
        copy = storage.shutil.copyfile
        probes = []

        def probe(source, destination):
            with self.assertRaises(sqlite3.OperationalError):
                with other:
                    other.execute("UPDATE resume_versions SET is_active=0")
            probes.append(True)
            return copy(source, destination)

        try:
            with patch.object(storage.shutil, 'copyfile', side_effect=probe):
                storage.backup(self.db, self.base / 'locked-backup')
            self.assertTrue(probes)
            with other:
                other.execute("UPDATE resume_versions SET updated_at=?", (d.now(),))
        finally:
            other.close()

    def test_credential_rejection_and_failed_ai_response_retention(self):
        run = self.make_run()
        with self.assertRaises(ValueError):
            r.create_ai_call(self.db, purpose='draft', provider='p', model='m',
                             request={'config': {'Authorization': 'private'}}, run_id=run)
        self.assertEqual(r.history(self.db, 'ai_calls'), [])
        call = r.create_ai_call(self.db, purpose='draft', provider='p', model='m', request={'text': 'input'}, run_id=run)
        r.finish_ai_call(self.db, call, raw_response='malformed response', error='Invalid model JSON')
        self.assertEqual(r.get(self.db, 'ai_calls', call)['raw_response'], 'malformed response')
        self.assertEqual(r.finish_run(self.db, run, error='Invalid model JSON'), 'failed')

    def test_failed_extraction_retry_and_invalid_activation_preserve_source(self):
        original = self.resume()
        new = r.upload_resume(self.db, 'new.pdf', PDF)
        capture = r.create_capture(self.db, capture_type='resume_text', resume_version_id=new)
        r.start_capture(self.db, capture)
        r.finish_capture(self.db, capture, captured_text='Partial unreadable text', error='Unreadable pages')
        r.finish_extraction(self.db, new, extracted_text='Partial unreadable text', error='Unreadable pages')
        r.start_extraction(self.db, new)
        r.finish_extraction(self.db, new, 'Corrected extraction', {'name': 'New'})
        with self.assertRaises(sqlite3.IntegrityError):
            d.activate_resume(self.db, new, {'invalid': float('nan')})
        self.assertEqual(self.db.execute('SELECT id FROM resume_versions WHERE is_active=1').fetchone()[0], original)
        self.assertEqual(r.get(self.db, 'intake_captures', capture)['captured_text'], 'Partial unreadable text')

    def test_upgrade_existing_initial_schema_preserves_data(self):
        old = d.connect(self.base / 'old' / 'jab.sqlite3')
        try:
            with tempfile.TemporaryDirectory() as directory:
                initial = Path(directory)
                (initial / '001_initial.sql').write_bytes((d.MIGRATIONS / '001_initial.sql').read_bytes())
                with patch.object(d, 'MIGRATIONS', initial):
                    d.migrate(old)
                app = d.record_application(old, origin='external', company='Existing', role='Engineer')
            d.migrate(old)
            self.assertEqual(r.get(old, 'applications', app)['company'], 'Existing')
            self.assertEqual(len(r.history(old, 'application_events', application_id=app)), 1)
            d.check(old)
        finally:
            old.close()

    def test_path_and_upload_boundaries(self):
        for name in ('../outside', '/tmp/outside', '.'):
            with self.assertRaises(ValueError):
                storage.resolve(self.db, name)
        (storage.root(self.db) / 'link').symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            storage.resolve(self.db, 'link/outside')
        for name, data in (('bad.txt', PDF), ('bad.pdf', b'no'), ('bad.docx', PDF)):
            with self.assertRaises(ValueError):
                r.upload_resume(self.db, name, data)
        with self.assertRaises(ValueError):
            r.history(self.db, 'jobs; DROP TABLE jobs')
        with self.assertRaises(ValueError):
            r.history(self.db, 'jobs', bad_column=1)
        with self.assertRaises(ValueError):
            r.create_run(self.db, job_id=self.job())


if __name__ == '__main__':
    unittest.main()
