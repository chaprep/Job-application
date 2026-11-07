from copy import deepcopy
from io import BytesIO
import zipfile

from backend import schemas as s
from backend.errors import BackendError


def resume_content():
    return s.ResumeContent(contact=s.Contact(name='Test Candidate', email='test@example.com', location='Bengaluru', links=['https://example.com']),
        summary=[s.Claim(id='summary', text='Builds useful software with Python and clear documentation.')],
        skills=[s.SkillGroup(id='skills', label='Development', items=[s.Claim(id='python', text='Python')])],
        experience=[s.Entry(id='work', organization='Example Studio', title='Engineer', dates='2024 - Present', bullets=[s.Claim(id='achievement', text='Automated tasks and saved 30 hours monthly.')])],
        education=[s.Entry(id='degree', organization='Example University', title='Bachelor of Business Administration')])


def tailored(source):
    content = deepcopy(source)
    for group in ('summary',):
        for item in content[group]:
            item['source_refs'] = [item['id']]
    for group in content['skills']:
        for item in group['items']:
            item['source_refs'] = [item['id']]
    for entry in content['experience']:
        for item in entry['bullets']:
            item['source_refs'] = [item['id']]
    return content


def letter(source):
    sentence = 'I build useful software with Python and clear documentation and bring a practical approach to organising work and supporting a team through careful implementation and thoughtful communication with colleagues and customers.'
    paragraph = ' '.join([sentence] * 3)
    return s.CoverLetter(contact=s.Contact.model_validate(source['contact']), salutation='Dear Example hiring team,',
        paragraphs=[s.Claim(id=f'paragraph_{i}', text=paragraph, source_refs=['summary']) for i in range(3)], signature=source['contact']['name'])


def docx_bytes():
    lines = ['Test Candidate', 'test@example.com', 'Bengaluru', 'https://example.com', 'Builds useful software with Python and clear documentation.', 'Example Studio', 'Engineer', '2024 - Present', 'Automated tasks and saved 30 hours monthly.', 'Python', 'Example University', 'Bachelor of Business Administration']
    body = ''.join('<w:p><w:r><w:t>' + line + '</w:t></w:r></w:p>' for line in lines)
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>')
    return stream.getvalue()


class FakeAI:
    def __init__(self, fail_kind=None, bad_review=False):
        self.fail_kind, self.bad_review = fail_kind, bad_review
        self.calls = []

    def complete(self, db, operation, inputs, contract, *, research=None, **owner):
        from backend import repository as r
        self.calls.append((operation, inputs))
        call = r.create_ai_call(db, purpose=operation, provider='fixture', model='fixture', request={'inputs': inputs}, **owner)
        if operation in ('tailor_resume','write_cover_letter','revise_document') and inputs.get('kind') == self.fail_kind:
            r.finish_ai_call(db, call, raw_response='fixture failure', error='Fixture failed')
            raise BackendError('fixture_failed', 'Fixture model operation failed.', 502)
        if operation == 'organise_resume':
            result = s.OrganisedResume(content=resume_content())
        elif operation == 'extract_job':
            result = s.ExtractedJob(jd_text=inputs['source_content'] if inputs['input_format'] == 'plain_text' else 'Example is hiring an Engineer to build Python applications.', company='Example', title='Engineer', evidence={'company': 'Example', 'title': 'Engineer'}, requirements=s.Requirements(required=['Python']))
        elif operation == 'review_document':
            findings = [s.Finding(field='summary', severity='error', category='grounding', explanation='Unsupported statement')] if self.bad_review else []
            result = s.Review(findings=findings)
        else:
            body = tailored(inputs['resume']) if inputs['kind'] == 'resume' else letter(inputs['resume']).model_dump()
            if inputs['kind'] == 'cover_letter':
                body['letter_date'] = inputs['current_date']
            value = {'content': body}
            if operation == 'revise_document':
                value['changes'] = ['Applied the requested improvement']
            result = contract.model_validate(value)
        r.finish_ai_call(db, call, raw_response=result.model_dump_json(), validated_response=result.model_dump())
        return result, call
