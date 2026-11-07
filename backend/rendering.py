"""Controlled LaTeX templates and bounded compilation/PDF checks."""
from functools import lru_cache
from datetime import date
import csv
from io import StringIO
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
from urllib.parse import urlsplit

from .errors import BackendError
from .validation import safe_link
from .content import upgrade, valid_span, link_records
from .extraction import pdf_blocks

TEMPLATE_VERSION = 'inter-3'
COVER_LETTER_VERSION = 'progress-2'
COVER_LETTER_TEMPLATE = Path(__file__).resolve().parents[1] / 'reference/cover-letter-template.tex'
REFERENCE = Path(__file__).resolve().parents[1] / 'reference/resume-template.tex'


def template_version(kind):
    return COVER_LETTER_VERSION if kind == 'cover_letter' else TEMPLATE_VERSION


def escape(text):
    substitutions = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&',
                     '#': r'\#', '%': r'\%', '_': r'\_', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(substitutions.get(char, char) for char in str(text))


def claim(value):
    return rich_text(value['text'], value.get('links', []), value.get('emphasis', []))


def rich_text(text, links=(), emphasis=()):
    links = sorted(links, key=lambda link: link.get('start') if isinstance(link.get('start'), int) else -1)
    last = -1
    for link in links:
        if not valid_span(text, link) or link['start'] < last:
            raise BackendError('invalid_span', 'Reattach or remove unresolved/overlapping hyperlinks before rendering.')
        last = link['end']
    bold = [(m.start(), m.end()) for phrase in set(emphasis) if phrase for m in re.finditer(re.escape(phrase), text)]
    boundaries = {0, len(text), *(n for pair in bold for n in pair), *(n for link in links for n in (link['start'], link['end']))}
    positions, output, current, pieces = sorted(boundaries), [], None, []
    def flush():
        if pieces:
            body = ''.join(pieces)
            output.append(r'\href{' + escape(current['url']) + '}{' + body + '}' if current and safe_link(current['url']) else body)
            pieces.clear()
    for start, end in zip(positions, positions[1:]):
        link = next((link for link in links if link['start'] <= start and end <= link['end']), None)
        if link is not current:
            flush(); current = link
        piece = escape(text[start:end])
        pieces.append(r'\textbf{' + piece + '}' if any(a <= start and end <= b for a, b in bold) else piece)
    flush()
    return ''.join(output)


def hyperlink(url, label=None):
    if not safe_link(url):
        return escape(label or url)
    return r'\href{' + escape(url) + '}{' + escape(label or url) + '}'


@lru_cache(maxsize=1)
def inter_font_dir():
    if shutil.which('kpsewhich'):
        try:
            result = subprocess.run(['kpsewhich', 'Inter-Regular.otf'], capture_output=True, text=True, timeout=5)
            candidate = Path(result.stdout.strip()).parent
            if all((candidate / f'Inter-{style}.otf').is_file() for style in ('Regular','Bold','Italic')):
                return candidate
        except subprocess.SubprocessError:
            pass
    return None


@lru_cache(maxsize=1)
def roboto_font_dir():
    if shutil.which('kpsewhich'):
        try:
            result = subprocess.run(['kpsewhich', 'Roboto-Regular.otf'], capture_output=True, text=True, timeout=5)
            candidate = Path(result.stdout.strip()).parent
            if all((candidate / f'Roboto-{style}.otf').is_file() for style in ('Regular', 'Bold')):
                return candidate
        except subprocess.SubprocessError:
            pass
    return None


def displayed_date(value):
    if not value:
        return ''
    parsed = date.fromisoformat(value)
    months = ('January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December')
    return f'{parsed.day} {months[parsed.month - 1]} {parsed.year}'


def cover_contact_locations(contact):
    return [part.strip() for part in contact.get('location', '').split('|') if part.strip()]


def cover_contact_heading(link):
    try:
        parts = urlsplit(link['url'])
        host = (parts.hostname or '').lower()
        if host == 'linkedin.com' or host.endswith('.linkedin.com'):
            return 'LinkedIn'
        if parts.scheme in ('http', 'https'):
            return 'Website'
    except ValueError:
        pass
    return link['label']


def cover_contact_href(url, label):
    body = r'\seqsplit{' + escape(label) + '}'
    return r'\href{' + escape(url) + '}{' + body + '}' if safe_link(url) else body


