"""Five workflows: orchestration owns model calls, checks, tasks and state changes."""
from contextlib import contextmanager
from datetime import date
import json
import logging
import sqlite3
import threading
import time

from . import database as d, repository as r, storage, schemas as s, validation as v, rendering
from .ai import AI, PROMPT_VERSION
from .errors import BackendError
from .extraction import extract
from .fetching import fetch_job_zyte
from .research import Research, research_history
from .content import upgrade, upgrade_snapshot, freeze_link_ids

log = logging.getLogger('jab.tasks')


class Service:
    def __init__(self, settings, ai=None, fetcher=None):
        self.settings = settings
        self.ai = ai or AI(settings)
        self.fetcher = fetcher or (lambda url: fetch_job_zyte(url, settings.zyte_api_key))
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = None

    @contextmanager
    def connection(self):
        db = d.connect(self.settings.database)
        try:
            yield db
        finally:
            db.close()

    def start(self):
        self.thread = threading.Thread(target=self.work, name='jab-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join()

    def require_ai(self):
        if not self.settings.ai_ready:
            raise BackendError('ai_not_configured', 'Configure provider URL, model ID and API key in .env, then restart.', 503)

    def ensure_idle(self, db, **owners):
        conditions, params = [], []
        for key, value in owners.items():
            conditions.append(key + '=?')
            params.append(value)
        if db.execute("SELECT id FROM processing_tasks WHERE status IN ('queued','running') AND (" + ' OR '.join(conditions) + ')', params).fetchone():
            raise BackendError('operation_in_progress', 'Work is already in progress for this resource.', 409)

    def ensure_job_idle(self, db, job_id):
        if r.get(db, 'jobs', job_id)['deleted_at']:
            raise BackendError('job_deleted', 'This job has been deleted and is read-only.', 409)
        self.ensure_idle(db, job_id=job_id)
        if db.execute("SELECT t.id FROM processing_tasks t LEFT JOIN document_versions doc ON doc.id=t.document_id JOIN preparation_runs p ON p.id=coalesce(t.run_id,doc.run_id) WHERE p.job_id=? AND t.status IN ('queued','running')", (job_id,)).fetchone():
            raise BackendError('operation_in_progress', 'A generation or revision is already running for this job.', 409)

    def task(self, db, action, owner, row_id, inputs=None):
        allowed = {'resume_version_id','job_id','run_id','document_id'}
        if owner not in allowed:
            raise ValueError('Invalid task owner')
        self.ensure_idle(db, **{owner: row_id})
        task_id = db.execute(f'INSERT INTO processing_tasks(action,{owner},input_json,created_at) VALUES (?,?,?,?)', (action, row_id, r.encode(inputs or {}), d.now())).lastrowid
        return {'task_id': task_id, owner: row_id}

    def upload(self, filename, data):
        # Readability is checked before a task is accepted; extraction is repeated from the preserved file.
        extension = filename.rsplit('.', 1)[-1].lower()
        if extension not in ('pdf','docx'):
            raise BackendError('unsupported_upload', 'Upload a PDF or DOCX resume.')
        extract(data, extension)
        with self.connection() as db, d.transaction(db):
            resume = r.upload_resume(db, filename, data)
            result = self.task(db, 'extract_resume', 'resume_version_id', resume)
        self.wake.set()
        return result

    def retry_resume(self, resume_id):
        with self.connection() as db, d.transaction(db):
            row = r.get(db, 'resume_versions', resume_id)
            self.ensure_idle(db, resume_version_id=resume_id)
            if row['status'] not in ('failed','uploaded'):
                raise BackendError('resume_state', 'Only failed or unprocessed uploads can be extracted again.', 409)
            result = self.task(db, 'extract_resume', 'resume_version_id', resume_id)
        self.wake.set()
        return result

    def reimport_resume(self, resume_id):
        with self.connection() as db, d.transaction(db):
            original = r.get(db, 'resume_versions', resume_id)
            self.ensure_idle(db, resume_version_id=resume_id)
            if db.execute("SELECT t.id FROM processing_tasks t JOIN resume_versions v ON v.id=t.resume_version_id WHERE v.sha256=? AND t.status IN ('queued','running')", (original['sha256'],)).fetchone():
                raise BackendError('operation_in_progress', 'This original is already being re-imported.', 409)
            stamp = d.now()
            version = db.execute("INSERT INTO resume_versions(original_filename,file_path,file_type,sha256,parent_resume_id,status,created_at,updated_at) VALUES (?,?,?,?,?,'uploaded',?,?)", (original['original_filename'], original['file_path'], original['file_type'], original['sha256'], resume_id, stamp, stamp)).lastrowid
            result = self.task(db, 'extract_resume', 'resume_version_id', version)
        self.wake.set()
        return result

    def save_resume(self, resume_id, content, activate=False, override_invalid_links=False):
        body = freeze_link_ids(content.model_dump()) if activate else content.model_dump()
        failures = v.structure(body, 'resume')
        link_issues = [f for f in failures if v.is_link_finding(f)]
        blocking = [f for f in failures if not (override_invalid_links and v.is_link_finding(f))]
        if activate and blocking:
            raise BackendError('resume_validation', 'Resolve the resume issues before activation.', fields={'findings': failures, 'can_override_links': bool(link_issues) and len(link_issues) == len(failures)})
        overrides = [{**f, 'severity': 'warning', 'explanation': 'You chose to keep this link as entered. It will appear as plain text in PDFs.'} for f in link_issues] if activate and override_invalid_links else []
        with self.connection() as db, d.transaction(db):
            self.ensure_idle(db, resume_version_id=resume_id)
            row = r.get(db, 'resume_versions', resume_id)
            if row['status'] not in ('ready','needs_review'):
                raise BackendError('resume_state', 'Complete extraction before saving the resume.', 409)
            version = r.save_resume_draft(db, resume_id, body)
            if activate:
                db.execute('UPDATE resume_versions SET validation_overrides_json=? WHERE id=?', (r.encode(overrides) if overrides else None, version))
                d.activate_resume(db, version, body)
        return {'resume_version_id': version, 'status': 'ready' if activate else 'needs_review', 'findings': overrides if overrides else failures}

    def add_job(self, input):
        if input.source_type == 'url':
            from .fetching import public_target
            public_target(input.source_url)
        with self.connection() as db, d.transaction(db):
            job = r.create_job(db, **input.model_dump())
            result = self.task(db, 'intake_job', 'job_id', job, {'source_type': input.source_type, 'jd_text': input.jd_text, 'source_url': input.source_url})
        self.wake.set()
        return result

    def intake_job(self, job_id, input):
        if input.source_type == 'url':
            from .fetching import public_target
            public_target(input.source_url)
        with self.connection() as db, d.transaction(db):
            self.ensure_job_idle(db, job_id)
            job = r.get(db, 'jobs', job_id)
            if job['status'] == 'archived':
                raise BackendError('job_archived', 'Restore job details before running intake.', 409)
            result = self.task(db, 'intake_job', 'job_id', job_id, input.model_dump())
        self.wake.set()
        return result

    def save_job(self, job_id, fields, confirm=False, archive=False):
        values = fields.model_dump(mode='json', exclude_unset=True) if fields else {}
        if 'requirements' in values:
            values['requirements_json'] = r.encode(values.pop('requirements') or {})
        with self.connection() as db, d.transaction(db):
            self.ensure_job_idle(db, job_id)
            r.get(db, 'jobs', job_id)
            r.save_job(db, job_id, confirm=confirm, archive=archive, **values)
            return r.get(db, 'jobs', job_id)

    def delete_job(self, job_id):
        with self.connection() as db, d.transaction(db):
            row = r.get(db, 'jobs', job_id)
            if not row['deleted_at']:
                self.ensure_job_idle(db, job_id)
            return r.soft_delete(db, 'jobs', job_id)

    def start_generation(self, job_id, instructions=None, source_document_id=None):
        self.require_ai()
        with self.connection() as db, d.transaction(db):
            self.ensure_job_idle(db, job_id)
            if source_document_id:
                self.ensure_idle(db, document_id=source_document_id)
            template_version = (rendering.template_version(r.get(db, 'document_versions', source_document_id)['kind'])
                                if source_document_id else rendering.TEMPLATE_VERSION + ',' + rendering.COVER_LETTER_VERSION)
            run = r.create_run(db, job_id=job_id, source_document_id=source_document_id, instructions=instructions,
                               provider=self.settings.base_url, model=self.settings.model, prompt_version=PROMPT_VERSION, template_version=template_version)
            result = self.task(db, 'revise' if source_document_id else 'generate', 'run_id', run)
        self.wake.set()
        return result

    def save_document(self, document_id, content):
        with self.connection() as db, d.transaction(db):
            old = r.get(db, 'document_versions', document_id)
            run = r.get(db, 'preparation_runs', old['run_id'])
            self.ensure_job_idle(db, run['job_id'])
            self.ensure_idle(db, document_id=document_id)
            cls = s.ResumeContent if old['kind'] == 'resume' else s.CoverLetter
            body = cls.model_validate(content.model_dump()).model_dump()
            doc = r.save_document(db, old['run_id'], old['kind'], body, parent_document_id=document_id)
            result = self.task(db, 'render', 'document_id', doc)
        self.wake.set()
        return result

    def retry_render(self, document_id):
        with self.connection() as db, d.transaction(db):
            doc = r.get(db, 'document_versions', document_id)
            run = r.get(db, 'preparation_runs', doc['run_id'])
            self.ensure_job_idle(db, run['job_id'])
            if doc['render_status'] == 'ready':
                raise BackendError('immutable_pdf', 'Ready PDFs cannot be replaced; save a new revision.', 409)
            result = self.task(db, 'render', 'document_id', document_id)
        self.wake.set()
        return result

    def step(self, db, task_id, value):
        with d.transaction(db):
            db.execute("UPDATE processing_tasks SET step=? WHERE id=? AND status='running'", (value, task_id))
        log.info('task=%s step=%s', task_id, value)

    def work(self):
        while not self.stopping.is_set():
            with self.connection() as db:
                row = db.execute("SELECT * FROM processing_tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self.wake.wait(0.2)
                self.wake.clear()
                continue
            try:
                self.execute(dict(row))
            except sqlite3.OperationalError:
                log.warning('worker database busy; pending work retained')
                self.stopping.wait(0.5)

    def execute(self, task):
        started = time.monotonic()
        with self.connection() as db:
            with d.transaction(db):
                if db.execute("UPDATE processing_tasks SET status='running',started_at=? WHERE id=? AND status='queued'", (d.now(), task['id'])).rowcount != 1:
                    return
            try:
                handlers = {'extract_resume': self.extract_resume, 'intake_job': self.process_job, 'generate': self.generate, 'revise': self.generate, 'render': self.process_render}
                result = handlers[task['action']](db, task)
            except Exception as exc:
                error = exc if isinstance(exc, BackendError) else BackendError('processing_failed', 'Processing failed. Check the saved source and retry explicitly.', 422, True)
                self.fail_resource(db, task, error.message)
                with d.transaction(db):
                    db.execute("UPDATE processing_tasks SET status='failed',step='failed',error_code=?,error_message=?,finished_at=? WHERE id=?", (error.code, error.message, d.now(), task['id']))
                log.warning('task=%s action=%s error=%s', task['id'], task['action'], error.code)
            else:
                with d.transaction(db):
                    db.execute("UPDATE processing_tasks SET status='succeeded',step='finished',result_json=?,finished_at=? WHERE id=?", (r.encode(result), d.now(), task['id']))
            log.info('task=%s duration_seconds=%.2f', task['id'], time.monotonic() - started)

    def fail_resource(self, db, task, message):
        with d.transaction(db):
            if task['resume_version_id']:
                db.execute("UPDATE resume_versions SET status='failed',error_message=?,updated_at=? WHERE id=? AND status IN ('uploaded','extracting')", (message, d.now(), task['resume_version_id']))
            if task['run_id']:
                db.execute("UPDATE preparation_runs SET status='failed',error_message=?,finished_at=? WHERE id=? AND status IN ('queued','running')", (message, d.now(), task['run_id']))
            if task['document_id']:
                db.execute("UPDATE document_versions SET render_status='failed',render_error=? WHERE id=? AND render_status!='ready'", (message, task['document_id']))
            # Retain completed source captures and close only unfinished attempts owned by this task.
            owner = 'resume_version_id' if task['resume_version_id'] else 'job_id' if task['job_id'] else None
            if owner:
                db.execute(f"UPDATE intake_captures SET status='failed',error_message=? WHERE {owner}=? AND status IN ('pending','running')", (message, task[owner]))

    def extract_resume(self, db, task):
        resume_id = task['resume_version_id']
        r.start_extraction(db, resume_id)
        row = r.get(db, 'resume_versions', resume_id)
        capture = r.create_capture(db, capture_type='resume_text', resume_version_id=resume_id)
        r.start_capture(db, capture)
        self.step(db, task['id'], 'extracting_text')
        data = storage.verified(db, row['file_path'], row['sha256']).read_bytes()
        text, blocks = extract(data, row['file_type'])
        r.finish_capture(db, capture, captured_text=text)
        self.step(db, task['id'], 'organising_resume')
        organised, _ = self.ai.complete(db, 'organise_resume', {'text_blocks': blocks}, s.OrganisedResume, intake_capture_id=capture)
        try:
            content, coverage = v.source_coverage(organised.content, blocks)
        except ValueError as exc:
            raise BackendError('import_wording_changed', str(exc)) from exc
        r.finish_extraction(db, resume_id, text, content.model_dump())
        findings = [f.model_dump() for f in organised.findings] + coverage + v.structure(content.model_dump(), 'resume')
        return {'resume_version_id': resume_id, 'findings': findings, 'status': 'needs_review'}

    def process_job(self, db, task):
        job_id = task['job_id']
        inputs = json.loads(task['input_json'])
        job = r.get(db, 'jobs', job_id)
        pasted = inputs['source_type'] == 'pasted'
        source_url = inputs.get('source_url') or job['source_url']
        capture = r.create_capture(db, capture_type='pasted_jd' if pasted else 'fetched_jd', job_id=job_id, supplied_url=source_url)
        r.start_capture(db, capture)
        self.step(db, task['id'], 'capturing_job')
        text = inputs['jd_text'] if pasted else self.fetcher(source_url)
        r.finish_capture(db, capture, captured_text=text)
        self.step(db, task['id'], 'extracting_job_fields')
        extracted, _ = self.ai.complete(db, 'extract_job', {
            'input_format': 'plain_text' if pasted else 'html',
            'source_content': text,
            'source_url': source_url,
        }, s.ExtractedJob, intake_capture_id=capture)
        fields = extracted.model_dump(mode='json', exclude={'requirements','findings','evidence'})
        fields['jd_text'] = text if pasted else extracted.jd_text
        fields['source_url'] = source_url
        if not fields['jd_text'] or not fields['jd_text'].strip():
            raise BackendError('job_description_unavailable', 'AI found no usable job description. Check the posting or paste the full JD.', 422)
        r.save_job(db, job_id, **fields, requirements_json=r.encode(extracted.requirements.model_dump()))
        return {'job_id': job_id, 'status': 'needs_review', 'findings': [f.model_dump() for f in extracted.findings]}

    def render_document(self, db, document_id, task_id):
        doc = r.get(db, 'document_versions', document_id)
        run = r.get(db, 'preparation_runs', doc['run_id'])
        snapshot = upgrade_snapshot(json.loads(run['source_snapshot_json']))
        content = upgrade(json.loads(doc['content_json']))
        self.step(db, task_id, 'rendering_' + doc['kind'])
        try:
            pdf, checks = rendering.render(content, doc['kind'], snapshot['job'])
        except BackendError as exc:
            r.add_validation(db, document_id, 'pdf', 'failed', [v.finding('pdf', exc.message, 'pdf')])
            raise
        r.add_validation(db, document_id, 'pdf', 'passed', checks)
        r.publish_pdf(db, document_id, pdf)
        return {'document_id': document_id, 'findings': []}

    def generate(self, db, task):
        run_id = task['run_id']
        r.start_run(db, run_id)
        run = r.get(db, 'preparation_runs', run_id)
        snapshot = upgrade_snapshot(json.loads(run['source_snapshot_json']))
        source = snapshot.get('source_document')
        kinds = [source['kind']] if source else ['resume','cover_letter']
        docs, errors = [], []
        for kind in kinds:
            self.step(db, task['id'], 'drafting_' + kind)
            operation = 'revise_document' if source else 'tailor_resume' if kind == 'resume' else 'write_cover_letter'
            cls = (s.ResumeRevision if kind == 'resume' else s.LetterRevision) if source else (s.ResumeDraft if kind == 'resume' else s.LetterDraft)
            companion = snapshot.get('companion_document', {}).get('content') if source else None
            if docs:
                companion = upgrade(json.loads(r.get(db, 'document_versions', docs[-1])['content_json']))
            try:
                inputs = {**snapshot, 'kind': kind, 'companion': companion}
                research = None
                if kind == 'cover_letter':
                    inputs['current_date'] = date.today().isoformat()
                    if source:
                        parent = r.get(db, 'document_versions', source['id'])
                        previous = research_history(r.history(db, 'ai_calls', run_id=parent['run_id']))
                        inputs['company_research'] = {'sources': previous['sources']}
                    if self.settings.cover_letter_research_enabled and self.settings.zyte_api_key.strip():
                        contact = snapshot['resume']['contact']
                        private_terms = [contact.get(key) for key in ('name', 'email', 'phone')]
                        private_terms.extend(link.get('url') for link in contact.get('links', []))
                        research = Research(self.settings, progress=lambda value: self.step(db, task['id'], value),
                                            private_terms=private_terms)
                        self.step(db, task['id'], 'researching_company')
                    else:
                        inputs['research_unavailable'] = 'disabled' if not self.settings.cover_letter_research_enabled else 'missing_credentials'
                options = {'research': research} if research is not None else {}
                draft, call = self.ai.complete(db, operation, inputs, cls, run_id=run_id, **options)
                doc_id = r.save_document(db, run_id, kind, draft.content.model_dump(), ai_call_id=call)
                docs.append(doc_id)
            except BackendError as exc:
                errors.append({'kind': kind, 'code': exc.code, 'message': exc.message})
        for doc_id in docs:
            try:
                self.render_document(db, doc_id, task['id'])
            except BackendError as exc:
                r.render_failed(db, doc_id, exc.message)
                errors.append({'document_id': doc_id, 'code': exc.code, 'message': exc.message})
        status = r.finish_run(db, run_id, findings=errors, error='Some outputs need attention' if errors else None)
        if not docs:
            raise BackendError('generation_failed', 'No valid drafts were returned. Inspect AI history and retry.', 502, True)
        return {'run_id': run_id, 'status': status, 'document_ids': docs, 'issues': errors}

    def process_render(self, db, task):
        return self.render_document(db, task['document_id'], task['id'])
