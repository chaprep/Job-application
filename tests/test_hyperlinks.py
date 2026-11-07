from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend import schemas as s, validation as v, rendering, repository as r, database as d
from backend.content import upgrade, upgrade_snapshot, text_fields, attach_import_links, link_records, remap_spans
from backend.extraction import extract, docx_blocks, pdf_blocks
from backend.app import create_app
from backend.config import Settings
from backend_fixtures import FakeAI, resume_content, docx_bytes, tailored
from test_backend import BackendTests as _BackendHelpers


class LinkContractTests(unittest.TestCase):
    def test_upgrade_preserves_legacy_values_and_original_json(self):
        old = resume_content().model_dump()
        old['schema_version'] = '1'
        old['contact']['links'] = ['https://example.com', 'Portfolio']
        old['experience'][0]['link'] = 'https://example.com/work'
        original = json.dumps(old)
        new = s.ResumeContent.model_validate(old).model_dump()
        self.assertEqual(new['schema_version'], '2')
        self.assertEqual([link['url'] for link in new['contact']['links']], old['contact']['links'])
        self.assertEqual(new['experience'][0]['link'], old['experience'][0]['link'])
        self.assertEqual(json.dumps(old), original)
        self.assertEqual(upgrade(new), new)
        snapshot = {'resume': old, 'source_document': {'content': old}}
        self.assertEqual(upgrade_snapshot(snapshot)['source_document']['content']['schema_version'], '2')
        self.assertEqual(snapshot['resume']['schema_version'], '1')

    def test_unicode_positions_move_or_become_unresolved_without_losing_targets(self):
        old = 'A 😀 CNEX and CNEX'
        span = dict(start=4, end=8, url='https://studio.example', source_link_id='cnex')
        shifted = remap_spans(old, 'Hi ' + old, [span])[0]
        self.assertEqual((shifted['start'], shifted['end']), (7, 11))
        changed = remap_spans(old, 'A 😀 Studio and CNEX', [span])[0]
        self.assertIsNone(changed['start'])
        self.assertEqual(changed['unresolved_label'], 'CNEX')
        self.assertEqual(changed['url'], span['url'])
        self.assertEqual(remap_spans(old, old + '.', [span])[0], span)

    def test_span_validation_and_source_grounding(self):
        source = resume_content().model_dump()
        source['contact']['links'] = []
        node = source['experience'][0]
        node['organization_links'] = [dict(start=0, end=7, url='https://example.com', source_link_id='company', unresolved_label=None)]
        output = tailored(source)
        self.assertEqual(v.result(v.structure(output, 'resume')), 'passed')
        self.assertEqual(v.result(v.grounded(output, source, {}, 'resume')), 'passed')
        output['experience'][0]['organization_links'][0]['url'] = 'https://other.example'
        self.assertEqual(v.result(v.grounded(output, source, {}, 'resume')), 'failed')
        output = tailored(source)
        output['experience'][0]['organization_links'] = []
        self.assertTrue(any('lost' in f['explanation'] for f in v.grounded(output, source, {}, 'resume')))
        output = tailored(source)
        output['experience'][0]['organization_links'][0].update(start=None, end=None, unresolved_label='Example')
        findings = v.structure(output, 'resume')
        self.assertTrue(findings)
        self.assertFalse(any(v.is_link_finding(f) for f in findings))
        output = tailored(source)
        output['experience'][0]['organization_links'] *= 2
        self.assertEqual(v.result(v.structure(output, 'resume')), 'failed')

    def test_hidden_destination_is_evidence_and_ambiguous_labels_stay_unresolved(self):
        body = resume_content().model_dump()
        body['contact']['links'] = []
        body['experience'][0]['organization'] = 'CNEX'
        evidence = [dict(id='one', text='CNEX', links=[dict(id='cnex_link', label='CNEX', url='https://studio.example')])]
        linked = attach_import_links(body, evidence)
        self.assertEqual(linked['experience'][0]['organization_links'][0]['url'], 'https://studio.example')
        body['experience'].append(deepcopy(body['experience'][0]))
        body['experience'][-1]['id'] = 'other'
        ambiguous = attach_import_links(body, evidence)
        self.assertEqual(ambiguous['unresolved_links'][0]['url'], 'https://studio.example')
        self.assertEqual(ambiguous['experience'][0]['organization_links'], [])
        # A hidden URI need not be in visible text to pass source coverage.
        minimal = s.ResumeContent(contact=s.Contact(name='Test'), experience=[s.Entry(organization='CNEX', title='Engineer')])
        blocks = [dict(id='one', text='Test CNEX Engineer', links=evidence[0]['links'])]
        content, _ = v.source_coverage(minimal, blocks)
        self.assertEqual(content.experience[0].organization_links[0].source_link_id, 'cnex_link')

    def test_import_never_accepts_model_invented_link_destinations(self):
        body = resume_content().model_dump()
        body['summary'][0]['links'] = [dict(start=0, end=6, url='https://invented.example', source_link_id='invented', unresolved_label=None)]
        blocks = [dict(id='all', text=' '.join(v.text_values(body)), links=[])]
        with self.assertRaisesRegex(ValueError, 'invented hyperlink'):
            v.source_coverage(s.ResumeContent.model_validate(body), blocks)

    def test_supplied_resume_all_seven_links_and_true_display_labels(self):
        path = Path(__file__).resolve().parents[1] / 'reference/resume-template.pdf'
        _, blocks = extract(path.read_bytes(), 'pdf')
        links = [link for block in blocks for link in block['links']]
        self.assertEqual(len(links), 7)
        expected = {'mailto:test@example.com', 'https://www.linkedin.com/in/example/', 'https://example.com', 'https://studio.example', 'https://products.example', 'https://care.example', 'https://github.com/example/project'}
        self.assertEqual({link['url'] for link in links}, expected)
        self.assertEqual(next(link['label'] for link in links if link['url'] == 'https://studio.example'), 'studio.example')
        self.assertTrue(all(link['color'] == '#174b70' for link in links))
        # A deterministic organisation fixture mirrors all linked labels; verify each association.
        base = s.ResumeContent(contact=s.Contact(name='Test Candidate', email='test@example.com', links=[s.ContactLink(label=link['label'], url=link['url']) for link in links[1:3]]),
            experience=[s.Entry(organization=label.upper(), link=label) for label in ('studio.example', 'products.example', 'care.example')], projects=[s.Entry(title='Lead scoring', link=links[-1]['url'])])
        imported = attach_import_links(base.model_dump(), blocks)
        self.assertEqual(imported['unresolved_links'], [])
        self.assertEqual({url for _, _, url, _ in link_records(imported)}, expected - {'mailto:test@example.com'})
        self.assertEqual(imported['experience'][0]['link_label'], 'studio.example')

    def test_docx_relationships_across_parts_runs_tables_and_field_codes(self):
        namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        relns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        document = f'''<w:document xmlns:w="{namespace}" xmlns:r="{relns}"><w:body><w:p><w:r><w:t>Test Candidate </w:t></w:r><w:hyperlink r:id="rId1"><w:r><w:t>CN</w:t></w:r><w:r><w:t>EX</w:t></w:r></w:hyperlink></w:p><w:tbl><w:tr><w:tc><w:p><w:fldSimple w:instr='HYPERLINK "https://example.com/table"'><w:r><w:t>Table link</w:t></w:r></w:fldSimple></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>HYPERLINK "https://example.com/field"</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>Field link</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:body></w:document>'''
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('word/document.xml', document)
            archive.writestr('word/_rels/document.xml.rels', '<Relationships><Relationship Id="rId1" Target="https://studio.example"/></Relationships>')
            for part in ('header1.xml', 'footer1.xml'):
                archive.writestr('word/' + part, f'<w:root xmlns:w="{namespace}" xmlns:r="{relns}"><w:p><w:hyperlink r:id="rId1"><w:r><w:t>{part}</w:t></w:r></w:hyperlink></w:p></w:root>')
                archive.writestr('word/_rels/' + part + '.rels', '<Relationships><Relationship Id="rId1" Target="https://example.com/' + part + '"/></Relationships>')
        text, blocks = docx_blocks(stream.getvalue())
        links = [link for block in blocks for link in block['links']]
        self.assertEqual(len(links), 5)
        self.assertIn('Test Candidate CNEX', text)
        self.assertEqual(next(link['url'] for link in links if link['label'] == 'CNEX'), 'https://studio.example')
        self.assertEqual(blocks[0]['part'], 'word/header1.xml')
        self.assertEqual(blocks[-1]['part'], 'word/footer1.xml')

    def test_bold_overlap_link_escape_and_unknown_protocols(self):
        tex = rendering.rich_text('A 😀 CNEX studio', [dict(start=4, end=15, url='https://studio.example?a=1&b=2', source_link_id='cnex')], ['CNEX'])
        self.assertIn(r'\href{https://studio.example?a=1\&b=2}{\textbf{CNEX} studio}', tex)
        tex = rendering.rich_text('CNEX', [dict(start=0, end=4, url='javascript:alert(1)')], ['CNEX'])
        self.assertNotIn(r'\href', tex)
        self.assertIn(r'\textbf{CNEX}', tex)


