"""Immutable local artifacts and verified, offline backup/restore bundles."""
from contextlib import closing
import hashlib
import os
import sqlite3
import shutil
import tempfile
import uuid
from pathlib import Path

if __package__:
    from . import database
else:
    import database


def root(db):
    filename = db.execute('PRAGMA database_list').fetchone()[2]
    if not filename:
        raise ValueError('File storage requires an on-disk database')
    return Path(filename).resolve().parent


def resolve(db, relative):
    path = Path(relative)
    base = root(db)
    if path.is_absolute() or not path.parts or '..' in path.parts or path.parts[0] not in {'originals', 'pdfs', 'tmp'}:
        raise ValueError('Expected a relative artifact path')
    target = (base / path).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError('Artifact path escapes data directory')
    return target


def digest(data):
    return hashlib.sha256(data).hexdigest()


def publish(db, data, folder, suffix):
    """Caller holds a write transaction; failed commits may leave an orphan file."""
    relative = f'{folder}/{uuid.uuid4().hex}.{suffix}'
    target = resolve(db, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolve(db, f'tmp/{uuid.uuid4().hex}.tmp')
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    return relative, digest(data)


def verified(db, relative, expected):
    target = resolve(db, relative)
    if not target.is_file() or digest(target.read_bytes()) != expected:
        raise ValueError(f'Missing or changed artifact: {relative}')
    return target


def references(db):
    return list(db.execute('SELECT file_path,sha256 FROM resume_versions UNION SELECT pdf_path,pdf_sha256 FROM document_versions WHERE render_status=\'ready\''))


def verify_files(db):
    for relative, expected in references(db):
        verified(db, relative, expected)


def orphan_files(db):
    known = {resolve(db, row[0]) for row in references(db)}
    return sorted(str(p.relative_to(root(db))) for folder in ('originals', 'pdfs', 'tmp')
                  for p in (root(db) / folder).glob('*') if p.is_file() and p.resolve() not in known)


def backup(db, destination):
    """Reserve writes across snapshot and copies. All Jab writers use this database."""
    destination = Path(destination).resolve()
    base = root(db)
    if destination == base or destination.is_relative_to(base):
        raise ValueError('Backup must be outside the live data directory')
    if destination.exists():
        raise FileExistsError(destination)
    if db.in_transaction:
        raise ValueError('Commit pending work before backup')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.jab-backup-', dir=destination.parent))
    try:
        db.execute('BEGIN IMMEDIATE')
        try:
            # A separate read connection avoids backing up a connection with an open write transaction.
            with closing(sqlite3.connect(
                    f'{Path(db.execute("PRAGMA database_list").fetchone()[2]).as_uri()}?mode=ro', uri=True)) as source:
                target = database.connect(stage / 'jab.sqlite3')
                try:
                    source.backup(target)
                    database.migrate(target)
                    database.check(target)
                    for relative, expected in references(target):
                        src = verified(db, relative, expected)
                        dst = resolve(target, relative)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dst)
                    verify_files(target)
                finally:
                    target.close()
            stage.rename(destination)
        finally:
            db.rollback()
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination


def restore(bundle, destination):
    """Restore into a new data directory; never overwrite the running database."""
    bundle = Path(bundle).resolve()
    if not (bundle / 'jab.sqlite3').is_file():
        raise ValueError('Backup database is missing')
    # backup() validates migration history, integrity and hashes before exposing output.
    source = sqlite3.connect(f'{(bundle / "jab.sqlite3").as_uri()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    source.execute('PRAGMA foreign_keys=ON')
    try:
        return backup(source, destination)
    finally:
        source.close()
