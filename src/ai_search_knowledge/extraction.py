"""Observable document extraction; publisher text is data, never verified truth."""
from __future__ import annotations

import io
import json
import re
from urllib.parse import urljoin, urlsplit
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from .core import FetchFailure, canonical_url, digest, now

PARSER_VERSION = '2.0.0'
DATA_URI = re.compile(r'data:(?:[\w.+-]+/[\w.+-]+)?(?:;[\w.+%=-]+)*,[^\s<>\'"\)\]]+', re.I)
DISCOVERY_KINDS = {'listing', 'profile', 'service', 'promotional'}
CHALLENGES = ('just a moment...', 'verify you are human', 'access denied',
              'enable javascript and cookies to continue', 'checking your browser',
              'this page is not available', 'something went wrong, but don’t fret',
              'you’ve been blocked', '404: not found', '404 not found', 'page not found')


def sanitize_derived_text(text: str) -> tuple[str, int]:
    """Remove inline URI payloads without decoding, fetching or executing them."""
    return DATA_URI.subn('[embedded data payload omitted]', text)


def _meta(soup: BeautifulSoup, names: list[str]) -> tuple[str | None, str | None]:
    for name in names:
        tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name}) or soup.find('meta', attrs={'itemprop': name})
        if tag and tag.get('content'):
            return str(tag['content']), name
    return None, None


