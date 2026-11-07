"""Local HTTP API for Jab's five workflows."""
from contextlib import asynccontextmanager
from email.parser import BytesParser
from email.policy import default
import fcntl
import json
import re
import sqlite3

from fastapi import FastAPI, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import PositiveInt, ValidationError

from .config import ROOT, Settings
from . import database as d, repository as r, storage, schemas as s, rendering
from .errors import BackendError
from .extraction import MAX_UPLOAD
from .service import Service
from .content import upgrade, upgrade_snapshot
from .research import research_history


def decoded(row):
    result = dict(row)
    for key, value in list(result.items()):
        if key.endswith('_json'):
            result[key[:-5]] = json.loads(value) if value is not None else None
            if value is not None and key in ('reviewed_content_json', 'content_json'):
                result[key[:-5]] = upgrade(result[key[:-5]])
            if value is not None and key == 'source_snapshot_json':
                result[key[:-5]] = upgrade_snapshot(result[key[:-5]])
            del result[key]
    return result


def create_app(settings=None, ai=None, fetcher=None):
    cfg = settings or Settings.load()
    service = Service(cfg, ai=ai, fetcher=fetcher)

    @asynccontextmanager
    async def lifespan(app):
        cfg.database.parent.mkdir(parents=True, exist_ok=True)
        lock = (cfg.database.parent / 'backend.lock').open('a')
        try:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Another Jab backend is already managing this data directory') from exc
            with service.connection() as db:
                d.migrate(db)
                d.check(db)
                d.recover_interrupted(db)
                with d.transaction(db):
                    db.execute("UPDATE processing_tasks SET status='interrupted',step='interrupted',error_code='restart_interrupted',error_message='Jab restarted; retry explicitly',finished_at=? WHERE status IN ('queued','running')", (d.now(),))
            service.start()
            app.state.service = service
            yield
        finally:
            await run_in_threadpool(service.stop)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    app = FastAPI(title='Jab local API', version='1.0.0', lifespan=lifespan)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.origins), allow_methods=['GET','POST','PATCH','PUT','DELETE','OPTIONS'], allow_headers=['Content-Type'])

    @app.middleware('http')
    async def local_boundary(request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in cfg.origins and origin not in ('http://localhost:8000','http://127.0.0.1:8000'):
            return JSONResponse(BackendError('origin_not_allowed', 'Use Jab from its configured local origin.', 403).payload(), status_code=403)
        if request.headers.get('content-type', '').startswith('application/json'):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    return JSONResponse(BackendError('request_too_large', 'JSON request exceeds 2 MiB.', 413).payload(), status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        return await call_next(request)

    @app.exception_handler(BackendError)
    async def domain_error(request, exc):
        return JSONResponse(exc.payload(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def input_error(request, exc):
        fields = [{'field': '.'.join(map(str, error['loc'])), 'message': error['msg']} for error in exc.errors()]
        return JSONResponse(BackendError('invalid_input', 'Check the supplied fields.', fields={'issues': fields}).payload(), status_code=422)

    @app.exception_handler(ValidationError)
    async def content_error(request, exc):
        return JSONResponse(BackendError('invalid_content', 'Content does not match the document schema.', fields={'issues': exc.errors(include_input=False, include_url=False)}).payload(), status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        message = str(exc)
        status = 404 if 'not found' in message.lower() else 422
        return JSONResponse(BackendError('not_found' if status == 404 else 'invalid_operation', message, status).payload(), status_code=status)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(BackendError('constraint_violation', 'Required fields, references or lifecycle rules were not satisfied.', 409).payload(), status_code=409)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        busy = 'locked' in str(exc).lower()
        return JSONResponse(BackendError('database_busy' if busy else 'database_error', 'Database is busy; retry shortly.' if busy else 'Database operation failed.', 503 if busy else 500, busy).payload(), status_code=503 if busy else 500)

    def get(table, row_id):
        with service.connection() as db:
            return decoded(r.get(db, table, row_id))

    def listing(table, search='', status=None, stage=None, limit=25, offset=0, owner=None, due_before=None, job_id=None):
        allowed = {'resume_versions','jobs','preparation_runs','document_versions','applications','application_events','processing_tasks','ai_calls','intake_captures','document_validations','activity_events'}
        if table not in allowed:
            raise ValueError('Invalid collection')
        clauses, args = [], []
        if table in ('jobs', 'applications'):
            clauses.append('deleted_at IS NULL')
        if search and table in ('jobs','applications'):
            clauses.append('(company LIKE ? OR ' + ('title' if table == 'jobs' else 'role') + ' LIKE ?)')
            args.extend(['%' + search + '%'] * 2)
        if status:
            clauses.append('status=?'); args.append(status)
        if stage:
            clauses.append('stage=?'); args.append(stage)
        if owner:
            key, value = owner
            clauses.append(key + '=?'); args.append(value)
        if due_before:
            r.day(due_before)
            clauses.append('next_action_due_on<=?'); args.append(due_before)
        if job_id is not None:
            clauses.append('job_id=?'); args.append(job_id)
        where = ' AND '.join(clauses) or '1'
        with service.connection() as db:
            total = db.execute(f'SELECT count(*) FROM {table} WHERE {where}', args).fetchone()[0]
            order = 'occurred_at DESC,id DESC' if table == 'application_events' else 'id DESC'
            rows = db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
        return {'items': [decoded(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/readiness')
    def readiness():
        with service.connection() as db:
            d.check(db)
        return {'database': True, 'renderer': rendering.available(), 'ai_configured': cfg.ai_ready, 'model': cfg.model or None}

    prefix = '/api/v1'

    @app.get(prefix + '/tasks/{task_id}', response_model=s.TaskRecord)
    def task(task_id: PositiveInt):
        return get('processing_tasks', task_id)

    @app.post(prefix + '/resumes', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True, openapi_extra={'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {'type': 'object', 'properties': {'file': {'type': 'string', 'format': 'binary'}}, 'required': ['file']}}}}})
    async def upload(request: Request):
        content_type = request.headers.get('content-type', '')
        if not content_type.lower().startswith('multipart/form-data') or '\r' in content_type or '\n' in content_type:
            raise BackendError('upload_format', 'Use multipart/form-data with one file field.')
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD + 65536:
                raise BackendError('upload_too_large', 'Upload a PDF or DOCX up to 10 MiB.', 413)
            chunks.append(chunk)
        # Bounded standard-library MIME parsing avoids buffering an unbounded multipart upload.
        message = BytesParser(policy=default).parsebytes(('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + b''.join(chunks))
        if not message.is_multipart() or message.defects:
            raise BackendError('upload_format', 'Malformed multipart upload.')
        parts = list(message.iter_parts())
        if len(parts) != 1 or parts[0].get_param('name', header='content-disposition') != 'file' or not parts[0].get_filename():
            raise BackendError('upload_format', 'Supply exactly one file field.')
        data = parts[0].get_payload(decode=True)
        if not data or len(data) > MAX_UPLOAD:
            raise BackendError('upload_too_large', 'Supply a nonempty PDF or DOCX up to 10 MiB.', 413)
        return await run_in_threadpool(service.upload, parts[0].get_filename(), data)

    @app.get(prefix + '/resumes', response_model=s.Page)
    def resumes(status: str | None = None, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        return listing('resume_versions', status=status, limit=limit, offset=offset)

    @app.get(prefix + '/resumes/active')
    def active_resume():
        with service.connection() as db:
            row = db.execute('SELECT * FROM resume_versions WHERE is_active=1').fetchone()
            return decoded(row) if row else None

    @app.get(prefix + '/resumes/{resume_id}')
    def resume(resume_id: PositiveInt):
        row = get('resume_versions', resume_id)
        row['captures'] = listing('intake_captures', owner=('resume_version_id', resume_id))['items']
        row['tasks'] = listing('processing_tasks', owner=('resume_version_id', resume_id))['items']
        return row

    @app.get(prefix + '/resumes/{resume_id}/captures', response_model=s.Page)
    def resume_captures(resume_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('resume_versions', resume_id)
        return listing('intake_captures', owner=('resume_version_id', resume_id), limit=limit, offset=offset)

    @app.get(prefix + '/resumes/{resume_id}/original')
    def original(resume_id: PositiveInt, download: bool = True):
        with service.connection() as db:
            row = r.get(db, 'resume_versions', resume_id)
            path = storage.verified(db, row['file_path'], row['sha256'])
        return FileResponse(path, filename=row['original_filename'], content_disposition_type='attachment' if download else 'inline')

    @app.patch(prefix + '/resumes/{resume_id}/draft')
    def save_resume(resume_id: PositiveInt, body: s.ResumeSave):
        return service.save_resume(resume_id, body.content)

    @app.post(prefix + '/resumes/{resume_id}/activate')
    def activate_resume(resume_id: PositiveInt, body: s.Activate):
        return service.save_resume(resume_id, body.content, activate=True, override_invalid_links=body.override_invalid_links)

    @app.post(prefix + '/resumes/{resume_id}/retry-extraction', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def retry_resume(resume_id: PositiveInt):
        return service.retry_resume(resume_id)

    @app.post(prefix + '/resumes/{resume_id}/reimport', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def reimport_resume(resume_id: PositiveInt):
        return service.reimport_resume(resume_id)

    @app.post(prefix + '/jobs', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def create_job(body: s.JobInput):
        return service.add_job(body)

    @app.get(prefix + '/jobs', response_model=s.Page)
    def jobs(search: str = '', status: str | None = None, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        return listing('jobs', search=search, status=status, limit=limit, offset=offset)

    @app.get(prefix + '/jobs/{job_id}')
    def job(job_id: PositiveInt):
        row = get('jobs', job_id)
        row['captures'] = listing('intake_captures', owner=('job_id', job_id))['items']
        row['tasks'] = listing('processing_tasks', owner=('job_id', job_id))['items']
        with service.connection() as db:
            row['duplicate_job_ids'] = [item[0] for item in db.execute('SELECT id FROM jobs WHERE deleted_at IS NULL AND id!=? AND ((source_url IS NOT NULL AND source_url=?) OR (company IS NOT NULL AND lower(company)=lower(?) AND lower(title)=lower(?)))', (job_id, row['source_url'], row['company'], row['title']))]
            row['active_tasks'] = [decoded(task) for task in db.execute("SELECT t.* FROM processing_tasks t LEFT JOIN document_versions doc ON doc.id=t.document_id LEFT JOIN preparation_runs p ON p.id=coalesce(t.run_id,doc.run_id) WHERE (t.job_id=? OR p.job_id=?) AND t.status IN ('queued','running') ORDER BY t.id DESC", (job_id, job_id))]
        return row

    @app.get(prefix + '/jobs/{job_id}/captures', response_model=s.Page)
    def job_captures(job_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('jobs', job_id)
        return listing('intake_captures', owner=('job_id', job_id), limit=limit, offset=offset)

    @app.delete(prefix + '/jobs/{job_id}')
    def delete_job(job_id: PositiveInt):
        return decoded(service.delete_job(job_id))

    @app.get(prefix + '/jobs/{job_id}/activity', response_model=s.Page)
    def job_activity(job_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('jobs', job_id)
        return listing('activity_events', owner=('job_id', job_id), limit=limit, offset=offset)

    @app.patch(prefix + '/jobs/{job_id}')
    def edit_job(job_id: PositiveInt, body: s.JobFields):
        return decoded(service.save_job(job_id, body))

    @app.post(prefix + '/jobs/{job_id}/confirm')
    def confirm_job(job_id: PositiveInt):
        return decoded(service.save_job(job_id, None, confirm=True))

    @app.post(prefix + '/jobs/{job_id}/archive')
    def archive_job(job_id: PositiveInt):
        return decoded(service.save_job(job_id, None, archive=True))

    @app.post(prefix + '/jobs/{job_id}/intake', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def job_intake(job_id: PositiveInt, body: s.JobInput):
        return service.intake_job(job_id, body)

    @app.post(prefix + '/jobs/{job_id}/runs', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def start_run(job_id: PositiveInt, body: s.Instructions = s.Instructions()):
        return service.start_generation(job_id, body.instructions)

    @app.get(prefix + '/jobs/{job_id}/runs', response_model=s.Page)
    def runs(job_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('jobs', job_id)
        return listing('preparation_runs', owner=('job_id', job_id), limit=limit, offset=offset)

    @app.get(prefix + '/jobs/{job_id}/documents', response_model=s.Page)
    def job_documents(job_id: PositiveInt, status: str | None = None, kind: str | None = None,
                      limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        if kind not in (None, 'resume', 'cover_letter'):
            raise ValueError('Unknown document type')
        with service.connection() as db:
            rows, total = r.job_documents(db, job_id, kind=kind, status=status, limit=limit, offset=offset)
        return {'items': [decoded(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    @app.get(prefix + '/jobs/{job_id}/document-selections')
    def document_selections(job_id: PositiveInt):
        with service.connection() as db:
            selected = r.document_selections(db, job_id)
            for doc in selected.values():
                if doc:
                    doc['version_number'] = r.document_version_number(db, doc['id'])
        return {kind: decoded(doc) if doc else None for kind, doc in selected.items()}

    @app.post(prefix + '/jobs/{job_id}/document-selections')
    def select_document(job_id: PositiveInt, body: s.DocumentSelection):
        with service.connection() as db:
            r.select_document(db, job_id, body.document_id)
        return document_selections(job_id)

    @app.get(prefix + '/runs/{run_id}')
    def run(run_id: PositiveInt):
        row = get('preparation_runs', run_id)
        row['documents'] = listing('document_versions', owner=('run_id', run_id), limit=100)['items']
        row['ai_calls'] = listing('ai_calls', owner=('run_id', run_id), limit=100)['items']
        summary = research_history(row['ai_calls'])
        summary['sources'] = [{key: page[key] for key in ('url', 'title', 'fetched_at')} for page in summary['sources']]
        row['research'] = summary
        row['tasks'] = listing('processing_tasks', owner=('run_id', run_id))['items']
        return row

    @app.get(prefix + '/runs/{run_id}/documents', response_model=s.Page)
    def documents(run_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('preparation_runs', run_id)
        return listing('document_versions', owner=('run_id', run_id), limit=limit, offset=offset)

    @app.get(prefix + '/documents/{document_id}')
    def document(document_id: PositiveInt):
        row = get('document_versions', document_id)
        with service.connection() as db:
            row['version_number'] = r.document_version_number(db, document_id)
            origin = r.get(db, 'preparation_runs', row['run_id'])
            row['source_resume'] = upgrade_snapshot(json.loads(origin['source_snapshot_json']))['resume']
        row['validations'] = listing('document_validations', owner=('document_id', document_id), limit=100)['items']
        row['tasks'] = listing('processing_tasks', owner=('document_id', document_id))['items']
        return row

    @app.post(prefix + '/documents/{document_id}/revisions', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def manual_revision(document_id: PositiveInt, body: s.DocumentSave):
        return service.save_document(document_id, body.content)

    @app.post(prefix + '/documents/{document_id}/ai-revisions', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def ai_revision(document_id: PositiveInt, body: s.RevisionRequest):
        with service.connection() as db:
            doc = r.get(db, 'document_versions', document_id)
            run = r.get(db, 'preparation_runs', doc['run_id'])
        return service.start_generation(run['job_id'], body.instructions, source_document_id=document_id)

    @app.post(prefix + '/documents/{document_id}/render', status_code=202, response_model=s.TaskAccepted, response_model_exclude_none=True)
    def retry_render(document_id: PositiveInt):
        return service.retry_render(document_id)

    @app.get(prefix + '/documents/{document_id}/pdf')
    def pdf(document_id: PositiveInt, download: bool = True):
        with service.connection() as db:
            row = r.get(db, 'document_versions', document_id)
            path = r.download_pdf(db, document_id)
            origin = r.get(db, 'preparation_runs', row['run_id'])
            name = upgrade_snapshot(json.loads(origin['source_snapshot_json']))['resume']['contact']['name']
        name = ' '.join(re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', ' ', name).split()).strip(' .') or 'Candidate'
        label = 'resume' if row['kind'] == 'resume' else 'cover letter'
        return FileResponse(path, media_type='application/pdf', filename=f'{name}_{label}.pdf', content_disposition_type='attachment' if download else 'inline')

    @app.get(prefix + '/captures/{capture_id}/ai-calls', response_model=s.Page)
    def capture_calls(capture_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('intake_captures', capture_id)
        return listing('ai_calls', owner=('intake_capture_id', capture_id), limit=limit, offset=offset)

    @app.post(prefix + '/applications', status_code=201)
    def record_application(body: s.ApplicationInput):
        with service.connection() as db:
            app_id = d.record_application(db, **body.model_dump(mode='json'))
            return decoded(r.get(db, 'applications', app_id))

    @app.get(prefix + '/applications', response_model=s.Page)
    def applications(search: str = '', stage: s.Stage | None = None, due_before: str | None = None, job_id: PositiveInt | None = None, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        return listing('applications', search=search, stage=stage, due_before=due_before, job_id=job_id, limit=limit, offset=offset)

    @app.get(prefix + '/applications/{application_id}')
    def application(application_id: PositiveInt):
        return get('applications', application_id)

    @app.delete(prefix + '/applications/{application_id}')
    def delete_application(application_id: PositiveInt):
        with service.connection() as db:
            return decoded(r.soft_delete(db, 'applications', application_id))

    @app.get(prefix + '/applications/{application_id}/activity', response_model=s.Page)
    def application_activity(application_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('applications', application_id)
        return listing('activity_events', owner=('application_id', application_id), limit=limit, offset=offset)

    @app.get(prefix + '/applications/{application_id}/events', response_model=s.Page)
    def events(application_id: PositiveInt, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        get('applications', application_id)
        return listing('application_events', owner=('application_id', application_id), limit=limit, offset=offset)

    @app.post(prefix + '/applications/{application_id}/stage')
    def stage(application_id: PositiveInt, body: s.StageChange):
        with service.connection() as db:
            d.change_stage(db, application_id, body.stage, body.occurred_at.isoformat() if body.occurred_at else None)
            return decoded(r.get(db, 'applications', application_id))

    @app.post(prefix + '/applications/{application_id}/notes', status_code=201)
    def note(application_id: PositiveInt, body: s.Note):
        with service.connection() as db:
            event = r.add_note(db, application_id, body.note, occurred_at=body.occurred_at.isoformat() if body.occurred_at else None)
            return decoded(r.get(db, 'application_events', event))

    @app.put(prefix + '/applications/{application_id}/follow-up')
    def follow_up(application_id: PositiveInt, body: s.FollowUp):
        with service.connection() as db:
            r.update_followup(db, application_id, next_action=body.next_action, due_on=body.due_on.isoformat() if body.due_on else None)
            return decoded(r.get(db, 'applications', application_id))

    @app.post(prefix + '/applications/{application_id}/corrections')
    def correction(application_id: PositiveInt, body: s.Correction):
        fields = body.model_dump(mode='json', exclude_unset=True)
        reason = fields.pop('reason')
        if any(fields.get(key, 'missing') is None for key in ('company','role')):
            raise BackendError('invalid_correction', 'Company and role cannot be cleared.')
        with service.connection() as db:
            r.correct_application(db, application_id, reason=reason, **fields)
            return decoded(r.get(db, 'applications', application_id))

    frontend = ROOT / 'frontend' / 'dist'
    if (frontend / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='frontend-assets')

    @app.get('/', include_in_schema=False)
    def workspace():
        if not (frontend / 'index.html').is_file():
            raise BackendError('frontend_not_built', 'Build the frontend first: cd frontend && npm ci && npm run build, then restart Jab.', 503)
        return FileResponse(frontend / 'index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/favicon.svg', include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / 'frontend' / 'public' / 'favicon.svg', media_type='image/svg+xml')

    return app


app = create_app()