def cover_letter_latex(content, job):
    fonts = roboto_font_dir()
    if fonts is None:
        raise BackendError('font_missing', 'Install the Roboto font package in TeX Live, then restart Jab. Résumé rendering remains available.', 503)
    contact = content['contact']
    sidebar = [r'\covername{' + escape(contact['name']) + '}',
               r'\vspace{4bp}',
               r'\coverrole{' + escape(job['title']) + '}',
               r'\vspace{10bp}\rule{11bp}{0.5bp}\par\vspace{14bp}',
               r'\begingroup\fontsize{10}{14}\selectfont']
    locations = cover_contact_locations(contact)
    sidebar.extend(escape(line) + r'\par' for line in locations)
    if contact.get('phone'):
        if locations:
            sidebar.append(r'\vspace{4bp}')
        sidebar.append(escape(contact['phone']) + r'\par\vspace{12bp}')
    sidebar.append(r'\hypersetup{urlcolor=accent,linkcolor=accent}')
    if contact.get('email'):
        email = contact['email']
        # Keep the approved email kerning when it fits; split only oversized addresses.
        sidebar.append(r'\sbox0{' + escape(email) + r'}\ifdim\wd0>\linewidth ' +
                       cover_contact_href('mailto:' + email, email) + r'\else ' +
                       hyperlink('mailto:' + email, email) + r'\fi\par\vspace{10bp}')
    for link in contact['links']:
        sidebar.append(r'\textbf{' + escape(cover_contact_heading(link)) + r'}\par')
        sidebar.append(cover_contact_href(link['url'], link['url']) + r'\par\vspace{10bp}')
    sidebar.append(r'\endgroup')
    main = []
    if content.get('letter_date'):
        main.append(r'{\color{dategray}\bfseries ' + escape(displayed_date(content['letter_date'])) + r'\par}')
    main += [r'\textbf{Hiring Team}\par', escape(job['company']) + r'\par']
    if job.get('location'):
        main.append(escape(job['location']) + r'\par')
    main += [r'\vspace{24bp}', escape(content['salutation']) + r'\par\vspace{12bp}']
    main.extend(claim(paragraph) + r'\par\vspace{12bp}' for paragraph in content['paragraphs'])
    main += [r'\vspace{8bp}', escape(content['closing']) + r'\par', escape(content['signature']) + r'\par']
    values = {'FONT_PATH': str(fonts), 'NAME': escape(contact['name']),
              'SIDEBAR': '\n'.join(sidebar), 'MAIN': '\n'.join(main)}
    return re.sub(r'@(FONT_PATH|NAME|SIDEBAR|MAIN)@', lambda match: values[match[1]], COVER_LETTER_TEMPLATE.read_text())


def preamble(contact, kind):
    source = REFERENCE.read_text().split(r'\begin{document}')[0]
    fonts = inter_font_dir()
    if fonts is None:
        raise BackendError('font_missing', 'Install the Inter font package in TeX Live, then restart Jab.', 503)
    source = re.sub(r'Path=[^,]+,Extension=', lambda _: 'Path=' + str(fonts) + '/,Extension=', source)
    source = re.sub(r'\\hypersetup\{[^\n]+\}', lambda _: r'\hypersetup{pdftitle={' + escape(contact['name']) + ' | ' + ('Resume' if kind == 'resume' else 'Cover Letter') + '},pdfauthor={' + escape(contact['name']) + '}}', source)
    return source


def header(contact):
    lines = [r'{\fontsize{19}{21}\selectfont\bfseries ' + escape(contact['name']) + r'\par}']
    details = [escape(contact[key]) for key in ('location', 'phone') if contact[key]]
    if contact['email']:
        details.append(hyperlink('mailto:' + contact['email'], contact['email']))
    if details:
        lines.append(r' \textbar{} '.join(details) + r'\par')
    if contact['links']:
        lines.append(r' \textbar{} '.join(hyperlink(link['url'], link['label']) for link in contact['links']) + r'\par')
    return '\n'.join(lines)


