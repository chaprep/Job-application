"""Bounded local extraction. No OCR; source text is preserved before AI organisation."""
from io import BytesIO
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .errors import BackendError

MAX_UPLOAD = 10 * 1024 * 1024


def normal(value):
    return ' '.join(value.split())


def extract(data, kind):
    if len(data) > MAX_UPLOAD:
        raise BackendError('upload_too_large', 'Upload a PDF or DOCX up to 10 MiB.', 413)
    try:
        text, blocks = pdf_blocks(data) if kind == 'pdf' else docx_blocks(data)
    except BackendError:
        raise
    except Exception as exc:
        raise BackendError('unreadable_resume', 'The file is corrupt, encrypted or unreadable. Upload a readable PDF or DOCX.') from exc
    if len(normal(text)) < 20:
        raise BackendError('no_resume_text', 'No usable text was extracted. Upload a text-based PDF or DOCX; OCR is not supported.')
    if len(text) > 150000:
        raise BackendError('resume_text_too_large', 'The resume contains too much text; upload a shorter file.')
    return text, blocks


def xml_tree(body):
    if b'<!ENTITY' in body or b'<!DOCTYPE' in body:
        raise ValueError('Unsupported XML declaration')
    return ElementTree.fromstring(body)


def pdf_blocks(data):
    # Keep existing text/encryption/page checks; Poppler's XML preserves annotated display text.
    fallback = pdf_text(data)
    if not shutil.which('pdftohtml'):
        raise BackendError('parser_missing', 'Install Poppler (including pdftohtml) to preserve résumé hyperlinks.', 503)
    with tempfile.TemporaryDirectory(prefix='jab-links-') as folder:
        source = Path(folder) / 'source.pdf'
        output = Path(folder) / 'source.xml'
        source.write_bytes(data)
        with output.open('wb') as stream:
            process = subprocess.run(['pdftohtml', '-xml', '-zoom', '1', '-i', '-hidden', '-stdout', str(source)], stdout=stream, stderr=subprocess.DEVNULL, timeout=25)
        if process.returncode or output.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Hyperlink extraction failed or exceeded output limits')
        body = output.read_bytes().replace(b'<!DOCTYPE pdf2xml SYSTEM "pdf2xml.dtd">', b'')
        root = xml_tree(body)
    blocks = []
    for page in root.findall('page'):
        colours = {font.get('id'): font.get('color') for font in page.findall('fontspec')}
        line = None
        for box in page.findall('text'):
            text, links = '', []
            def walk(node, url=None):
                nonlocal text
                url = node.get('href') if node.tag == 'a' else url
                start = len(text)
                text += node.text or ''
                for child in node:
                    walk(child, url)
                    text += child.tail or ''
                if node.tag == 'a' and len(text) > start:
                    links.append({'start': start, 'end': len(text), 'label': text[start:], 'url': url or '', 'unresolved': not bool(url), 'color': colours.get(box.get('font'))})
            walk(box)
            if not text.strip():
                continue
            top, left, width = (float(box.get(k, '0')) for k in ('top', 'left', 'width'))
            if line is None or abs(top - line['top']) > 2 or left < line['right'] - 2:
                line = {'id': f'block_{len(blocks)+1}', 'text': '', 'links': [], 'page': int(page.get('number')), 'top': top, 'right': left}
                blocks.append(line)
            gap = ' ' if line['text'] and left - line['right'] > 0.7 else ''
            shift = len(line['text']) + len(gap)
            line['text'] += gap + text
            for link in links:
                link.update(id=f'pdf_{len(blocks)}_{len(line["links"])}', start=link['start'] + shift, end=link['end'] + shift, page=line['page'], rectangle={key: box.get(key) for key in ('top', 'left', 'width', 'height')})
                line['links'].append(link)
            line['right'] = left + width
    if not blocks and normal(fallback):
        raise ValueError('Visible PDF text could not be associated with hyperlink metadata')
    return '\n'.join(b['text'] for b in blocks), blocks


