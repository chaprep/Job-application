"""Soft deletion retains history, files and links while removing active work."""
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend import database as d, repository as r
from backend.app import create_app
from backend.config import Settings
from backend_fixtures import FakeAI, resume_content


class SoftDeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(database=Path(self.tmp.name) / 'jab.sqlite3', model='fixture', api_key='fixture')
        self.client = TestClient(create_app(self.settings, FakeAI()))
        self.client.__enter__()
        self.service = self.client.app.state.service
        self.service.stop()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def seed(self):
        with self.service.connection() as db:
            job = r.create_job(db, source_type='pasted', jd_text='Build useful software')
            r.save_job(db, job, company='Example', title='Engineer', confirm=True)
            resume = r.upload_resume(db, 'base.pdf', b'%PDF-1.7\nfixture')
            r.start_extraction(db, resume)
            r.finish_extraction(db, resume, 'Original', resume_content().model_dump())
            d.activate_resume(db, resume, resume_content().model_dump())
            run = r.create_run(db, job_id=job)
            r.start_run(db, run)
            doc = r.save_document(db, run, 'resume', resume_content().model_dump())
            for check in ('structure', 'facts', 'pdf'):
                r.add_validation(db, doc, check, 'passed', [])
            r.publish_pdf(db, doc, b'%PDF-1.7\nretained document')
            r.finish_run(db, run)
            app = d.record_application(db, origin='jab', company='Example', role='Engineer',
                job_id=job, applied_on='2026-11-05', resume_document_id=doc)
            r.update_followup(db, app, next_action='Call', due_on='2026-11-06')
        return job, app, doc, run

    def test_application_delete_retains_job_document_and_history(self):
        job, app, doc, _ = self.seed()
        path = f'/api/v1/applications/{app}'
        history = self.client.get(path + '/events').json()
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()['deleted_at'])
        self.assertEqual(self.client.delete(path).json()['deleted_at'], deleted.json()['deleted_at'])
        for query in ('', '?search=Example', '?stage=applied', '?due_before=2026-11-07', f'?job_id={job}'):
            self.assertEqual(self.client.get('/api/v1/applications' + query).json()['total'], 0)
        self.assertEqual(self.client.get(path + '/events').json(), history)
        self.assertEqual(self.client.get(path + '/activity').json()['total'], 1)
        self.assertIsNone(self.client.get(f'/api/v1/jobs/{job}').json()['deleted_at'])
        self.assertEqual(self.client.get(f'/api/v1/documents/{doc}/pdf').content, b'%PDF-1.7\nretained document')
        for method, suffix, body in (
            ('post', '/stage', {'stage': 'interviewing'}),
            ('post', '/notes', {'note': 'Should fail'}),
            ('put', '/follow-up', {'next_action': 'Changed'}),
            ('post', '/corrections', {'reason': 'Change', 'role': 'Changed'}),
        ):
            response = getattr(self.client, method)(path + suffix, json=body)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get(path + '/events').json(), history)

    def test_job_delete_preserves_application_and_blocks_new_work(self):
        job, app, doc, run = self.seed()
        with self.service.connection() as db:
            duplicate = r.create_job(db, source_type='pasted', jd_text='Other description')
            r.save_job(db, duplicate, company='Example', title='Engineer')
        path = f'/api/v1/jobs/{job}'
        self.assertIn(job, self.client.get(f'/api/v1/jobs/{duplicate}').json()['duplicate_job_ids'])
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.delete(path).json(), deleted.json())
        self.assertNotIn(job, self.client.get(f'/api/v1/jobs/{duplicate}').json()['duplicate_job_ids'])
        self.assertEqual(self.client.get('/api/v1/jobs?status=ready&search=Example').json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/jobs').json()['total'], 1)
        self.assertEqual(self.client.get('/api/v1/applications').json()['total'], 1)
        self.assertEqual(self.client.get(f'/api/v1/applications/{app}').json()['job_id'], job)
        self.assertEqual(self.client.get(f'/api/v1/documents/{doc}/pdf').status_code, 200)
        self.assertEqual(self.client.get(path + '/documents').json()['total'], 1)
        activity = self.client.get(path + '/activity').json()['items']
        self.assertEqual([e['kind'] for e in activity], ['deleted', 'confirmed', 'created'])
        for method, suffix, body in (
            ('patch', '', {'title': 'Changed'}), ('post', '/confirm', None),
            ('post', '/archive', None), ('post', '/runs', {}),
            ('post', '/intake', {'source_type': 'pasted', 'jd_text': 'A replacement job description with sufficient content.'}),
        ):
            response = getattr(self.client, method)(path + suffix, json=body)
            self.assertEqual(response.status_code, 409, response.text)
        # Existing applications can still progress after their job is deleted.
        self.assertEqual(self.client.post(f'/api/v1/applications/{app}/stage', json={'stage': 'screening'}).status_code, 200)
        response = self.client.post('/api/v1/applications', json={'origin': 'external', 'company': 'Example', 'role': 'Engineer', 'job_id': job})
        self.assertEqual(response.status_code, 409, response.text)
        with self.service.connection() as db:
            d.check(db)
            for statement in ('DELETE FROM activity_events', 'UPDATE activity_events SET kind=\'changed\'', 'DELETE FROM jobs', 'DELETE FROM applications'):
                with self.assertRaises(sqlite3.IntegrityError), d.transaction(db):
                    db.execute(statement)

    def test_busy_job_cannot_be_deleted_and_missing_records_return_404(self):
        job, _, doc, run = self.seed()
        for owner, value, action in (('job_id', job, 'intake_job'), ('run_id', run, 'generate'), ('document_id', doc, 'render')):
            with self.service.connection() as db, d.transaction(db):
                task = self.service.task(db, action, owner, value)['task_id']
            response = self.client.delete(f'/api/v1/jobs/{job}')
            self.assertEqual(response.status_code, 409, response.text)
            with self.service.connection() as db, d.transaction(db):
                db.execute("UPDATE processing_tasks SET status='failed' WHERE id=?", (task,))
        self.assertIsNone(self.client.get(f'/api/v1/jobs/{job}').json()['deleted_at'])
        for collection in ('jobs', 'applications'):
            self.assertEqual(self.client.delete(f'/api/v1/{collection}/9999').status_code, 404)

    def test_upgrade_existing_database_preserves_rows_and_events(self):
        old_migrations = Path(self.tmp.name) / 'old_migrations'
        old_migrations.mkdir()
        for migration in sorted(d.MIGRATIONS.glob('*.sql'))[:4]:
            shutil.copyfile(migration, old_migrations / migration.name)
        db = d.connect(Path(self.tmp.name) / 'old.sqlite3')
        try:
            with patch.object(d, 'MIGRATIONS', old_migrations):
                d.migrate(db)
            with d.transaction(db):
                db.execute("INSERT INTO jobs(source_type,status,jd_text,created_at,updated_at) VALUES ('pasted','needs_review','Existing description',?,?)", (d.now(), d.now()))
            app = d.record_application(db, origin='external', company='Existing', role='Engineer')
            d.change_stage(db, app, 'screening')
            history = r.history(db, 'application_events', application_id=app)
            d.migrate(db)
            d.migrate(db)
            self.assertEqual(r.get(db, 'jobs', 1)['jd_text'], 'Existing description')
            self.assertIsNone(r.get(db, 'jobs', 1)['deleted_at'])
            self.assertIsNone(r.get(db, 'applications', app)['deleted_at'])
            self.assertEqual(r.history(db, 'application_events', application_id=app), history)
            r.soft_delete(db, 'applications', app)
            self.assertEqual(len(r.history(db, 'activity_events', application_id=app)), 1)
            d.check(db)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
