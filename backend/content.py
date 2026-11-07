"""Lossless content adaptation and hyperlink spans (Unicode code-point offsets)."""
from copy import deepcopy
import hashlib
import re


def upgrade(value):
    def plain(node):
        if hasattr(node, 'model_dump'):
            return node.model_dump()
        if isinstance(node, dict):
            return {key: plain(child) for key, child in node.items()}
        if isinstance(node, list):
            return [plain(child) for child in node]
        return deepcopy(node)
    result = plain(value)
    if not isinstance(result, dict) or result.get('schema_version', '1') not in ('1', '2') or 'contact' not in result:
        return result
    result['schema_version'] = '2'
    result.setdefault('unresolved_links', [])
    if not isinstance(result['contact'], dict):
        return result
    links = result['contact'].get('links', [])
    if isinstance(links, list):
        result['contact']['links'] = [dict(id=f'legacy_contact_{i}', label=link, url=link, source_link_id=None) if isinstance(link, str) else link for i, link in enumerate(links)]
    def visit(node):
        if isinstance(node, dict):
            if 'text' in node:
                node.setdefault('links', [])
            if 'organization' in node and 'title' in node:
                node.setdefault('title_links', [])
                node.setdefault('organization_links', [])
                node.setdefault('link_label', '')
                node.setdefault('link_source_id', None)
            for child in list(node.values()):
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(result)
    return result


def upgrade_snapshot(value):
    result = deepcopy(value)
    if 'resume' in result:
        result['resume'] = upgrade(result['resume'])
    if result.get('source_document'):
        result['source_document']['content'] = upgrade(result['source_document']['content'])
    return result


def text_fields(content):
    """Yield mutable text owners, their text field and their span field."""
    def visit(value):
        if isinstance(value, dict):
            if 'text' in value:
                yield value, 'text', 'links'
            if 'organization' in value and 'title' in value:
                yield value, 'organization', 'organization_links'
                yield value, 'title', 'title_links'
            for key, child in value.items():
                if key not in ('links', 'title_links', 'organization_links', 'unresolved_links'):
                    yield from visit(child)
        elif isinstance(value, list):
            for child in value:
                yield from visit(child)
    yield from visit(content)


def valid_span(text, span):
    start, end = span.get('start'), span.get('end')
    return isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text) and not span.get('unresolved_label')


def link_records(content):
    """Yield source link IDs, labels, URLs and their owning facts, never traverse link metadata as facts."""
    content = upgrade(content)
    for link in content.get('contact', {}).get('links', []):
        yield link.get('source_link_id') or link['id'], link['label'], link['url'], 'contact'
    for owner, key, spans in text_fields(content):
        for span in owner.get(spans, []):
            label = owner[key][span['start']:span['end']] if valid_span(owner[key], span) else span.get('unresolved_label', '')
            yield span.get('source_link_id'), label, span['url'], owner.get('id')
        if key == 'organization' and owner.get('link'):
            yield owner.get('link_source_id') or ('legacy_entry_' + owner['id'])[:64], owner.get('link_label') or owner['link'], owner['link'], owner['id']


def freeze_link_ids(content):
    result = upgrade(content)
    for owner, key, spans in text_fields(result):
        for index, span in enumerate(owner.get(spans, [])):
            if not span.get('source_link_id'):
                # Deterministic within this version; source IDs are always paired with the frozen URL.
                identity = f'{owner["id"]}:{key}:{index}:{span["url"]}'
                span['source_link_id'] = 'link_' + hashlib.sha256(identity.encode()).hexdigest()[:40]
    return result


def remap_spans(old, new, spans):
    """Unambiguous prefix/suffix edits move a span; edits through a link retain an unresolved target."""
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    result = deepcopy(spans)
    for span in result:
        if not valid_span(old, span):
            continue
        start, end = span['start'], span['end']
        if end <= prefix:
            continue
        if start >= len(old) - suffix:
            span['start'] += len(new) - len(old)
            span['end'] += len(new) - len(old)
        else:
            span.update(start=None, end=None, unresolved_label=old[start:end])
    return result


def attach_import_links(content, blocks):
    """The parser supplies destinations; deterministic matching, not the model, attaches them."""
    result = upgrade(content)
    evidence = {link['id']: link for block in blocks for link in block.get('links', [])}
    if not evidence:
        return result
    # Rebuild model-supplied associations from parser evidence so invented associations cannot survive.
    for owner, _, spans in text_fields(result):
        owner[spans] = []
    result['unresolved_links'] = []
    contact = result['contact']
    for source in evidence.values():
        label, url = source['label'], source['url']
        if source.get('unresolved'):
            result['unresolved_links'].append(dict(id=source['id'], label=label, url=url, source_link_id=source['id'], reason='The document contains a link whose destination could not be recovered. Set its destination and place it, or remove it explicitly.'))
            continue
        if url == 'mailto:' + contact.get('email', '') and label == contact.get('email'):
            continue  # The email field already renders with this exact destination.
        matches = [link for link in contact['links'] if link['label'] in (label, url) or link['url'] in (label, url)]
        if len(matches) == 1:
            matches[0].update(label=label, url=url, source_link_id=source['id'])
            continue
        standalone = [owner for owner, key, _ in text_fields(result) if key == 'organization' and owner.get('link') in (label, url)]
        if len(standalone) == 1:
            standalone[0].update(link=url, link_label=label, link_source_id=source['id'])
            continue
        candidates = []
        for owner, key, spans in text_fields(result):
            for match in re.finditer(re.escape(label), owner[key]):
                candidates.append((owner, spans, match.start(), match.end()))
        if len(candidates) == 1:
            owner, spans, start, end = candidates[0]
            owner[spans].append(dict(start=start, end=end, url=url, source_link_id=source['id'], unresolved_label=None))
            # Older organisation prompts sometimes put the linked label into the standalone URL slot.
            if owner.get('link') in (label, url):
                owner['link'] = ''
        else:
            result['unresolved_links'].append(dict(id=source['id'], label=label, url=url, source_link_id=source['id'], reason='Choose the text this link belongs to; extraction could not associate it uniquely.'))
    return result
