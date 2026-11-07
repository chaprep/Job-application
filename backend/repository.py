"""Workflow persistence; network calls, parsing and PDF compilation happen outside transactions."""
import json
from datetime import date, datetime
from pathlib import Path

if __package__:
    from . import database as dbcore, storage
    from .content import upgrade
else:
    import database as dbcore
    import storage
    from content import upgrade

JOB_FIELDS = {'company', 'title', 'location', 'expected_salary', 'advertised_salary',
              'employment_type', 'application_deadline', 'recruiter_details', 'job_reference',
              'tailoring_instructions', 'source_url', 'jd_text', 'requirements_json'}
TABLES = {'resume_versions', 'jobs', 'preparation_runs', 'document_versions',
          'applications', 'application_events', 'intake_captures', 'ai_calls', 'document_validations', 'processing_tasks', 'activity_events'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def content(value):
    if not isinstance(value, dict) or not value:
        raise ValueError('Content must be a nonempty JSON object')
    return encode(value)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} is required')
    return value


def day(value):
    if value is not None:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError('Date must use YYYY-MM-DD')
    return value


def timestamp(value):
    if value is not None:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError('Event time must include a timezone')
    return value


def get(db, table, row_id):
    if table not in TABLES:
        raise ValueError('Unknown entity')
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (row_id,)).fetchone()
    if row is None:
        raise ValueError(f'{table} record not found')
    return dict(row)