def entry_tex(entry, nested=False):
    pieces = [rich_text(entry[key], entry.get(key + '_links', [])) for key in ('organization', 'title') if entry[key]]
    if entry['link']:
        pieces.append(hyperlink(entry['link'], entry.get('link_label') or entry['link']))
    title = r' \textbar{} '.join(pieces)
    side = r' \textbar{} '.join(escape(entry[key]) for key in ('location', 'dates') if entry[key])
    heading = title + (r'\hfill{\normalfont ' + side + '}' if side else '')
    output = [(r'\textbf{' + heading + r'}\par') if nested else (r'\subsection*{' + heading + '}')]
    output += [claim(item) + r'\par' for item in entry['description']]
    if entry['bullets']:
        output.append(r'\begin{itemize}')
        output.extend(r'\item ' + claim(item) for item in entry['bullets'])
        output.append(r'\end{itemize}')
    output += [entry_tex(child, True) for child in entry['children']]
    return '\n'.join(output)


def latex(content, kind, job):
    content = upgrade(content)
    if kind == 'cover_letter':
        return cover_letter_latex(content, job)
    body = [header(content['contact'])]
    if kind == 'resume':
        if content['summary']:
            body.append(r'\section*{Professional Summary}')
            body.extend(claim(item) + r'\par' for item in content['summary'])
        if content['skills']:
            body += [r'\section*{Technical \& GTM Skills}', r'\begin{itemize}']
            for group in content['skills']:
                label = r'\textbf{' + escape(group['label']) + ':} ' if group['label'] else ''
                body.append(r'\item ' + label + ', '.join(claim(item) for item in group['items']))
            body.append(r'\end{itemize}')
        for key, title in (('experience','Professional Experience'),('projects','Selected Technical Project'),('education','Education & Certifications')):
            if content[key]:
                body.append(r'\section*{' + escape(title) + '}')
                body.extend(entry_tex(entry) for entry in content[key])
        for section in content['additional_sections']:
            body.append(r'\section*{' + escape(section['title']) + '}')
            body.extend(entry_tex(entry) for entry in section['entries'])
        size = r'\fontsize{9.1}{10.7}\selectfont'
    return preamble(content['contact'], kind) + '\n' + r'\begin{document}' + '\n' + size + '\n' + '\n'.join(body) + '\n' + r'\end{document}'


def required_text(content, kind, job=None):
    content = upgrade(content)
    values = [content['contact']['name']]
    if kind == 'cover_letter':
        if content.get('letter_date'):
            values.append(displayed_date(content['letter_date']))
        contact = content['contact']
        values += cover_contact_locations(contact)
        values += [contact.get(key, '') for key in ('phone', 'email')]
        for link in contact['links']:
            values += [cover_contact_heading(link), link['url']]
        values += [content[key] for key in ('salutation', 'closing', 'signature')]
        values += [p['text'] for p in content['paragraphs']]
        if job:
            values += ['Hiring Team', job['title'], job['company'], job.get('location') or '']
    else:
        def visit(node):
            if isinstance(node, dict):
                if 'text' in node:
                    values.append(node['text'])
                for key, child in node.items():
                    if key not in ('id','source_refs','emphasis','links','title_links','organization_links','unresolved_links'):
                        visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(content)
    return values