class LinkWorkflowTests(unittest.TestCase):
    setUp = _BackendHelpers.setUp
    tearDown = _BackendHelpers.tearDown
    wait = _BackendHelpers.wait
    baseline = _BackendHelpers.baseline
    job = _BackendHelpers.job
    # Only new tests are collected here; the inherited helpers use an isolated DB/FakeAI.
    def test_reimport_is_a_new_version_and_does_not_replace_active_or_original(self):
        with TestClient(create_app(self.settings, self.ai)) as client:
            base = self.baseline(client)
            content = base['reviewed_content']
            content['summary'][0]['text'] = 'A user-reviewed change made after the original upload.'
            response = client.post(f'/api/v1/resumes/{base["id"]}/activate', json={'content': content, 'confirmed': True})
            active = response.json()['resume_version_id']
            original_bytes = client.get(f'/api/v1/resumes/{active}/original').content
            client.app.state.service.stop()
            accepted = client.post(f'/api/v1/resumes/{active}/reimport')
            self.assertEqual(accepted.status_code, 202, accepted.text)
            child = client.get(f'/api/v1/resumes/{accepted.json()["resume_version_id"]}').json()
            self.assertEqual(child['parent_resume_id'], active)
            self.assertIsNone(child['reviewed_content'])
            self.assertEqual(client.get('/api/v1/resumes/active').json()['id'], active)
            self.assertEqual(client.get(f'/api/v1/resumes/{child["id"]}/original').content, original_bytes)
            self.assertEqual(client.post(f'/api/v1/resumes/{base["id"]}/reimport').status_code, 409)
        with TestClient(create_app(self.settings, self.ai)) as client:
            self.assertEqual(client.get('/api/v1/resumes/active').json()['id'], active)
            result = self.wait(client, client.post(f'/api/v1/resumes/{child["id"]}/retry-extraction'))
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual(client.get('/api/v1/resumes/active').json()['reviewed_content']['summary'][0]['text'], content['summary'][0]['text'])

    def test_real_pdf_blue_link_labels_destinations_and_no_duplicate_appended_url(self):
        content = resume_content().model_dump()
        content['contact']['links'] = [s.ContactLink(id='linkedin', label='LinkedIn', url='https://www.linkedin.com/in/example/').model_dump(), s.ContactLink(id='website', label='Website', url='https://example.com').model_dump()]
        content['contact']['email'] = 'test@example.com'
        entry = content['experience'][0]
        entry.update(organization='CNEX', organization_links=[dict(start=0, end=4, url='https://studio.example', source_link_id='cnex')])
        entry['bullets'] = [s.Claim(id='clients', text='Supported Zebotech and Turtlecare.', links=[s.LinkSpan(start=10, end=18, url='https://products.example', source_link_id='zebo'), s.LinkSpan(start=23, end=33, url='https://care.example', source_link_id='turtle')]).model_dump()]
        content['projects'] = [s.Entry(id='project', title='GitHub project', title_links=[s.LinkSpan(start=0, end=6, url='https://github.com/example/project', source_link_id='github')]).model_dump()]
        pdf, checks = rendering.render(content, 'resume', {})
        self.assertEqual(checks['hyperlinks_verified'], 7)
        text, blocks = pdf_blocks(pdf)
        annotations = [link for block in blocks for link in block['links']]
        # Poppler may associate adjacent punctuation with an annotation rectangle; verify actual
        # PDF annotations separately from the XML text fragments it assigns to those rectangles.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'linked.pdf'; path.write_bytes(pdf)
            rows = subprocess.run(['pdfinfo', '-url', str(path)], capture_output=True, text=True, check=True).stdout.splitlines()
            self.assertEqual(sum('Annotation' in row for row in rows), 7)
        self.assertEqual(len([link for link in annotations if link['color'] == '#174b70']), 7)
        self.assertNotIn('https://studio.example', text)
        self.assertEqual(next(link['label'] for link in annotations if link['url'] == 'https://studio.example'), 'CNEX')
        # Old ready PDFs and frozen JSON remain untouched when newer APIs adapt them.
        with TestClient(create_app(self.settings, self.ai)) as client:
            base = self.baseline(client)
            job = self.job(client)
            with client.app.state.service.connection() as db, d.transaction(db):
                legacy = resume_content().model_dump(); legacy['schema_version'] = '1'; legacy['contact']['links'] = ['https://example.com']
                legacy.pop('unresolved_links', None)
                for owner, key, spans in text_fields(legacy):
                    owner.pop(spans, None)
                    owner.pop('link_label', None); owner.pop('link_source_id', None)
                snapshot = {'resume': legacy, 'job': {'company': 'Example', 'title': 'Engineer', 'jd_text': 'Example Engineer Python'}, 'instructions': None}
                run_id = db.execute("INSERT INTO preparation_runs(job_id,resume_version_id,source_snapshot_json,status,created_at) VALUES (?,?,?,'running',?)", (job, base['id'], json.dumps(snapshot), d.now())).lastrowid
                doc_id = r.save_document(db, run_id, 'resume', tailored(legacy))
                before = r.get(db, 'document_versions', doc_id)['content_json']
                frozen = r.get(db, 'preparation_runs', run_id)['source_snapshot_json']
            response = client.get(f'/api/v1/documents/{doc_id}')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['content']['schema_version'], '2')
            revision = self.wait(client, client.post(f'/api/v1/documents/{doc_id}/revisions', json={'content': tailored(legacy)}))
            self.assertEqual(revision['status'], 'succeeded', revision)
            self.assertEqual(client.get(f'/api/v1/documents/{revision["document_id"]}').json()['render_status'], 'ready')
            with client.app.state.service.connection() as db:
                self.assertEqual(r.get(db, 'document_versions', doc_id)['content_json'], before)
                self.assertEqual(r.get(db, 'preparation_runs', run_id)['source_snapshot_json'], frozen)


del _BackendHelpers
