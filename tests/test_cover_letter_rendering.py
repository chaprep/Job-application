"""Dedicated cover-letter layout and résumé rendering compatibility."""
import csv
import hashlib
import copy
import json
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import rendering
from backend.errors import BackendError
from backend.extraction import pdf_blocks
from backend_fixtures import resume_content, letter

JOB = {'title': 'AI GTM Engineer', 'company': 'Example', 'location': 'Bengaluru, India'}


def sample(count=250, paragraphs=3):
    content = letter(resume_content().model_dump()).model_dump()
    content['letter_date'] = '2026-11-07'
    sentence = ('I build tools that help teams save time and serve clients well. '
                'My work brings clear goals and sound code to each stage of a project. '
                'I test each change with the team and use their views to shape the next step.')
    words = (sentence.split() * 10)[:count]
    content['paragraphs'] = [dict(id=f'p{i}', text=' '.join(words[i*count//paragraphs:(i+1)*count//paragraphs]), links=[], emphasis=[]) for i in range(paragraphs)]
    return content


class CoverLetterRendering(unittest.TestCase):
    def test_matches_approved_preview_and_original_right_column(self):
        fixtures = Path(__file__).parent / 'fixtures'
        fixture = json.loads((fixtures / 'cover-letter-approved.json').read_text())
        content = fixture['content']
        original = copy.deepcopy(content)
        pdf, checks = rendering.render(content, 'cover_letter', fixture['job'])
        self.assertEqual(content, original)
        self.assertEqual(checks['template_version'], 'progress-2')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new.pdf'
            path.write_bytes(pdf)
            raster = lambda source, *crop: subprocess.check_output(
                ['pdftoppm', '-scale-to', '1500', '-singlefile', *crop, str(source)])
            self.assertEqual(hashlib.sha256(raster(path)).digest(),
                             hashlib.sha256(raster(fixtures / 'cover-letter-approved.pdf')).digest())
            right = raster(path, '-x', '440', '-y', '0', '-W', '720', '-H', '1500')
            self.assertEqual(hashlib.sha256(right).hexdigest(), fixture['original_right_raster_sha256'])

    def test_contact_layout_and_displayed_url_contract(self):
        content = sample()
        content['contact']['location'] = 'Bengaluru, India | Remote'
        content['contact']['links'] = [
            dict(id='web', label='My portfolio', url='https://example.com/'),
            dict(id='li', label='Professional profile', url='https://www.linkedin.com/in/example/'),
            dict(id='other', label='Other contact', url='mailto:hello@example.com'),
        ]
        expected = rendering.required_text(content, 'cover_letter', JOB)
        for value in ('Bengaluru, India', 'Remote', 'Website', 'LinkedIn', 'Other contact'):
            self.assertIn(value, expected)
        for link in content['contact']['links']:
            self.assertIn(link['url'], expected)
        tex = rendering.latex(content, 'cover_letter', JOB)
        self.assertNotIn(r'\textbf{' + content['contact']['name'] + '}', tex)
        self.assertIn(r'\fontsize{10}{14}', tex)
        self.assertIn(r'\textbf{Website}\par', tex)
        self.assertEqual(rendering.cover_contact_heading(dict(url='https://linkedin.com.evil.test/', label='Profile')), 'Website')
        self.assertEqual(rendering.cover_contact_heading(dict(url='https://example.com/linkedin.com/', label='Profile')), 'Website')
        self.assertEqual(rendering.cover_contact_heading(dict(url='https://[invalid', label='Saved label')), 'Saved label')
        self.assertNotIn(r'\href', rendering.cover_contact_href('javascript:alert(1)', 'javascript:alert(1)'))
        pdf, checks = rendering.render(content, 'cover_letter', JOB)
        self.assertEqual(checks['hyperlinks_verified'], 4)
        _, blocks = pdf_blocks(pdf)
        for link in content['contact']['links']:
            labels = ''.join(l['label'] for b in blocks for l in b.get('links', []) if l['url'] == link['url'])
            self.assertIn(link['url'], labels.replace(' ', '').replace('\n', ''))

    def test_resume_actual_path_is_identical_to_before_change(self):
        before = (Path(__file__).parent / 'fixtures/resume-before.tex').read_text().replace('@INTER_FONT_DIR@', str(rendering.inter_font_dir()))
        self.assertEqual(before, rendering.latex(resume_content().model_dump(), 'resume', {}))
        old_pdf, _ = rendering.compile_tex(before, [])
        new_pdf, checks = rendering.render(resume_content().model_dump(), 'resume', {})
        self.assertEqual(checks['paper'], 'A4')
        with tempfile.TemporaryDirectory() as folder:
            hashes = []
            for label, pdf in (('before', old_pdf), ('after', new_pdf)):
                path = Path(folder) / label
                path.with_suffix('.pdf').write_bytes(pdf)
                subprocess.run(['pdftoppm', '-scale-to', '1600', '-singlefile', '-png', str(path.with_suffix('.pdf')), str(path)], check=True, capture_output=True)
                hashes.append(hashlib.sha256(path.with_suffix('.png').read_bytes()).digest())
            self.assertEqual(*hashes)

    def test_word_budget_endpoints_and_column_bounds(self):
        for count, paragraphs in ((250, 3), (350, 4)):
            with self.subTest(words=count):
                content = sample(count, paragraphs)
                self.assertEqual(sum(len(p['text'].split()) for p in content['paragraphs']), count)
                pdf, checks = rendering.render(content, 'cover_letter', JOB)
                self.assertEqual((checks['paper'], checks['pages'], checks['template_version']), ('US Letter', 1, 'progress-2'))
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 'letter.pdf'
                    path.write_bytes(pdf)
                    rows = list(csv.DictReader(StringIO(subprocess.check_output(['pdftotext', '-tsv', str(path), '-'], text=True)), delimiter='\t', quoting=csv.QUOTE_NONE))
                    page = next(row for row in rows if row['level'] == '1')
                    self.assertEqual((float(page['width']), float(page['height'])), (612, 792))
                    for row in rows:
                        if row['level'] == '5':
                            self.assertTrue(float(row['left']) + float(row['width']) <= 201 or float(row['left']) >= 237, row)
                    with self.assertRaises(BackendError) as error:
                        rendering.pdf_check(path, [], kind='resume')
                    self.assertEqual(error.exception.code, 'pdf_page_size')

    def test_long_contacts_unicode_emphasis_and_wrapped_links(self):
        content = sample()
        content['contact'].update(name='Alexandra María Srinivasan Prasad', phone='+1 202-555-0100',
                                  email='alexandra.maria.srinivasan.prasad@example.com',
                                  links=[dict(id='portfolio', label='Portfolio & case studies: alexandra.example.com/projects', url='https://example.com/projects/alexandra-maria-srinivasan-prasad/case-study?a=1&b=2')])
        content['signature'] = content['contact']['name']
        p = content['paragraphs'][0]
        text = 'I built Python & SQL tools with 30% savings, ₹25 outcomes and $5 costs. Uses #tags, x_y and {braces}. '
        label = 'Explore the full case study and read how our team built these tools'
        p.update(text=text + label + '. ' + p['text'], emphasis=['Python & SQL', 'full case study'],
                 links=[dict(start=len(text), end=len(text)+len(label), url='https://example.com/case?a=1&b=2')])
        job = {**JOB, 'title': 'Senior Sales Development Representative and GTM Engineer'}
        self.assertIn(r'\textbf{Python \& SQL}', rendering.latex(content, 'cover_letter', job))
        pdf, checks = rendering.render(content, 'cover_letter', job)
        self.assertEqual(checks['hyperlinks_verified'], 3)
        _, blocks = pdf_blocks(pdf)
        self.assertEqual({link['url'] for block in blocks for link in block.get('links', [])},
                         {'mailto:' + content['contact']['email'], content['contact']['links'][0]['url'], p['links'][0]['url']})

    def test_optional_details_and_historical_undated_letter(self):
        content = sample()
        content.pop('letter_date')
        content['contact'].update(location='', phone='', email='', links=[])
        job = dict(title='Engineer', company='Example', recruiter_details='Jane Doe, 123 Invented Street')
        tex = rendering.latex(content, 'cover_letter', job)
        sidebar = tex.split(r'\begin{lrbox}{\letterbody}')[0]
        for omitted in (r'\vspace{4bp}\par', r'\vspace{12bp}', r'\textbf{Website}', r'\textbf{LinkedIn}', r'\sbox0'):
            self.assertNotIn(omitted, sidebar)
        for omitted in ('November', 'Jane Doe', 'Invented Street'):
            self.assertNotIn(omitted, tex)
        self.assertEqual(rendering.render(content, 'cover_letter', job)[1]['hyperlinks_verified'], 0)

    def test_all_saved_visible_content_is_required(self):
        content = sample()
        expected = rendering.required_text(content, 'cover_letter', JOB)
        for value in ['7 November 2026', content['contact']['email'], *JOB.values(), content['salutation'], content['closing'], content['signature'], content['paragraphs'][0]['text']]:
            self.assertIn(value, expected)
        self.assertEqual(content['letter_date'], '2026-11-07')
        self.assertEqual(rendering.displayed_date('2026-01-01'), '1 January 2026')

    def test_overflow_is_actionable_without_typography_changes(self):
        content = sample()
        content['paragraphs'][0]['text'] *= 12
        self.assertIn(r'\fontsize{11}{14}', rendering.latex(content, 'cover_letter', JOB))
        with self.assertRaises(BackendError) as error:
            rendering.render(content, 'cover_letter', JOB)
        self.assertEqual(error.exception.code, 'pdf_overflow')
        self.assertIn('Shorten', error.exception.message)

    def test_fonts_are_independent(self):
        with patch.object(rendering, 'roboto_font_dir', return_value=None):
            self.assertTrue(rendering.available())
            self.assertFalse(rendering.available('cover_letter'))
            rendering.render(resume_content().model_dump(), 'resume', {})
            with self.assertRaises(BackendError) as error:
                rendering.latex(sample(), 'cover_letter', JOB)
            self.assertEqual(error.exception.code, 'font_missing')
            self.assertIn('Roboto', error.exception.message)
        with patch.object(rendering, 'inter_font_dir', return_value=None):
            self.assertTrue(rendering.available('cover_letter'))
            self.assertFalse(rendering.available())
            rendering.render(sample(), 'cover_letter', JOB)

    def test_wrong_page_size_and_invalid_glyphs(self):
        tex = rendering.latex(sample(), 'cover_letter', JOB).replace('letterpaper', 'a4paper')
        with self.assertRaises(BackendError) as error:
            rendering.compile_tex(tex, [], 'cover_letter')
        self.assertEqual(error.exception.code, 'pdf_page_size')
        for log in ('Missing character: There is no glyph', r'Overfull \hbox', r'Overfull \vbox'):
            with self.assertRaises(BackendError) as error:
                rendering.pdf_check(Path('unused.pdf'), [], log, 'cover_letter')
            self.assertEqual(error.exception.code, 'pdf_overflow')