def docx_blocks(data):
    if not data.startswith(b'PK\x03\x04'):
        raise ValueError('Not DOCX')
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    blocks = []
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 30 * 1024 * 1024 or 'word/document.xml' not in archive.namelist():
            raise ValueError('Invalid DOCX or expanded size exceeds limit')
        parts = sorted(n for n in archive.namelist() if re.fullmatch(r'word/header\d+\.xml', n)) + ['word/document.xml'] + sorted(n for n in archive.namelist() if re.fullmatch(r'word/footer\d+\.xml', n))
        for name in parts:
            relname = 'word/_rels/' + name.split('/')[-1] + '.rels'
            rels = {item.get('Id'): item.get('Target') for item in xml_tree(archive.read(relname))} if relname in archive.namelist() else {}
            root = xml_tree(archive.read(name))
            for paragraph in root.findall('.//w:p', ns):
                text, links, field_url, instructions = '', [], None, ''
                field_start = None
                def walk(node, url=None):
                    nonlocal text, field_url, field_start, instructions
                    tag = node.tag.rsplit('}', 1)[-1]
                    if tag == 'hyperlink':
                        url = rels.get(node.get('{' + ns['r'] + '}id'))
                        if not url and node.get('{' + ns['w'] + '}anchor'):
                            url = '#' + node.get('{' + ns['w'] + '}anchor')
                    if tag == 'fldSimple':
                        instruction = node.get('{' + ns['w'] + '}instr', '')
                        match = re.search(r'HYPERLINK\s+(?:"([^"]+)"|(\S+))', instruction, re.I)
                        url = (match[1] or match[2]) if match else None
                    start = len(text)
                    if tag == 'instrText':
                        instructions += node.text or ''
                    elif tag == 'fldChar':
                        kind = node.get('{' + ns['w'] + '}fldCharType')
                        if kind == 'begin':
                            instructions = ''; field_url = None; field_start = None
                        elif kind == 'separate':
                            match = re.search(r'HYPERLINK\s+(?:"([^"]+)"|(\S+))', instructions, re.I)
                            field_url = (match[1] or match[2]) if match else None
                            field_start = len(text)
                        elif kind == 'end' and field_start is not None and 'HYPERLINK' in instructions.upper():
                            links.append(dict(start=field_start, end=len(text), label=text[field_start:], url=field_url or '', unresolved=not bool(field_url)))
                            field_url = None; field_start = None
                    elif tag == 't':
                        text += node.text or ''
                    elif tag in ('tab', 'br', 'cr'):
                        text += ' '
                    for child in node:
                        walk(child, url)
                    if (tag == 'hyperlink' or tag == 'fldSimple' and 'HYPERLINK' in node.get('{' + ns['w'] + '}instr', '').upper()) and len(text) > start:
                        links.append(dict(start=start, end=len(text), label=text[start:], url=url or '', unresolved=not bool(url)))
                walk(paragraph)
                if not text.strip():
                    continue
                block_id = f'block_{len(blocks)+1}'
                for i, link in enumerate(links):
                    link.update(id=f'docx_{len(blocks)+1}_{i}', part=name)
                blocks.append(dict(id=block_id, text=text, links=links, part=name))
    return '\n'.join(b['text'] for b in blocks), blocks


def pdf_text(data):
    if not data.startswith(b'%PDF-'):
        raise ValueError('Not PDF')
    if not all(shutil.which(command) for command in ('pdftotext', 'pdfinfo')):
        raise BackendError('parser_missing', 'Install Poppler to read PDF résumés.', 503)
    with tempfile.TemporaryDirectory(prefix='jab-extract-') as folder:
        path = Path(folder) / 'source.pdf'
        path.write_bytes(data)
        info = subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True, timeout=10)
        if info.returncode or re.search(r'^Encrypted:\s+yes', info.stdout, re.MULTILINE):
            raise ValueError('Encrypted or unreadable PDF')
        pages = re.search(r'^Pages:\s+(\d+)', info.stdout, re.MULTILINE)
        if not pages or int(pages[1]) > 30:
            raise ValueError('Resume exceeds page limit or its pages could not be read')
        output = Path(folder) / 'source.txt'
        with output.open('wb') as stream:
            result = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', str(path), '-'], stdout=stream, stderr=subprocess.DEVNULL, timeout=20)
        if result.returncode or output.stat().st_size > 1024 * 1024:
            raise ValueError('Unreadable PDF')
        text = output.read_text(encoding='utf-8')
        if len(text) > 150000:
            raise BackendError('resume_text_too_large', 'The resume contains too much text; upload a shorter file.')
        return text


def docx_text(data):
    return docx_blocks(data)[0]