def pdf_check(path, expected, log='', kind='resume'):
    letter = kind == 'cover_letter'
    paper = 'US Letter' if letter else 'A4'
    if re.search(r'Overfull \\[hv]box|Missing character:', log):
        raise BackendError('pdf_overflow', 'PDF has overflow or missing glyphs. Shorten/edit the content; typography was not changed.')
    try:
        # TSV avoids Poppler 26's empty-metadata crash in its XHTML bbox writer.
        process = subprocess.run(['pdftotext','-tsv','-enc','UTF-8',str(path),'-'], capture_output=True, text=True, timeout=20, check=True)
        rows = list(csv.DictReader(StringIO(process.stdout), delimiter='\t', quoting=csv.QUOTE_NONE))
        pages = [row for row in rows if row['level'] == '1']
        if len(pages) != 1:
            raise BackendError('pdf_page_count', f'Output must fit on one {paper} page. Shorten the content and save a new revision.')
        width, height = float(pages[0]['width']), float(pages[0]['height'])
        target_width, target_height = (612, 792) if letter else (595.28, 841.89)
        if abs(width - target_width) > 2 or abs(height - target_height) > 2:
            raise BackendError('pdf_page_size', f'Output must use {paper} paper.')
        words = [row for row in rows if row['level'] == '5']
        for word in words:
            x, y = float(word['left']), float(word['top'])
            side, vertical = (57, 53) if letter else (10, 5)
            right = x + float(word['width'])
            # Roboto’s 24-point name has font bounds above its visible cap height.
            top = 47 if letter and x < 201 else vertical
            if (x < side or y < top or right > width - side or y + float(word['height']) > height - vertical
                    or (letter and x < 237 and right > 201)):
                raise BackendError('pdf_clipping', 'PDF text extends beyond the permitted page bounds.' +
                                   (' Shorten the content and save a new revision.' if letter else ''))
        extracted = unicodedata.normalize('NFC', ' '.join(word['text'] or '' for word in words))
    except (subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise BackendError('pdf_unreadable', 'The PDF failed text/layout verification.') from exc
    if '\ufffd' in extracted or any('\ue000' <= char <= '\uf8ff' for char in extracted):
        raise BackendError('pdf_text_mapping', 'PDF contains invalid text mappings.')
    # TeX may turn straight quotes into typographic quotes without changing the wording.
    quotes = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"'})
    norm = lambda text: re.sub(r'\s+', '', unicodedata.normalize('NFC', text).translate(quotes))
    actual = norm(extracted)
    for value in expected:
        if norm(value) not in actual:
            raise BackendError('pdf_missing_text', 'Rendered text does not match saved content. Review the affected revision.')
    return {'pages': 1, 'paper': paper, 'text_verified': True}


def available(kind='resume'):
    template = COVER_LETTER_TEMPLATE if kind == 'cover_letter' else REFERENCE
    fonts = roboto_font_dir() if kind == 'cover_letter' else inter_font_dir()
    return all(shutil.which(command) for command in ('lualatex', 'pdftotext', 'pdfinfo', 'pdftohtml')) and template.is_file() and fonts is not None


def compile_tex(tex, expected, kind='resume'):
    if not available(kind):
        raise BackendError('renderer_missing', f'Install LuaLaTeX, {"Roboto" if kind == "cover_letter" else "Inter"} and Poppler before preparing PDFs.', 503)
    with tempfile.TemporaryDirectory(prefix='jab-render-') as folder:
        folder = Path(folder)
        (folder / 'document.tex').write_text(tex)
        (folder / 'tex-var').mkdir()
        (folder / 'tex-cache').mkdir()
        env = os.environ.copy()
        env.update(TEXMFVAR='tex-var', TEXMFCACHE='tex-cache', openin_any='p', openout_any='p')
        try:
            result = subprocess.run(['lualatex','--no-shell-escape','-interaction=nonstopmode','-halt-on-error','document.tex'], cwd=folder,
                                    capture_output=True, text=True, timeout=60, env=env)
        except subprocess.TimeoutExpired as exc:
            raise BackendError('render_timeout', 'PDF compilation exceeded 60 seconds. Edit the content and retry.', 422, True) from exc
        if result.returncode or not (folder / 'document.pdf').is_file():
            raise BackendError('render_failed', 'PDF compilation failed. Check fonts and supported characters, then retry.', 422, True)
        log = (folder / 'document.log').read_text(errors='replace')
        checks = pdf_check(folder / 'document.pdf', expected, log, kind)
        return (folder / 'document.pdf').read_bytes(), checks


def render(content, kind, job):
    content = upgrade(content)
    pdf, checks = compile_tex(latex(content, kind, job), required_text(content, kind, job), kind)
    expected = [(url if kind == 'cover_letter' and owner == 'contact' else label, url)
                for _, label, url, owner in link_records(content) if url and safe_link(url)]
    if content['contact']['email']:
        expected.append((content['contact']['email'], 'mailto:' + content['contact']['email']))
    _, blocks = pdf_blocks(pdf)
    actual = [link for block in blocks for link in block.get('links', [])]
    norm = lambda value: re.sub(r'\s+', '', unicodedata.normalize('NFC', value))
    if {link['url'] for link in actual} != {url for _, url in expected}:
        raise BackendError('pdf_links_mismatch', 'Rendered PDF hyperlinks do not match the saved destinations.')
    for label, url in expected:
        if norm(label) not in norm(''.join(link['label'] for link in actual if link['url'] == url)):
            raise BackendError('pdf_link_label', 'A saved hyperlink was attached to different text in the PDF.')
    checks['hyperlinks_verified'] = len(expected)
    checks['template_version'] = template_version(kind)
    return pdf, checks