def history(db, table, **filters):
    if table not in TABLES:
        raise ValueError('Unknown entity')
    columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
    if not set(filters) <= columns:
        raise ValueError('Unknown filter')
    where = ' AND '.join(f'{key} IS ?' for key in filters) or '1'
    return [dict(row) for row in db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY id', tuple(filters.values()))]


def job_documents(db, job_id, *, kind=None, status=None, limit=25, offset=0):
    get(db, 'jobs', job_id)
    query = """WITH versions AS (
        SELECT doc.*,row_number() OVER (PARTITION BY doc.kind ORDER BY doc.id) AS version_number
        FROM document_versions doc JOIN preparation_runs p ON p.id=doc.run_id WHERE p.job_id=?)
        SELECT * FROM versions"""
    filters, args = [], [job_id]
    for field, value in (('kind', kind), ('render_status', status)):
        if value:
            filters.append(field + '=?')
            args.append(value)
    if filters:
        query += ' WHERE ' + ' AND '.join(filters)
    total = db.execute('SELECT count(*) FROM (' + query + ')', args).fetchone()[0]
    rows = db.execute(query + ' ORDER BY id DESC LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
    return [dict(row) for row in rows], total


def document_selections(db, job_id):
    get(db, 'jobs', job_id)
    result = {'resume': None, 'cover_letter': None}
    for row in db.execute('SELECT kind,document_id FROM job_document_selections WHERE job_id=?', (job_id,)):
        result[row['kind']] = get(db, 'document_versions', row['document_id'])
    return result


def select_document(db, job_id, document_id):
    with dbcore.transaction(db):
        if get(db, 'jobs', job_id)['deleted_at']:
            raise ValueError('Deleted job is read-only')
        doc = get(db, 'document_versions', document_id)
        if get(db, 'preparation_runs', doc['run_id'])['job_id'] != job_id:
            raise ValueError('Selected document must belong to this job')
        db.execute('INSERT INTO job_document_selections(job_id,kind,document_id) VALUES (?,?,?) '
                   'ON CONFLICT(job_id,kind) DO UPDATE SET document_id=excluded.document_id',
                   (job_id, doc['kind'], document_id))
    return doc


def document_version_number(db, document_id):
    return db.execute("""SELECT count(*) FROM document_versions doc
        JOIN preparation_runs p ON p.id=doc.run_id
        JOIN document_versions selected ON selected.id=?
        JOIN preparation_runs origin ON origin.id=selected.run_id
        WHERE p.job_id=origin.job_id AND doc.kind=selected.kind AND doc.id<=selected.id""",
        (document_id,)).fetchone()[0]

def upload_resume(db, filename, data):
    text(filename, 'Filename')
    extension = Path(filename).suffix.lower()[1:]
    if extension not in ('pdf', 'docx') or not isinstance(data, bytes) or not data:
        raise ValueError('A nonempty PDF or DOCX upload is required')
    # Full parser validation belongs to extraction; reject obvious format mismatches here.
    if not data.startswith(b'%PDF-' if extension == 'pdf' else b'PK\x03\x04'):
        raise ValueError('Upload does not match its file type')
    stamp = dbcore.now()
    with dbcore.transaction(db):
        path, sha = storage.publish(db, data, 'originals', extension)
        return db.execute('INSERT INTO resume_versions(original_filename,file_path,file_type,sha256,status,created_at,updated_at) VALUES (?,?,?,?,\'uploaded\',?,?)',
                          (Path(filename).name, path, extension, sha, stamp, stamp)).lastrowid


def start_extraction(db, resume_id):
    with dbcore.transaction(db):
        if db.execute("UPDATE resume_versions SET status='extracting',error_message=NULL,updated_at=? WHERE id=? AND status IN ('uploaded','failed')", (dbcore.now(), resume_id)).rowcount != 1:
            raise ValueError('Resume cannot start extraction')


def finish_extraction(db, resume_id, extracted_text=None, reviewed_content=None, error=None):
    if not error:
        text(extracted_text, 'Extracted text')
        body = content(reviewed_content)
    else:
        body = None
        extracted_text = None  # Preserve failed attempt text in its capture, allowing extraction retry.
    with dbcore.transaction(db):
        if db.execute('UPDATE resume_versions SET extracted_text=?,reviewed_content_json=?,status=?,error_message=?,updated_at=? WHERE id=? AND status IN (\'uploaded\',\'extracting\',\'failed\') AND extracted_text IS NULL',
                      (extracted_text, body, 'failed' if error else 'needs_review', error, dbcore.now(), resume_id)).rowcount != 1:
            raise ValueError('Resume extraction is already complete or not found')


def save_resume_draft(db, resume_id, reviewed_content):
    body = content(reviewed_content)
    stamp = dbcore.now()
    with dbcore.transaction(db):
        row = get(db, 'resume_versions', resume_id)
        if row['status'] == 'ready':
            return db.execute("INSERT INTO resume_versions(original_filename,file_path,file_type,sha256,extracted_text,reviewed_content_json,status,created_at,updated_at,parent_resume_id) VALUES (?,?,?,?,?,?,'needs_review',?,?,?)",
                              (row['original_filename'], row['file_path'], row['file_type'], row['sha256'], row['extracted_text'], body, stamp, stamp, resume_id)).lastrowid
        if row['status'] != 'needs_review':
            raise ValueError('Extract the resume before editing')
        db.execute('UPDATE resume_versions SET reviewed_content_json=?,updated_at=? WHERE id=?', (body, stamp, resume_id))
        return resume_id


def create_job(db, *, source_type, source_url=None, jd_text=None):
    with dbcore.transaction(db):
        stamp = dbcore.now()
        job_id = db.execute("INSERT INTO jobs(source_type,source_url,jd_text,status,created_at,updated_at) VALUES (?,?,?,'needs_review',?,?)", (source_type, source_url, jd_text, stamp, stamp)).lastrowid
        db.execute("INSERT INTO activity_events(job_id,kind,created_at) VALUES (?,'created',?)", (job_id, stamp))
        return job_id


def save_job(db, job_id, *, confirm=False, archive=False, **fields):
    if not set(fields) <= JOB_FIELDS or (confirm and archive):
        raise ValueError('Invalid job update')
    for key, value in fields.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f'{key} must be text')
    with dbcore.transaction(db):
        old = get(db, 'jobs', job_id)
        if old['deleted_at']:
            raise ValueError('Deleted job is read-only')
        fields.update(status='archived' if archive else 'ready' if confirm else 'needs_review', updated_at=dbcore.now())
        db.execute(f'UPDATE jobs SET {",".join(key+"=?" for key in fields)} WHERE id=?', (*fields.values(), job_id))
        changes = {key: value for key, value in fields.items() if key != 'updated_at' and old[key] != value}
        db.execute('INSERT INTO activity_events(job_id,kind,details_json,created_at) VALUES (?,?,?,?)',
                   (job_id, 'archived' if archive else 'confirmed' if confirm else 'updated',
                    encode({'old': {key: old[key] for key in changes}, 'new': changes}), fields['updated_at']))


def soft_delete(db, table, row_id):
    if table not in ('jobs', 'applications'):
        raise ValueError('Invalid deletion target')
    with dbcore.transaction(db):
        row = get(db, table, row_id)
        if row['deleted_at'] is None:
            stamp = dbcore.now()
            db.execute(f'UPDATE {table} SET deleted_at=?,updated_at=? WHERE id=?', (stamp, stamp, row_id))
        return get(db, table, row_id)


def create_capture(db, *, capture_type, resume_version_id=None, job_id=None, supplied_url=None):
    with dbcore.transaction(db):
        return db.execute("INSERT INTO intake_captures(resume_version_id,job_id,capture_type,supplied_url,status,created_at) VALUES (?,?,?,?,'pending',?)", (resume_version_id, job_id, capture_type, supplied_url, dbcore.now())).lastrowid


def start_capture(db, capture_id):
    with dbcore.transaction(db):
        if db.execute("UPDATE intake_captures SET status='running' WHERE id=? AND status='pending'", (capture_id,)).rowcount != 1:
            raise ValueError('Only pending captures can start')


def finish_capture(db, capture_id, *, captured_text=None, error=None):
    if not error:
        text(captured_text, 'Captured text')
    with dbcore.transaction(db):
        db.execute('UPDATE intake_captures SET captured_text=?,status=?,error_message=? WHERE id=?',
                   (captured_text, 'failed' if error else 'succeeded', error, get(db, 'intake_captures', capture_id)['id']))


def create_run(db, *, job_id, resume_version_id=None, source_document_id=None, instructions=None,
               provider=None, model=None, prompt_version=None, template_version=None):
    with dbcore.transaction(db):
        job = get(db, 'jobs', job_id)
        if job['deleted_at']:
            raise ValueError('Deleted job is read-only')
        if resume_version_id is None:
            active = db.execute('SELECT id FROM resume_versions WHERE is_active=1').fetchone()
            if active is None:
                raise ValueError('Confirm an active base resume first')
            resume_version_id = active[0]
        resume = get(db, 'resume_versions', resume_version_id)
        if job['status'] != 'ready' or resume['status'] != 'ready':
            raise ValueError('Reviewed resume and job are required')
        job_snapshot = dict(job)
        if 'requirements_json' in job_snapshot:
            job_snapshot['requirements'] = json.loads(job_snapshot.pop('requirements_json') or '{}')
        snapshot = {'resume': upgrade(json.loads(resume['reviewed_content_json'])), 'job': job_snapshot, 'instructions': instructions}
        if resume['validation_overrides_json']:
            snapshot['resume_validation_overrides'] = json.loads(resume['validation_overrides_json'])
        if source_document_id is not None:
            text(instructions, 'Revision instructions')
            source = get(db, 'document_versions', source_document_id)
            if get(db, 'preparation_runs', source['run_id'])['job_id'] != job_id:
                raise ValueError('Revision must belong to this job')
            snapshot['source_document'] = {'id': source_document_id, 'kind': source['kind'], 'content': upgrade(json.loads(source['content_json']))}
            other_kind = 'cover_letter' if source['kind'] == 'resume' else 'resume'
            companion = document_selections(db, job_id)[other_kind]
            if companion:
                snapshot['companion_document'] = {'id': companion['id'], 'kind': companion['kind'],
                                                  'content': upgrade(json.loads(companion['content_json']))}
        return db.execute("INSERT INTO preparation_runs(job_id,resume_version_id,source_document_id,source_snapshot_json,status,provider,model,prompt_version,template_version,created_at) VALUES (?,?,?,?,'queued',?,?,?,?,?)",
                          (job_id, resume_version_id, source_document_id, encode(snapshot), provider, model, prompt_version, template_version, dbcore.now())).lastrowid


def start_run(db, run_id):
    with dbcore.transaction(db):
        if db.execute("UPDATE preparation_runs SET status='running',started_at=? WHERE id=? AND status='queued'", (dbcore.now(), run_id)).rowcount != 1:
            raise ValueError('Only queued runs can start')


def finish_run(db, run_id, *, findings=None, error=None):
    with dbcore.transaction(db):
        if get(db, 'preparation_runs', run_id)['status'] != 'running':
            raise ValueError('Only running runs can finish')
        docs = db.execute('SELECT kind,render_status FROM document_versions WHERE id IN (SELECT max(id) FROM document_versions WHERE run_id=? GROUP BY kind)', (run_id,)).fetchall()
        ready = sum(row['render_status'] == 'ready' for row in docs)
        expected = 1 if get(db, 'preparation_runs', run_id)['source_document_id'] else 2
        status = 'succeeded' if ready == expected else 'partial' if ready else 'failed'
        db.execute('UPDATE preparation_runs SET status=?,review_findings_json=?,error_message=?,finished_at=? WHERE id=?', (status, encode(findings) if findings is not None else None, error, dbcore.now(), run_id))
        return status


def check_payload(value):
    """Reject credential fields before recording a provider payload."""
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower().replace('-', '_') in {
                    'authorization', 'api_key', 'apikey', 'x_api_key', 'password',
                    'access_token', 'refresh_token', 'secret', 'headers'}:
                raise ValueError('Pass model input only; omit credentials and transport headers')
            check_payload(child)
    elif isinstance(value, list):
        for child in value:
            check_payload(child)


def create_ai_call(db, *, purpose, provider, model, request, intake_capture_id=None, run_id=None):
    for label, value in (('purpose', purpose), ('provider', provider), ('model', model)):
        text(value, label)
    # The caller passes only the model payload, never headers, API keys or environment data.
    check_payload(request)
    body = content(request)
    with dbcore.transaction(db):
        if run_id is not None and get(db, 'preparation_runs', run_id)['status'] != 'running' and purpose not in ('review_document', 'repair_review_document'):
            raise ValueError('AI generation requires a running attempt')
        if intake_capture_id is not None and get(db, 'intake_captures', intake_capture_id)['status'] not in ('pending','running','succeeded'):
            raise ValueError('Cannot use failed intake')
        return db.execute("INSERT INTO ai_calls(intake_capture_id,run_id,purpose,provider,model,request_json,status,started_at) VALUES (?,?,?,?,?,?,'running',?)", (intake_capture_id, run_id, purpose, provider, model, body, dbcore.now())).lastrowid


def finish_ai_call(db, call_id, *, raw_response=None, validated_response=None, token_usage=None, error=None):
    if not error:
        text(raw_response, 'Raw AI response')
        content(validated_response)
    with dbcore.transaction(db):
        get(db, 'ai_calls', call_id)
        db.execute('UPDATE ai_calls SET raw_response=?,validated_response_json=?,token_usage_json=?,status=?,error_message=?,finished_at=? WHERE id=?',
                   (raw_response, encode(validated_response) if validated_response is not None else None, encode(token_usage) if token_usage is not None else None, 'failed' if error else 'succeeded', error, dbcore.now(), call_id))


def save_document(db, run_id, kind, document_content, *, parent_document_id=None, ai_call_id=None):
    body = content(document_content)
    with dbcore.transaction(db):
        run = get(db, 'preparation_runs', run_id)
        if run['status'] == 'queued':
            raise ValueError('Start the run before saving results')
        if parent_document_id is None:
            latest = db.execute('SELECT id FROM document_versions WHERE run_id=? AND kind=? ORDER BY revision DESC LIMIT 1', (run_id, kind)).fetchone()
            parent_document_id = latest[0] if latest else run['source_document_id']
            if parent_document_id and get(db, 'document_versions', parent_document_id)['kind'] != kind:
                parent_document_id = None
        revision = db.execute('SELECT coalesce(max(revision),0)+1 FROM document_versions WHERE run_id=? AND kind=?', (run_id, kind)).fetchone()[0]
        return db.execute("INSERT INTO document_versions(run_id,parent_document_id,kind,revision,content_json,render_status,created_at,ai_call_id) VALUES (?,?,?,?,?,'pending',?,?)", (run_id, parent_document_id, kind, revision, body, dbcore.now(), ai_call_id)).lastrowid


def add_validation(db, document_id, check_type, result, findings, *, ai_call_id=None):
    with dbcore.transaction(db):
        return db.execute('INSERT INTO document_validations(document_id,check_type,result,findings_json,ai_call_id,created_at) VALUES (?,?,?,?,?,?)', (document_id, check_type, result, encode(findings), ai_call_id, dbcore.now())).lastrowid


def render_failed(db, document_id, error):
    text(error, 'Rendering error')
    with dbcore.transaction(db):
        get(db, 'document_versions', document_id)
        db.execute("UPDATE document_versions SET render_status='failed',render_error=? WHERE id=?", (error, document_id))


def publish_pdf(db, document_id, pdf_bytes):
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b'%PDF-'):
        raise ValueError('Expected PDF bytes')
    with dbcore.transaction(db):
        row = get(db, 'document_versions', document_id)
        if row['render_status'] == 'ready':
            raise ValueError('Ready PDFs cannot be replaced')
        path, sha = storage.publish(db, pdf_bytes, 'pdfs', 'pdf')
        db.execute("UPDATE document_versions SET pdf_path=?,pdf_sha256=?,render_status='ready',render_error=NULL,rendered_at=? WHERE id=?", (path, sha, dbcore.now(), document_id))
        select_document(db, get(db, 'preparation_runs', row['run_id'])['job_id'], document_id)


