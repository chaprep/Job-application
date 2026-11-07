"""Deterministic checks supplement, but do not replace, semantic AI and human review."""
import re
from urllib.parse import urlsplit

from . import schemas as s
from .extraction import normal
from .content import upgrade, text_fields, valid_span, link_records, attach_import_links


def finding(field, explanation, category='grounding', severity='error', refs=None):
    return s.Finding(field=field, severity=severity, category=category, explanation=explanation, source_refs=refs or []).model_dump()


def nodes(value):
    """Yield addressable source entries and individual claims."""
    if isinstance(value, dict):
        if 'id' in value:
            yield value
        for key, child in value.items():
            if key not in ('links', 'title_links', 'organization_links', 'unresolved_links'):
                yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def text_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'links':
                for link in child:
                    if isinstance(link, str):
                        yield link
                    elif 'label' in link:
                        yield link['label']
            elif key not in ('id', 'source_refs', 'source_link_id', 'link_source_id', 'schema_version', 'emphasis', 'title_links', 'organization_links', 'unresolved_links', 'url'):
                yield from text_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from text_values(child)
    elif isinstance(value, str) and value.strip():
        yield value


def safe_link(url):
    if not url:
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    scheme_ok = bool(parts.hostname) if parts.scheme in ('https', 'http') else parts.scheme == 'mailto' and '@' in parts.path
    return scheme_ok and not any(ch.isspace() or ord(ch) < 32 or ch in '{}\\' for ch in url) and not parts.username and not parts.password


def source_coverage(content, blocks):
    """Preserve extraction lines not represented, and reject paraphrased imported claims."""
    result = attach_import_links(content.model_dump(), blocks)
    represented = normal(' '.join(text_values(result)))
    missing = [block for block in blocks if normal(block['text']) not in represented]
    findings = []
    source = normal(' '.join(block['text'] for block in blocks))
    urls = {link['url'] for block in blocks for link in block.get('links', [])}
    for key, value in result['contact'].items():
        if key == 'links':
            if any(normal(link['label']) not in source or (link['url'] not in urls and normal(link['url']) not in source) for link in value):
                raise ValueError('Resume organisation changed contact link evidence')
            continue
        values = value if isinstance(value, list) else [value]
        if any(item and normal(item) not in source for item in values):
            raise ValueError('Resume organisation changed contact facts; retry or review the preserved extraction')
    for node in nodes(result):
        for key in ('title','organization','location','dates','link', 'link_label'):
            if node.get(key) and normal(node[key]) not in source and not (key == 'link' and node[key] in urls):
                raise ValueError('Resume organisation changed source facts; retry or review the preserved extraction')
        if 'text' in node and normal(node['text']) not in source:
            raise ValueError('Resume organisation changed source wording; review the preserved raw extraction or retry')
    for _, label, url, _ in link_records(result):
        if normal(label) not in source or (url not in urls and normal(url) not in source):
            raise ValueError('Resume organisation invented hyperlink evidence')
    if missing:
        result['additional_sections'].append({'title': 'Unclassified source content', 'entries': [
            s.Entry(title='', bullets=[s.Claim(text=block['text']) for block in missing]).model_dump()]})
        findings.append(finding('additional_sections', f'{len(missing)} source blocks were preserved for manual classification.', 'coverage', 'warning'))
    return s.ResumeContent.model_validate(result), findings


def is_link_finding(value):
    return value['category'] == 'structure' and (value['field'] == 'contact.links' or value['field'].endswith(('.link', '.url')))


