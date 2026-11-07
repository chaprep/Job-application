"""Independent document selections, cross-run history, and exact rewrite/submission inputs."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import database as d, repository as r
from backend.app import create_app
from backend.config import Settings
from backend.errors import BackendError
from backend.service import Service
from backend_fixtures import FakeAI, resume_content, letter

PDF = b'%PDF-1.7\nfixture\n%%EOF'


@pytest.fixture
def workspace(tmp_path):
    settings = Settings(database=tmp_path / 'data/jab.sqlite3', model='fixture', api_key='fixture')
    db = d.connect(settings.database)
    d.migrate(db)
    base = r.upload_resume(db, 'base.pdf', PDF)
    r.start_extraction(db, base)
    r.finish_extraction(db, base, 'Reviewed facts', resume_content().model_dump())
    d.activate_resume(db, base, resume_content().model_dump())
    job = r.create_job(db, source_type='pasted', jd_text='Build useful tools.')
    r.save_job(db, job, company='Example', title='Engineer', confirm=True)
    first = r.create_run(db, job_id=job)
    r.start_run(db, first)

    def save(run, kind):
        content = resume_content().model_dump() if kind == 'resume' else letter(resume_content().model_dump()).model_dump()
        doc = r.save_document(db, run, kind, content)
        r.add_validation(db, doc, 'pdf', 'passed', {})
        r.publish_pdf(db, doc, PDF)
        return doc

    resume1, letter1 = save(first, 'resume'), save(first, 'cover_letter')
    resume2 = save(first, 'resume')
    r.finish_run(db, first)
    latest = letter1
    for _ in range(4):
        run = r.create_run(db, job_id=job, source_document_id=latest, instructions='Improve the opening')
        r.start_run(db, run)
        latest = save(run, 'cover_letter')
        r.finish_run(db, run)
    yield settings, db, job, resume1, resume2, letter1, latest
    db.close()


def test_independent_selections_persist_and_histories_span_runs(workspace):
    settings, db, job, resume1, resume2, letter1, letter5 = workspace
    with TestClient(create_app(settings)) as client:
        url = f'/api/v1/jobs/{job}/document-selections'
        assert client.get(url).json()['resume']['id'] == resume2
        assert client.post(url, json={'document_id': resume1}).status_code == 200
        selected = client.get(url).json()
        assert (selected['resume']['id'], selected['cover_letter']['id']) == (resume1, letter5)
        assert (selected['resume']['version_number'], selected['cover_letter']['version_number']) == (1, 5)
        for kind, expected in (('resume', 2), ('cover_letter', 5)):
            history = client.get(f'/api/v1/jobs/{job}/documents?kind={kind}&limit=1').json()
            assert history['total'] == expected
            assert history['items'][0]['version_number'] == expected
            assert history['items'][0]['kind'] == kind
        doc = client.get(f'/api/v1/documents/{letter5}').json()
        assert doc['version_number'] == 5
        assert doc['source_resume']['contact']['name'] == 'Test Candidate'
    with TestClient(create_app(settings)) as client:
        selected = client.get(url).json()
        assert selected['resume']['id'] == resume1
        assert selected['cover_letter']['id'] == letter5


def test_rewrite_uses_exact_older_version_and_frozen_selected_companion(workspace):
    settings, db, job, resume1, resume2, letter1, letter5 = workspace
    r.select_document(db, job, resume1)
    ai = FakeAI()
    service = Service(settings, ai=ai)
    accepted = service.start_generation(job, 'Rewrite this older letter', source_document_id=letter1)
    snapshot = json.loads(r.get(db, 'preparation_runs', accepted['run_id'])['source_snapshot_json'])
    assert snapshot['source_document']['id'] == letter1
    assert snapshot['companion_document']['id'] == resume1
    r.select_document(db, job, resume2)
    with patch('backend.service.rendering.render', return_value=(PDF, {})):
        service.generate(db, r.get(db, 'processing_tasks', accepted['task_id']))
    inputs = ai.calls[-1][1]
    assert inputs['companion'] == snapshot['companion_document']['content']
    assert inputs['source_document']['id'] == letter1
    selected = r.document_selections(db, job)
    assert selected['resume']['id'] == resume2
    assert selected['cover_letter']['parent_document_id'] == letter1
    assert r.document_version_number(db, selected['cover_letter']['id']) == 6
    # The earlier letter and its PDF are immutable and remain downloadable.
    assert r.download_pdf(db, letter5).read_bytes() == PDF


def test_failed_rewrite_keeps_selected_pair_and_submission_freezes_exact_ids(workspace):
    settings, db, job, resume1, resume2, letter1, letter5 = workspace
    r.select_document(db, job, resume1)
    service = Service(settings, ai=FakeAI())
    accepted = service.start_generation(job, 'Try again', source_document_id=letter1)
    with patch('backend.service.rendering.render', side_effect=BackendError('pdf_overflow', 'Shorten the content.')):
        service.generate(db, r.get(db, 'processing_tasks', accepted['task_id']))
    selected = r.document_selections(db, job)
    assert (selected['resume']['id'], selected['cover_letter']['id']) == (resume1, letter5)
    failed = r.history(db, 'document_versions', run_id=accepted['run_id'])[0]
    assert failed['render_status'] == 'failed'
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/v1/applications', json={
            'origin': 'jab', 'company': 'Example', 'role': 'Engineer', 'job_id': job,
            'applied_on': '2026-11-07', 'resume_document_id': resume1, 'cover_letter_document_id': letter5})
        assert response.status_code == 201, response.text
        application = response.json()
        assert client.post(f'/api/v1/jobs/{job}/document-selections', json={'document_id': resume2}).status_code == 200
        saved = client.get(f'/api/v1/applications/{application["id"]}').json()
        assert (saved['resume_document_id'], saved['cover_letter_document_id']) == (resume1, letter5)
        invalid = client.post('/api/v1/applications', json={
            'origin': 'jab', 'company': 'Example', 'role': 'Engineer', 'job_id': job,
            'applied_on': '2026-11-07', 'resume_document_id': resume1, 'cover_letter_document_id': failed['id']})
        assert invalid.status_code == 422


def test_selection_rejects_other_jobs_and_migration_retains_files(workspace):
    settings, db, job, resume1, resume2, letter1, letter5 = workspace
    other = r.create_job(db, source_type='pasted', jd_text='Another role')
    with pytest.raises(ValueError, match='belong to this job'):
        r.select_document(db, other, resume1)
    before = r.history(db, 'document_versions')
    db.execute('DROP TABLE job_document_selections')
    db.execute("DELETE FROM schema_migrations WHERE version='007_document_selections.sql'")
    db.commit()
    d.migrate(db)
    selected = r.document_selections(db, job)
    assert (selected['resume']['id'], selected['cover_letter']['id']) == (resume2, letter5)
    assert r.history(db, 'document_versions') == before
    assert r.download_pdf(db, resume1).read_bytes() == PDF


def test_resume_rewrite_uses_older_resume_and_keeps_chosen_letter(workspace):
    settings, db, job, resume1, resume2, letter1, letter5 = workspace
    r.select_document(db, job, letter1)
    ai = FakeAI()
    service = Service(settings, ai=ai)
    accepted = service.start_generation(job, 'Improve the summary', source_document_id=resume1)
    with patch('backend.service.rendering.render', return_value=(PDF, {})):
        service.generate(db, r.get(db, 'processing_tasks', accepted['task_id']))
    inputs = ai.calls[-1][1]
    assert inputs['source_document']['id'] == resume1
    assert inputs['companion_document']['id'] == letter1
    assert inputs['companion'] == inputs['companion_document']['content']
    selected = r.document_selections(db, job)
    assert selected['resume']['parent_document_id'] == resume1
    assert selected['cover_letter']['id'] == letter1
    assert r.document_version_number(db, selected['resume']['id']) == 3


@pytest.mark.parametrize('name, expected_name', [
    ('Test Candidate', 'Test Candidate'),
    ('José 李', 'José 李'),
    ('  Jane/Smith: Test\r\n', 'Jane Smith Test'),
])
def test_pdf_download_names_use_frozen_base_resume_name(workspace, name, expected_name):
    from email.message import Message

    settings, db, job, *_ = workspace
    profile = resume_content().model_dump()
    profile['contact']['name'] = name
    base = r.upload_resume(db, 'arbitrary-source-name.pdf', PDF)
    r.start_extraction(db, base)
    r.finish_extraction(db, base, 'Reviewed facts', profile)
    d.activate_resume(db, base, profile)
    run = r.create_run(db, job_id=job)
    r.start_run(db, run)
    documents = {}
    for kind in ('resume', 'cover_letter'):
        # The generated contact must not override the reviewed base identity in filenames.
        content = resume_content().model_dump() if kind == 'resume' else letter(resume_content().model_dump()).model_dump()
        doc = r.save_document(db, run, kind, content)
        r.add_validation(db, doc, 'pdf', 'passed', {})
        r.publish_pdf(db, doc, PDF)
        documents[kind] = doc
    r.finish_run(db, run)
    # Selecting another base later must not rename historical versions.
    next_base = r.save_resume_draft(db, base, resume_content().model_dump())
    d.activate_resume(db, next_base, resume_content().model_dump())
    with TestClient(create_app(settings)) as client:
        for kind, doc in documents.items():
            for download in (True, False):
                response = client.get(f'/api/v1/documents/{doc}/pdf?download={str(download).lower()}')
                assert response.status_code == 200
                assert response.content == PDF
                header = Message()
                header['content-disposition'] = response.headers['content-disposition']
                label = 'resume' if kind == 'resume' else 'cover letter'
                assert header.get_filename() == f'{expected_name}_{label}.pdf'
                assert header.get_content_disposition() == ('attachment' if download else 'inline')