def download_pdf(db, document_id):
    row = get(db, 'document_versions', document_id)
    if row['render_status'] != 'ready':
        raise ValueError('PDF is not ready')
    return storage.verified(db, row['pdf_path'], row['pdf_sha256'])


def event(db, application_id, kind, *, note=None, details=None, occurred_at=None):
    return db.execute('INSERT INTO application_events(application_id,kind,occurred_at,recorded_at,note,details_json) VALUES (?,?,?,?,?,?)',
                      (application_id, kind, timestamp(occurred_at) or dbcore.now(), dbcore.now(), note, encode(details) if details is not None else None)).lastrowid


def add_note(db, application_id, note, *, occurred_at=None):
    text(note, 'Note')
    with dbcore.transaction(db):
        get(db, 'applications', application_id)
        return event(db, application_id, 'note_added', note=note, occurred_at=occurred_at)


def update_followup(db, application_id, *, next_action=None, due_on=None):
    day(due_on)
    if due_on is not None:
        text(next_action, 'Follow-up action')
    with dbcore.transaction(db):
        row = get(db, 'applications', application_id)
        db.execute('UPDATE applications SET next_action=?,next_action_due_on=?,updated_at=? WHERE id=?', (next_action, due_on, dbcore.now(), application_id))
        event(db, application_id, 'next_action_changed', details={'old': {'action': row['next_action'], 'due_on': row['next_action_due_on']}, 'new': {'action': next_action, 'due_on': due_on}})


def correct_application(db, application_id, *, reason, **fields):
    text(reason, 'Correction reason')
    allowed = {'company', 'role', 'application_url', 'applied_on', 'resume_document_id', 'cover_letter_document_id'}
    if not fields or not set(fields) <= allowed:
        raise ValueError('Invalid correction fields')
    day(fields.get('applied_on'))
    with dbcore.transaction(db):
        old = get(db, 'applications', application_id)
        merged = {**old, **fields}
        dbcore.validate_submission(db, merged['job_id'], merged['resume_document_id'], merged['cover_letter_document_id'])
        db.execute(f'UPDATE applications SET {",".join(key+"=?" for key in fields)},updated_at=? WHERE id=?', (*fields.values(), dbcore.now(), application_id))
        kind = 'submission_corrected' if {'resume_document_id', 'cover_letter_document_id'} & fields.keys() else 'details_corrected'
        event(db, application_id, kind, note=reason, details={'old': {key: old[key] for key in fields}, 'new': fields})