def structure(content, kind, approved_source=None):
    content = upgrade(content)
    approved_source = upgrade(approved_source) if approved_source else None
    findings = []
    approved_nodes = {node['id']: node for node in nodes(approved_source)} if approved_source else {}
    ids = [node['id'] for node in nodes(content)]
    if len(ids) != len(set(ids)):
        findings.append(finding('content', 'Source and claim IDs must be unique.', 'structure'))
    if not content['contact']['name'].strip():
        findings.append(finding('contact.name', 'A name is required.', 'structure'))
    if kind == 'resume' and not any(content.get(key) for key in ('summary', 'skills', 'experience', 'projects', 'education', 'additional_sections')):
        findings.append(finding('content', 'Meaningful resume content is required.', 'structure'))
    for node in nodes(content):
        if 'text' in node and not node['text'].strip():
            findings.append(finding(node['id'], 'Text cannot be blank.', 'structure'))
        if 'text' in node and any(phrase not in node['text'] for phrase in node.get('emphasis', [])):
            findings.append(finding(node['id'], 'Bold emphasis must quote actual claim text.', 'structure'))
        if node.get('link') and not safe_link(node['link']):
            accepted = approved_nodes.get(node['id'], {}).get('link') == node['link']
            findings.append(finding(node['id'] + '.link', 'Kept as entered with your approval; rendered as plain text.' if accepted else 'Use a valid HTTP/HTTPS link.', 'structure', 'warning' if accepted else 'error'))
    for link in content['contact']['links']:
        if not link['label'].strip():
            findings.append(finding('contact.links.label', 'Give the contact link a display label.', 'structure'))
        if not link['url'] or not safe_link(link['url']):
            accepted = approved_source is not None and any(old['url'] == link['url'] and old['label'] == link['label'] for old in approved_source['contact']['links'])
            findings.append(finding('contact.links', 'Kept as entered with your approval; rendered as plain text.' if accepted else 'Use valid HTTP/HTTPS links.', 'structure', 'warning' if accepted else 'error'))
    if content.get('unresolved_links'):
        findings.append(finding('unresolved_links', 'Attach or explicitly remove the unresolved imported links before saving for use.', 'structure'))
    destinations = {}
    for source_id, _, url, _ in link_records(content):
        if source_id and source_id in destinations and destinations[source_id] != url:
            findings.append(finding('hyperlinks.source', 'One hyperlink source ID cannot describe different destinations.', 'structure'))
        destinations[source_id] = url
    approved_links = {(source_id, url, owner) for source_id, _, url, owner in link_records(approved_source)} if approved_source else set()
    for owner, key, spans in text_fields(content):
        previous_end = -1
        for i, span in enumerate(sorted(owner.get(spans, []), key=lambda x: x['start'] if isinstance(x.get('start'), int) else -1)):
            field = owner['id'] + '.' + spans
            if not valid_span(owner[key], span) or span['start'] < previous_end:
                findings.append(finding(field, 'Reattach or remove the unresolved/overlapping hyperlink.', 'structure'))
                continue
            previous_end = span['end']
            if not span['url'] or not safe_link(span['url']):
                accepted = (span.get('source_link_id'), span['url'], owner['id']) in approved_links
                findings.append(finding(f'{field}.{i}.url', 'Kept as entered with your approval; rendered as plain text.' if accepted else 'Use a valid HTTP/HTTPS/mailto link.', 'structure', 'warning' if accepted else 'error'))
    if kind == 'cover_letter':
        count = len(re.findall(r'\S+', ' '.join(p['text'] for p in content['paragraphs'])))
        if not 250 <= count <= 350 or not 3 <= len(content['paragraphs']) <= 4:
            findings.append(finding('paragraphs', 'Use 250-350 body words in three or four paragraphs.', 'structure'))
    return findings


def grounded(content, source, job, kind):
    content, source = upgrade(content), upgrade(source)
    findings = []
    index = {node['id']: node for node in nodes(source)}
    source_records = list(link_records(source))
    source_links = {source_id: url for source_id, _, url, _ in source_records}
    output_links = list(link_records(content))
    for source_id, _, url, owner in output_links:
        original = source_links.get(source_id)
        if original is None or original != url:
            findings.append(finding(str(owner) + '.links', 'Hyperlink target must match a reviewed source link.'))
            continue
        current = next((node for node in nodes(content) if node['id'] == owner), None)
        owners = {source_owner for sid, _, _, source_owner in source_records if sid == source_id}
        if not owners.intersection({'contact', owner, *(current.get('source_refs', []) if current else [])}):
            findings.append(finding(str(owner) + '.links', 'Hyperlink belongs to a different source subject.'))
    for owner, key, spans in text_fields(content):
        retained = {owner['id'], *owner.get('source_refs', [])}
        actual = {span.get('source_link_id') for span in owner.get(spans, [])}
        for source_id, label, _, source_owner in source_records:
            if source_owner in retained and label and label in owner[key] and source_id not in actual:
                findings.append(finding(owner['id'] + '.' + spans, 'Retained linked text lost its source hyperlink.'))
    if content['contact'] != source['contact']:
        findings.append(finding('contact', 'Contact details must match the reviewed base resume.'))
    if kind == 'cover_letter' and content['signature'] != source['contact']['name']:
        findings.append(finding('signature', 'Signature must match the reviewed name.'))
    for node in nodes(content):
        path = node['id']
        if 'text' in node:
            refs = node.get('source_refs', [])
            unknown = [ref for ref in refs if ref not in index and ref != 'job']
            if not refs or unknown:
                findings.append(finding(path, 'Every claim needs valid reviewed source references.', refs=refs))
                continue
            evidence = ' '.join(' '.join(text_values(index[ref])) if ref != 'job' else job.get('jd_text', '') for ref in refs)
            # Match numeric tokens, not substrings (10 is not evidence for 100).
            numbers = re.findall(r'(?<![\w])\d+(?:[.,]\d+)*[%+]?', node['text'])
            source_numbers = set(re.findall(r'(?<![\w])\d+(?:[.,]\d+)*[%+]?', evidence))
            if any(number not in source_numbers for number in numbers):
                findings.append(finding(path, 'A numeric claim is absent from the cited source. Preserve metrics and qualifiers.', refs=refs))
        elif 'title' in node or 'label' in node:
            original = index.get(path)
            if original is None:
                findings.append(finding(path, 'Retained entries and skill groups must reference an existing source ID.'))
                continue
            for field in ('title', 'organization', 'dates', 'location', 'link', 'link_label'):
                if field in node and node[field] != original.get(field, ''):
                    findings.append(finding(path + '.' + field, f'{field} must match its reviewed source entry.'))
    if kind == 'resume' and source.get('education'):
        source_ids = {entry['id'] for entry in content.get('education', [])}
        # Baseline ordering is preserved at review; require at least one original education entry.
        if not source_ids & {entry['id'] for entry in source['education']}:
            findings.append(finding('education', 'Retain a reviewed education qualification.'))
    return findings


def result(findings):
    return 'failed' if any(f['severity'] == 'error' for f in findings) else 'warnings' if findings else 'passed'
