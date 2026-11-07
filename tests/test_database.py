import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import database

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = database.connect(Path(self.tmp.name) / 'test.sqlite3')
        database.migrate(self.db)
        database.migrate(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_active_resume_survives_failed_replacement(self):
        stamp = database.now()
        for name in ('one','two'):
            self.db.execute("INSERT INTO resume_versions(original_filename,file_path,file_type,sha256,status,created_at,updated_at) VALUES (?,?,'pdf','hash','needs_review',?,?)",(name,name,stamp,stamp))
        self.db.commit()
        database.activate_resume(self.db,1,{'name':'Test'})
        with self.assertRaises(ValueError):
            database.activate_resume(self.db,2,{})
        self.assertEqual(self.db.execute('SELECT id FROM resume_versions WHERE is_active=1').fetchone()[0],1)

    def test_application_history_and_atomic_invalid_stage(self):
        app = database.record_application(self.db,origin='external',company='Example',role='Engineer')
        database.change_stage(self.db,app,'screening')
        with self.assertRaises(sqlite3.IntegrityError):
            database.change_stage(self.db,app,'invalid')
        self.assertEqual(self.db.execute('SELECT stage FROM applications').fetchone()[0], 'screening')
        self.assertEqual(self.db.execute('SELECT count(*) FROM application_events').fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM application_events')
        database.check(self.db)

    def test_job_requires_reviewed_fields(self):
        stamp = database.now()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO jobs(source_type,status,created_at,updated_at) VALUES ('pasted','ready',?,?)",(stamp,stamp))
        self.db.execute("INSERT INTO jobs(source_type,status,jd_text,created_at,updated_at) VALUES ('pasted','needs_review','description',?,?)",(stamp,stamp))
        row = self.db.execute('SELECT source_url,jd_text FROM jobs').fetchone()
        self.assertEqual(tuple(row),(None,'description'))

if __name__ == '__main__':
    unittest.main()