def explicit_publication_date(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    value, evidence = _meta(soup, ['article:published_time', 'datePublished', 'citation_publication_date', 'DC.date.issued'])
    if value:
        return value, evidence

    def scan(item):
        if isinstance(item, dict):
            if item.get('datePublished'):
                return str(item['datePublished'])
            for child in item.values():
                if found := scan(child):
                    return found
        elif isinstance(item, list):
            for child in item:
                if found := scan(child):
                    return found
        return None

    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            if value := scan(json.loads(tag.get_text())):
                return value, 'JSON-LD datePublished'
        except (ValueError, TypeError):
            continue
    return None, None


def _kind(url: str, text: str, *, article: bool = False, research: bool = False) -> tuple[str, list[str]]:
    parsed = urlsplit(url)
    host = (parsed.hostname or '').removeprefix('www.')
    parts = [part for part in parsed.path.split('/') if part]
    path = parsed.path.lower()
    low = text.lower()
    cta = sum(marker in low for marker in ('join the waitlist', 'join waitlist', 'your intended use', 'by submitting', 'privacy policy', 'sign up', 'subscribe now'))
    technical = sum(marker in low for marker in ('architecture', 'benchmark', 'method', 'evaluation', 'inference', 'training', 'dataset', 'parameters', 'implementation', 'results'))
    if cta >= 2 and technical < 2 and len(text) < 2000:
        return 'promotional', ['cta_only_content']
    if research:
        return 'research_document', ['research_project_layout']
    if host == 'huggingface.co':
        if parts and parts[0] == 'blog':
            return 'article', ['publisher_blog_url']
        if parts and parts[0] == 'papers':
            return 'research_abstract', ['paper_abstract_url']
        if parts and parts[0] == 'spaces':
            return 'service', ['interactive_space_url']
        if parts and parts[0] == 'collections':
            return 'listing', ['collection_url']
        if len(parts) == 1:
            return 'profile', ['organization_or_profile_url']
        if ((len(parts) == 2 and parts[-1] == 'models') or 'tree' in parts
                or ('blob' in parts and path.endswith(('.pdf', '.safetensors', '.bin', '.gguf', '.ckpt')))):
            return 'listing', ['model_directory_or_listing_url']
        return ('dataset_card' if parts and parts[0] == 'datasets' else 'model_card'), ['repository_card_url']
    if host == 'github.com':
        if len(parts) == 1 or (parts and parts[0] == 'orgs'):
            return 'profile', ['organization_or_profile_url']
        if 'tree' in parts or (parts and parts[-1] in {'releases', 'issues', 'pulls'}):
            return 'listing', ['repository_directory_or_listing_url']
        if 'pull' in parts or 'issues' in parts:
            return 'technical_discussion', ['specific_repository_discussion_url']
        return 'project_documentation', ['repository_document_url']
    if host.startswith(('chat.', 'app.')) or any(segment in path for segment in ['/subscribe', '/signup', '/sign-up', '/login', '/fx/tools/']):
        return 'service', ['account_or_interactive_service_url']
    if host in {'kimi.com', 'aistudio.google.com', 'happyshrimp.ai', 'app.reve.com'} and path in {'', '/'}:
        return 'service', ['known_interactive_landing_url']
    if '/pricing' in path or '/license' in path:
        return 'commercial_terms', ['terms_or_pricing_document_url']
    return ('article' if article or '/blog/' in path else 'document'), ['visible_document_text']


def _coverage(text: str, visible: str, headings: list[str], removed: int, kind: str, reasons: list[str]) -> dict:
    normalized = ' '.join(text.lower().split())
    captured = sum(' '.join(heading.lower().split()) in normalized for heading in headings if heading)
    warnings = list(reasons)
    if headings and captured < len(headings):
        warnings.append('some_static_headings_not_captured')
    if removed:
        warnings.append('embedded_payloads_omitted_from_derived_text')
    return {'semantic_review': 'not_performed', 'audiovisual_review': 'not_performed',
            'suitability': 'discovery_only' if kind in DISCOVERY_KINDS else 'source_text_unreviewed',
            'extracted_characters': len(text), 'static_visible_characters': len(visible),
            'visible_character_ratio': round(len(text) / len(visible), 4) if visible else None,
            'headings_total': len(headings), 'headings_captured': captured,
            'data_uri_payloads_removed': removed, 'warnings': warnings,
            'measurement_scope': 'text/layout proxies; not a semantic completeness score'}


def _quality(text: str, title: str, kind: str, reasons: list[str], default: str) -> str:
    leading = (title + '\n' + text[:2500]).lower()
    if any(marker in leading for marker in CHALLENGES):
        return 'access_challenge'
    if 'cta_only_content' in reasons:
        return 'inadequate_content'
    if kind in DISCOVERY_KINDS:
        return 'discovery_only'
    if len(text.strip()) < 250:
        return 'thin_or_js_required'
    return default


def extraction_status(document: dict) -> str:
    quality = document.get('quality')
    if quality in {'access_challenge', 'inadequate_content', 'discovery_only', 'thin_or_js_required', 'ocr_required', 'service_response'}:
        return quality
    return 'ok'


def _render_region(region, url: str) -> str:
    from bs4 import BeautifulSoup, NavigableString

    rendered = BeautifulSoup(str(region), 'lxml')
    for table in list(rendered.select('table')):
        rows = [[cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'], recursive=False)] for row in table.select('tr')]
        rows = [row for row in rows if row]
        if not rows:
            continue
        width = max(map(len, rows))
        rows = [row + [''] * (width - len(row)) for row in rows]
        markdown = ['| ' + ' | '.join(cell.replace('|', '\\|') for cell in row) + ' |' for row in rows]
        markdown.insert(1, '| ' + ' | '.join(['---'] * width) + ' |')
        table.replace_with(NavigableString('\n' + '\n'.join(markdown) + '\n'))
    for heading in list(rendered.select('h1,h2,h3,h4,h5,h6')):
        heading.replace_with(NavigableString('\n' + '#' * int(heading.name[1]) + ' ' + heading.get_text(' ', strip=True) + '\n'))
    for link in list(rendered.select('a[href]')):
        target = urljoin(url, link.get('href', ''))
        label = link.get_text(' ', strip=True)
        if target.startswith(('http://', 'https://')) and label:
            link.replace_with(NavigableString(f'[{label}]({target})'))
    return re.sub(r'\n{3,}', '\n\n', rendered.get_text('\n', strip=True)).strip()


def _sanitize_dom(soup: BeautifulSoup) -> int:
    from bs4 import NavigableString

    removed = 0
    for tag in list(soup.select('script,style,nav,footer,form,button')):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        for name, value in list(tag.attrs.items()):
            if isinstance(value, str) and 'data:' in value.lower():
                clean, count = sanitize_derived_text(value)
                if count or value.lower().startswith('data:'):
                    removed += max(1, count)
                    del tag.attrs[name]
        if tag.name == 'img':
            alt = str(tag.get('alt', '')).strip()
            tag.replace_with(NavigableString(f'[Image alt text, not visual analysis: {alt}]' if alt else ''))
    for node in list(soup.find_all(string=True)):
        clean, count = sanitize_derived_text(str(node))
        if count:
            removed += count
            node.replace_with(NavigableString(clean))
    return removed


def extract_markdown(text: str, url: str, title: str | None = None) -> dict:
    clean, removed = sanitize_derived_text(text)
    heading = next((line.lstrip('# ').strip() for line in clean.splitlines() if line.startswith('# ')), None)
    title = title or heading or url
    headings = [line.lstrip('# ').strip() for line in clean.splitlines() if re.match(r'^#{1,6}\s', line)]
    kind, reasons = _kind(url, clean, article=bool(heading))
    links = [{'url': canonical_url(target), 'label': label} for label, target in re.findall(r'\[([^\]]*)\]\((https?://[^\s)]+)\)', clean)]
    return {'title': title, 'description': None, 'published_at': None, 'date_evidence': None,
            'text': clean, 'format': 'markdown', 'extraction_method': 'stored browser Markdown; payloads sanitized',
            'outbound_links': links, 'content_kind': kind,
            'classification': {'method': 'rule_based_unreviewed', 'reasons': reasons},
            'quality': _quality(clean, title, kind, reasons, 'browser_text_unreviewed'),
            'coverage': _coverage(clean, clean, headings, removed, kind, reasons),
            'parser_version': PARSER_VERSION, 'extracted_at': now()}


def extract_document(body: bytes, content_type: str, url: str) -> dict:
    content_type = content_type.lower().split(';')[0].strip()
    path = urlsplit(url).path.lower()
    if 'application/pdf' in content_type or body.startswith(b'%PDF-'):
        from pypdf import PdfReader

        pdf = PdfReader(io.BytesIO(body))
        if len(pdf.pages) > 250:
            raise FetchFailure('pdf_too_long', 'PDF exceeds 250-page limit; manual review needed')
        pages = [(page.extract_text() or '').strip() for page in pdf.pages]
        raw_text = '\n\n'.join(pages)
        text, removed = sanitize_derived_text('\n\n'.join(f'[PDF page {i}]\n{page}' for i, page in enumerate(pages, 1)))
        coverage = _coverage(text, raw_text, [], removed, 'research_document', ['figures_not_reviewed', 'ocr_not_performed'])
        quality = 'text_layer_unreviewed' if len(raw_text.strip()) >= 250 else 'ocr_required'
        return {'title': str((pdf.metadata or {}).get('/Title') or path.rsplit('/', 1)[-1]),
                'text': text, 'format': 'pdf', 'extraction_method': 'pypdf; text layer only; no OCR',
                'published_at': None, 'date_evidence': None, 'page_count': len(pages), 'description': None,
                'outbound_links': [], 'quality': quality, 'content_kind': 'research_document',
                'coverage': coverage, 'parser_version': PARSER_VERSION, 'extracted_at': now()}
    if 'json' in content_type or (path.endswith('.json') and 'html' not in content_type):
        try:
            value = json.loads(body.decode('utf-8-sig'))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise FetchFailure('invalid_json', f'JSON could not be parsed as data: {type(exc).__name__}') from exc
        removed = 0
        def clean_value(item):
            nonlocal removed
            if isinstance(item, str):
                if DATA_URI.match(item):
                    removed += 1
                    return '[embedded data payload omitted]'
                clean, count = sanitize_derived_text(item)
                removed += count
                return clean
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    _, count = sanitize_derived_text(key)
                    if count:
                        removed += count
                        key = f'[embedded data key {digest(key)[:16]}]'
                    result[key] = clean_value(child)
                return result
            if isinstance(item, list):
                return [clean_value(child) for child in item]
            return item
        clean = clean_value(value)
        text = json.dumps(clean, ensure_ascii=False, indent=2)
        title = (value.get('title') or value.get('name')) if isinstance(value, dict) else None
        title = title if isinstance(title, str) and len(title) < 250 else path.rsplit('/', 1)[-1]
        coverage = _coverage(text, text, [], removed, 'structured_data', ['structured_values_not_semantically_reviewed'])
        coverage.update({'json_top_level_type': type(value).__name__, 'json_top_level_items': len(value) if isinstance(value, (dict, list)) else None})
        return {'title': title, 'description': None, 'published_at': None, 'date_evidence': None,
                'text': text, 'format': 'json', 'extraction_method': 'JSON parsed as data; embedded payloads omitted',
                'outbound_links': [], 'quality': 'structured_data_unreviewed', 'content_kind': 'structured_data',
                'coverage': coverage, 'parser_version': PARSER_VERSION, 'extracted_at': now()}
    if content_type in {'text/plain', 'text/markdown'} or (not content_type and path.endswith(('.md', '.txt'))):
        text, removed = sanitize_derived_text(body.decode('utf-8', 'replace'))
        kind, reasons = _kind(url, text)
        return {'title': path.rsplit('/', 1)[-1], 'text': text, 'format': 'text',
                'extraction_method': 'UTF-8 plain text; embedded payloads omitted', 'published_at': None,
                'date_evidence': None, 'description': None, 'outbound_links': [], 'content_kind': kind,
                'quality': _quality(text, '', kind, reasons, 'text_unreviewed'),
                'coverage': _coverage(text, text, [], removed, kind, reasons),
                'parser_version': PARSER_VERSION, 'extracted_at': now()}
    if not any(marker in content_type for marker in ('html', 'xml', 'text/')):
        raise FetchFailure('unsupported_content', f'Unsupported content type: {content_type}')
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body.decode('utf-8', 'replace'), 'lxml')
    title, _ = _meta(soup, ['og:title', 'twitter:title'])
    title = title or (soup.title.get_text(' ', strip=True) if soup.title else url)
    description, _ = _meta(soup, ['description', 'og:description', 'twitter:description'])
    published, evidence = explicit_publication_date(soup)
    removed = _sanitize_dom(soup)
    visible = (soup.body or soup).get_text(' ', strip=True)
    headings = [tag.get_text(' ', strip=True) for tag in soup.select('h1,h2,h3,h4,h5,h6') if tag.get_text(' ', strip=True)]
    host = (urlsplit(url).hostname or '').removeprefix('www.')
    research = host.endswith('.github.io') or (host == 'research.nvidia.com' and '/labs/' in path)
    if host == 'github.com':
        article = soup.select_one('article.markdown-body, .markdown-body')
    elif host == 'huggingface.co':
        # Its first article can be a short related-paper widget, not the README.
        # Keep the established main-text extractor for substantive model cards.
        article = None
    else:
        article = soup.select_one('article')
    kind, reasons = _kind(url, visible, article=article is not None, research=research)
    links = []
    for anchor in soup.select('a[href]'):
        target = urljoin(url, anchor.get('href', ''))
        if target.startswith(('http://', 'https://')):
            links.append({'url': canonical_url(target), 'label': anchor.get_text(' ', strip=True)[:300]})
    if research or kind in DISCOVERY_KINDS:
        text = _render_region(soup.body or soup, url)
        method = 'full static research body' if research else 'visible discovery-page text'
    elif article is not None:
        text = _render_region(article, url)
        method = 'publisher article/README region'
    else:
        import trafilatura

        text = trafilatura.extract(str(soup), url=url, include_links=True, include_tables=True,
                                   include_comments=False, favor_recall=True) or ''
        method = 'trafilatura main text'
        if not text and visible:
            text = _render_region(soup.body or soup, url)
            method = 'visible body fallback; review extraction coverage'
            reasons.append('main_text_extractor_empty')
    text, trailing_removed = sanitize_derived_text(re.sub(r'\n{3,}', '\n\n', text).strip())
    coverage = _coverage(text, visible, headings, removed + trailing_removed, kind, reasons)
    return {'title': title, 'description': description, 'published_at': published, 'date_evidence': evidence,
            'text': text, 'format': 'html', 'extraction_method': method, 'outbound_links': links,
            'content_kind': kind, 'classification': {'method': 'rule_based_unreviewed', 'reasons': reasons},
            'quality': _quality(text, title, kind, reasons, 'extracted_unreviewed'), 'coverage': coverage,
            'parser_version': PARSER_VERSION, 'extracted_at': now()}
