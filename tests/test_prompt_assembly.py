"""Check the guidance actually delivered to each revision workflow."""
import json
import unittest

from backend.ai import PROMPTS, messages
from backend.schemas import ResumeRevision, LetterRevision


class PromptAssemblyTests(unittest.TestCase):
    def test_resume_revision_receives_full_tailoring_rules_and_revision_contract(self):
        inputs = {'kind': 'resume', 'instructions': 'Shorten the summary only.'}
        schema = ResumeRevision.model_json_schema()
        system, user = messages('revise_document', inputs, schema)
        tailoring = (PROMPTS / 'tailor_resume.md').read_text()
        revision = (PROMPTS / 'revise_document.md').read_text()
        self.assertIn(tailoring, system['content'])
        self.assertNotIn((PROMPTS / 'write_cover_letter.md').read_text(), system['content'])
        self.assertIn(revision, system['content'])
        self.assertLess(system['content'].index(tailoring), system['content'].index(revision))
        self.assertEqual(json.loads(system['content'].split('Output JSON Schema:\n')[1]), schema)
        self.assertIn('changes', schema['required'])
        self.assertEqual(json.loads(user['content']), inputs)

    def test_letter_revision_receives_writing_rules_and_revision_contract(self):
        inputs = {'kind': 'cover_letter', 'instructions': 'Improve the opening only.'}
        schema = LetterRevision.model_json_schema()
        system, user = messages('revise_document', inputs, schema)
        writing = (PROMPTS / 'write_cover_letter.md').read_text()
        revision = (PROMPTS / 'revise_document.md').read_text()
        self.assertNotIn((PROMPTS / 'tailor_resume.md').read_text(), system['content'])
        self.assertIn(writing, system['content'])
        self.assertIn(revision, system['content'])
        self.assertLess(system['content'].index(writing), system['content'].index(revision))
        self.assertEqual(json.loads(system['content'].split('Output JSON Schema:\n')[1]), schema)
        self.assertIn('changes', schema['required'])
        self.assertEqual(json.loads(user['content']), inputs)

    def test_document_prompts_make_claim_references_optional(self):
        for operation in ('tailor_resume', 'write_cover_letter', 'revise_document'):
            system, _ = messages(operation, {'kind': 'resume'}, ResumeRevision.model_json_schema())
            self.assertIn('source_refs are optional legacy metadata and may be empty', system['content'])
            self.assertNotIn('must include supporting reviewed source IDs', system['content'])
            self.assertNotIn('must carry `source_refs`', system['content'])
            self.assertNotIn('provide source_refs on claims', system['content'])
