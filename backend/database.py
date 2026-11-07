"""SQLite setup and transactional operations for Jab."""
from contextlib import contextmanager
import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = Path(__file__).parent / 'migrations'
DEFAULT_DB = ROOT / 'data' / 'jab.sqlite3'


@contextmanager
def transaction(db):
    """Serialize read-modify-write operations so history records the actual prior state."""
    if db.in_transaction:
        name = 'nested_' + uuid.uuid4().hex
        db.execute(f'SAVEPOINT {name}')
        try:
            yield
        except BaseException:
            db.execute(f'ROLLBACK TO {name}')
            db.execute(f'RELEASE {name}')
            raise
        else:
            db.execute(f'RELEASE {name}')
        return
    with db:
        db.execute('BEGIN IMMEDIATE')
        yield


def now():
    return datetime.now(timezone.utc).isoformat()


def connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)')
    db.commit()
    files = sorted(MIGRATIONS.glob('[0-9]*_*.sql'))
    known = {p.name for p in files}
    applied = dict(db.execute('SELECT version, checksum FROM schema_migrations'))
    if set(applied) - known:
        raise RuntimeError('Database has unknown migrations')
    if sorted(applied) != [p.name for p in files[:len(applied)]]:
        raise RuntimeError('Migration history is not an ordered prefix')
    for p in files[:len(applied)]:
        if applied[p.name] != hashlib.sha256(p.read_text().encode()).hexdigest():
            raise RuntimeError(f'Migration checksum mismatch: {p.name}')
    for p in files:
        sql = p.read_text()
        digest = hashlib.sha256(sql.encode()).hexdigest()
        if p.name in applied:
            if applied[p.name] != digest:
                raise RuntimeError(f'Migration checksum mismatch: {p.name}')
            continue
        # executescript commits before execution; include the transaction in the script.
        version = p.name.replace("'", "''")
        stamp = now()
        try:
            db.executescript(f"BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_migrations VALUES ('{version}', '{digest}', '{stamp}');\nCOMMIT;")
        except Exception:
            db.rollback()
            raise


def activate_resume(db, resume_id, content):
    if not isinstance(content, dict) or not content:
        raise ValueError('Reviewed résumé content is required')
    stamp = now()
    with transaction(db):
        row = db.execute('SELECT status FROM resume_versions WHERE id=?', (resume_id,)).fetchone()
        if row is None or row['status'] != 'needs_review':
            raise ValueError('Résumé is not ready for review')
        db.execute('UPDATE resume_versions SET is_active=0 WHERE is_active=1')
        db.execute("UPDATE resume_versions SET reviewed_content_json=?, status='ready', is_active=1, reviewed_at=?, updated_at=? WHERE id=?", (json.dumps(content), stamp, stamp, resume_id))


def validate_submission(db, job_id, resume_document_id, cover_letter_document_id):
    if __package__:
        from .repository import download_pdf
    else:
        from repository import download_pdf
    for document_id, kind in ((resume_document_id, 'resume'), (cover_letter_document_id, 'cover_letter')):
        if document_id is None:
            continue
        row = db.execute('SELECT d.kind,d.render_status,r.job_id FROM document_versions d JOIN preparation_runs r ON r.id=d.run_id WHERE d.id=?', (document_id,)).fetchone()
        if row is None or row['kind'] != kind or row['render_status'] != 'ready' or job_id is None or row['job_id'] != job_id:
            raise ValueError('Selected document must be ready, have the correct kind, and belong to this job')
        download_pdf(db, document_id)


def record_application(db, *, origin, company, role, job_id=None, applied_on=None, resume_document_id=None, cover_letter_document_id=None, application_url=None, stage='applied'):
    stamp = now()
    with transaction(db):
        if __package__:
            from .repository import day
        else:
            from repository import day
        day(applied_on)
        validate_submission(db, job_id, resume_document_id, cover_letter_document_id)
        cur = db.execute('INSERT INTO applications (origin,job_id,company,role,application_url,applied_on,stage,resume_document_id,cover_letter_document_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (origin,job_id,company,role,application_url,applied_on,stage,resume_document_id,cover_letter_document_id,stamp,stamp))
        db.execute("INSERT INTO application_events (application_id,kind,occurred_at,recorded_at,details_json) VALUES (?,'submission_recorded',?,?,?)", (cur.lastrowid,applied_on + 'T00:00:00+00:00' if applied_on else stamp,stamp,json.dumps({'resume_document_id':resume_document_id,'cover_letter_document_id':cover_letter_document_id})))
        return cur.lastrowid


def change_stage(db, application_id, stage, occurred_at=None):
    if __package__:
        from .repository import timestamp
    else:
        from repository import timestamp
    timestamp(occurred_at)
    stamp = now()
    with transaction(db):
        row = db.execute('SELECT stage FROM applications WHERE id=?', (application_id,)).fetchone()
        if row is None:
            raise ValueError('Application not found')
        db.execute('UPDATE applications SET stage=?,updated_at=? WHERE id=?', (stage,stamp,application_id))
        db.execute("INSERT INTO application_events (application_id,kind,occurred_at,recorded_at,details_json) VALUES (?,'stage_changed',?,?,?)", (application_id,occurred_at or stamp,stamp,json.dumps({'old':row['stage'],'new':stage})))


def recover_interrupted(db):
    with transaction(db):
        db.execute("UPDATE preparation_runs SET status='interrupted', finished_at=? WHERE status IN ('queued','running')", (now(),))
        db.execute("UPDATE intake_captures SET status='interrupted' WHERE status IN ('pending','running')")
        db.execute("UPDATE ai_calls SET status='interrupted', finished_at=? WHERE status IN ('pending','running')", (now(),))
        db.execute("UPDATE resume_versions SET status='failed', error_message='Extraction interrupted; retry', updated_at=? WHERE status IN ('uploaded','extracting')", (now(),))


def check(db):
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    foreign = db.execute('PRAGMA foreign_key_check').fetchall()
    if integrity != 'ok' or foreign:
        raise RuntimeError(f'Database integrity failure: {integrity}, foreign keys: {len(foreign)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init','check','backup','restore'])
    parser.add_argument('--database', type=Path, default=DEFAULT_DB)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    if __package__:
        from . import storage
    else:
        import storage
    if args.command == 'restore':
        if args.bundle is None or args.destination is None:
            parser.error('restore requires --bundle and --destination (a new data directory)')
        print(f'restore: ok ({storage.restore(args.bundle, args.destination)})')
        return
    if args.command == 'backup' and args.destination is None:
        parser.error('backup requires --destination')
    if args.command != 'init' and not args.database.is_file():
        parser.error('database does not exist; run init first')
    db = connect(args.database)
    try:
        if args.command == 'init':
            migrate(db)
        elif args.command == 'backup':
            storage.backup(db, args.destination)
        else:
            check(db)
            storage.verify_files(db)
        print(f'{args.command}: ok ({args.database})')
    finally:
        db.close()

if __name__ == '__main__':
    main()
