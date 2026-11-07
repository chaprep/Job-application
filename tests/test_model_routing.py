"""Operation-specific model selection, with no provider traffic."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend import database as d, repository as r, schemas as s
from backend.ai import AI
from backend.config import Settings
from backend.errors import BackendError


class ModelRoutingTests(unittest.TestCase):
    def test_intake_overrides_repair_and_other_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            db = d.connect(Path(directory) / 'jab.sqlite3')
            try:
                d.migrate(db)
                job = r.create_job(db, source_type='pasted', jd_text='Full job description')
                capture = r.create_capture(db, capture_type='pasted_jd', job_id=job)
                sent = []

                def respond(request):
                    sent.append(json.loads(request.content)['model'])
                    answer = 'invalid JSON' if sent[-1] != 'default-model' and sent.count(sent[-1]) == 1 else '{"findings":[]}'
                    return httpx.Response(200, json={'choices': [{'message': {'content': answer}}]})

                settings = Settings(model='anthropic/claude-sonnet-5.5',
                                    resume_model='resume-model', job_model='job-model',
                                    review_model='review-model', revision_model='revision-model',
                                    tailor_model='tailor-model', cover_letter_model='letter-model',
                                    api_key='test-key')
                ai = AI(settings, httpx.MockTransport(respond))
                for operation in ('organise_resume', 'extract_job', 'tailor_resume',
                                  'write_cover_letter', 'review_document', 'revise_document'):
                    if operation == 'extract_job':
                        with self.assertRaises(BackendError) as caught:
                            ai.complete(db, operation, {}, s.Review, intake_capture_id=capture)
                        self.assertEqual(caught.exception.code, 'invalid_ai_response')
                    else:
                        ai.complete(db, operation, {}, s.Review, intake_capture_id=capture)
                expected = ([settings.resume_model] * 2 + [settings.job_model]
                            + [settings.tailor_model] * 2 + [settings.cover_letter_model] * 2
                            + [settings.review_model] * 2 + [settings.revision_model] * 2)
                self.assertEqual(sent, expected)
                self.assertEqual([row['model'] for row in r.history(db, 'ai_calls')], expected)

                ai = AI(Settings(model='default-model', api_key='test-key'), httpx.MockTransport(respond))
                for operation in ('organise_resume', 'extract_job', 'tailor_resume',
                                  'write_cover_letter', 'review_document', 'revise_document'):
                    ai.complete(db, operation, {}, s.Review, intake_capture_id=capture)
                    self.assertEqual(sent[-1], 'default-model')
            finally:
                db.close()

    def test_intake_models_load_from_environment(self):
        with patch('backend.config.load_dotenv'), patch.dict(os.environ, {
            'JAB_AI_MODEL': 'default-model', 'JAB_AI_RESUME_MODEL': ' openai/gpt-6-luna-pro ',
            'JAB_AI_JOB_MODEL': ' openai/gpt-6-luna-pro ',
            'JAB_AI_REVIEW_MODEL': ' openai/gpt-6-luna-pro ',
            'JAB_AI_REVISION_MODEL': ' anthropic/claude-sonnet-5.5 ',
            'JAB_AI_TAILOR_MODEL': ' anthropic/claude-sonnet-5.5 ',
            'JAB_AI_COVER_LETTER_MODEL': ' anthropic/claude-opus-5.5 ',
        }):
            settings = Settings.load()
        self.assertEqual(settings.resume_model, 'openai/gpt-6-luna-pro')
        self.assertEqual(settings.job_model, 'openai/gpt-6-luna-pro')
        self.assertEqual(settings.review_model, 'openai/gpt-6-luna-pro')
        self.assertEqual(settings.revision_model, 'anthropic/claude-sonnet-5.5')
        self.assertEqual(settings.tailor_model, 'anthropic/claude-sonnet-5.5')
        self.assertEqual(settings.cover_letter_model, 'anthropic/claude-opus-5.5')
        self.assertEqual(settings.model, 'default-model')


    def test_document_kind_selects_model_for_drafts_retries_and_schema_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            db = d.connect(Path(directory) / 'jab.sqlite3')
            try:
                d.migrate(db)
                job = r.create_job(db, source_type='pasted', jd_text='Full job description')
                capture = r.create_capture(db, capture_type='pasted_jd', job_id=job)
                sent = []

                def respond(request):
                    sent.append(json.loads(request.content)['model'])
                    answer = 'invalid JSON' if len(sent) % 2 else '{"findings":[]}'
                    return httpx.Response(200, json={'choices': [{'message': {'content': answer}}]})

                sonnet, opus = 'anthropic/claude-sonnet-5.5', 'anthropic/claude-opus-5.5'
                ai = AI(Settings(model=sonnet, tailor_model=sonnet, revision_model=sonnet,
                                 cover_letter_model=opus, api_key='test-key'), httpx.MockTransport(respond))
                for operation, kind in (('tailor_resume', 'resume'), ('write_cover_letter', 'cover_letter'),
                                        ('revise_document', 'resume'), ('revise_document', 'cover_letter'),
                                        ('revise_document', 'resume'), ('revise_document', 'cover_letter')):
                    ai.complete(db, operation, {'kind': kind}, s.Review, intake_capture_id=capture)
                    self.assertEqual(sent[-2:], [opus if kind == 'cover_letter' else sonnet] * 2)
                self.assertEqual([row['model'] for row in r.history(db, 'ai_calls')], sent)
                # A blank letter override uses the default rather than the résumé revision model.
                ai = AI(Settings(model=sonnet, revision_model='resume-only-model', api_key='test-key'), httpx.MockTransport(respond))
                ai.complete(db, 'revise_document', {'kind': 'cover_letter'}, s.Review, intake_capture_id=capture)
                self.assertEqual(sent[-2:], [sonnet] * 2)
            finally:
                db.close()
