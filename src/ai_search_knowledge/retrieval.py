"""Bounded lexical retrieval over immutable, line-addressable evidence.

Normalization here creates a retrieval view. It never rewrites a source evidence
file, translates source text, or treats an alias match as a verified fact.
"""
from __future__ import annotations

import re
import math
import unicodedata
from functools import lru_cache
from datetime import date, datetime, time, timezone

DATA_URI = re.compile(r"data:[^\s,;()<>]+(?:;[^\s,()<>]*)?,[^\s)\]<>]+", re.I)
MARKDOWN_TARGET = re.compile(r"(?<=\]\()https?://[^\s)]+", re.I)
WORDS = re.compile(r"[\w]+(?:[.-][\w]+)*", re.UNICODE)
TOKENS = re.compile(r'\w+', re.UNICODE)
STOP = set("a an and are as at be by can for from how i in is it of on or that the their these this to was what when which who with you your compare versus vs please find show list yang dan atau di ke dari untuk dengan pada ini itu apa mana bagaimana saya aku ingin cari carikan pilih tolong bandingkan perbandingan menggunakan adalah bisa dapat sebuah apakah masih paling lebih".split())
# Grammatical scaffolding should not outvote a technology's uncommon name.
# Keep capability, hardware, licence and version words available for evidence.
STOP.update("am been being but could did do does doing had has have having he her hers herself him himself his its itself me mine myself our ours ourselves she should than them themselves then there they those through us very we were will would yourself yourselves let lets just also about into over under between within each every all any some such both either neither other same only own up down out off if because so why where whom whose may might must shall not no nor can’t don't doesn't didn't won't can't kenapa mengapa kapan siapa kami kita kamu anda kalian mereka ia dia nya tersebut saja sudah belum akan agar supaya yaitu yakni sebagai secara karena bahwa tanpa setelah sebelum saat ketika setiap semua".split())
COMMON = {"ai", "model", "models", "tool", "tools", "video", "new"}
# A deliberately small, visible research vocabulary, not a general translator.
ALIASES = (
    (("bahasa indonesia", "indonesian", "indonesia"), ("indonesian", "indonesia"), "language:indonesian"),
    (("teks ke suara", "text to speech", "text-to-speech", "tts", "model suara", "sintesis suara"), ("tts", "speech", "voice", "text-to-speech"), "capability:tts"),
    (("memori jangka panjang", "long term memory", "long-term memory"), ("memory", "consolidation", "long-term"), "topic:long-term-memory"),
    (("belajar tanpa lupa", "tanpa lupa", "continual learning", "catastrophic forgetting"), ("continual", "learning", "forgetting", "consolidation"), "topic:continual-learning"),
    (("hapus latar belakang", "hilangkan latar belakang", "background removal", "video matting"), ("background", "removal", "matting"), "capability:matting"),
    (("hemat vram", "hemat memori", "low gpu memory"), ("memory", "gpu", "efficient"), "constraint:memory-efficiency"),
    (("ukuran kecil", "model kecil", "compact model"), ("compact", "small", "parameters"), "attribute:compact"),
    (("sumber terbuka", "open source", "open-source"), ("open-source", "open", "weights"), "access:open-source"),
    (("lisensi", "licensing"), ("license", "licensing"), "attribute:license"),
    (("komersial", "commercial"), ("commercial",), "attribute:commercial"),
)
CHROME = re.compile(
    r"^(?:skip to (?:content|main content)|toggle navigation|open (?:main )?menu|"
    r"sign (?:in|up)|log(?:in| in)|copy (?:link|code)|dismiss (?:alert|notification)|"
    r"notifications?|fork|star|files and versions|community|deploy|use this model|"
    r"downloads last month|model tree|search or jump to|you must be signed in.*|"
    r"discussions?|download model|quick notebook development)$", re.I
)


def fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def query_plan(query: str) -> dict:
    normalized = fold(query)
    input_terms = list(dict.fromkeys(t for t in WORDS.findall(normalized) if t not in STOP))[:32]
    applied = []
    expanded, covered_words = list(input_terms), set()
    for phrases, variants, label in ALIASES:
        matched = [p for p in phrases if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", normalized)]
        if matched:
            applied.append({"name": label, "terms": list(variants), 'matched_phrases': matched})
            expanded.extend(variants)
            covered_words.update(word for phrase in matched for word in WORDS.findall(phrase))
    # Do not reward a translated README navigation label more than the actual
    # English concept. Matched alias phrases are scored once as concept groups.
    terms = [t for t in input_terms if t not in covered_words]
    return {"original": query, "normalized": normalized, "terms": terms, 'input_terms': input_terms,
            "expanded_terms": list(dict.fromkeys(expanded))[:64], "aliases": applied,
            "normalization_scope": "case/Unicode normalization, stopwords and explicit lexical aliases; no general translation"}


def term_matches(text: str, term: str) -> bool:
    return bool(_term_pattern(term).search(fold(text)))


@lru_cache(maxsize=2048)
def _term_pattern(term: str):
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")


@lru_cache(maxsize=2048)
def _simple_term(term: str) -> bool:
    return TOKENS.fullmatch(term) is not None


def _contains(text: str, tokens: set, term: str) -> bool:
    # Exact unigram lookup has the same Unicode word boundaries as the regex.
    # Keep literal punctuation-aware matching for versions/hyphenated phrases.
    return term in tokens if _simple_term(term) else bool(_term_pattern(term).search(text))


def weighted_query(plan: dict, document_count: int, frequencies: dict) -> dict:
    """Assign query-local document rarity, with no model/entity assumptions.

    Frequencies count distinct documents, not repeated passages/mentions. Alias
    variants are one concept so a translated navigation menu cannot earn many
    independent hits. These are ranking weights, never factual confidence.
    """
    def weight(term, key=None):
        frequency = min(document_count, max(0, frequencies.get(key or term, 0)))
        # Positive Robertson/BM25 IDF: a word in nearly every document carries
        # very little evidence, rather than receiving a full unit per match.
        rarity = math.log1p((document_count - frequency + 0.5) / (frequency + 0.5))
        base = 0.2 if term in COMMON else 0.25 if term.isdecimal() else 1.0
        return base * rarity
    return {**plan, 'term_weights': {t: weight(t) for t in plan['terms']},
            'alias_weights': {a['name']: weight(a['name']) for a in plan['aliases']},
            'weighting': 'distinct-document inverse frequency; aliases scored once; common terms and bare integers discounted'}


def _coverage(body_terms, title_terms, body_aliases, plan):
    def weight(term):
        return plan.get('term_weights', {}).get(term, 0.2 if term in COMMON else 0.25 if term.isdecimal() else 1.0)
    score = sum(weight(t) for t in body_terms) * 4
    score += sum(plan.get('alias_weights', {}).get(a, 1.0) for a in body_aliases) * 3
    score += sum(weight(t) for t in title_terms) * 0.25
    return score, {'body_terms': body_terms, 'title_terms': title_terms,
                   'body_alias_groups': body_aliases, 'title_only': not body_terms and not body_aliases}


def relevance(text: str, title: str, plan: dict, *, folded: bool = False) -> tuple[float, dict]:
    """Weighted lexical coverage with a small title contribution."""
    body, heading = (text, title) if folded else (fold(text), fold(title))
    body_tokens, title_tokens = set(TOKENS.findall(body)), set(TOKENS.findall(heading))
    body_terms = [t for t in plan["terms"] if _contains(body, body_tokens, t)]
    title_terms = [t for t in plan["terms"] if _contains(heading, title_tokens, t)]
    body_aliases = [a["name"] for a in plan["aliases"] if any(_contains(body, body_tokens, t) for t in a["terms"])]
    return _coverage(body_terms, title_terms, body_aliases, plan)


def _fragment(text: str, line: int, start: int, stop: int, line_length: int) -> dict:
    return {"text": text, "line": line, "start_column": start, "end_column": stop,
            "line_length": line_length}


def normalized_segments(lines: list[str], start_line: int = 1, fragment_chars: int = 1000) -> tuple[list[dict], dict]:
    """Return original-character spans, omitting only explicit payloads/site chrome."""
    segments, removed_uri, removed_chrome, removed_links = [], 0, 0, 0
    for offset, line in enumerate(lines):
        number = start_line + offset
        plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', line).strip().strip("#* _[]")
        if CHROME.fullmatch(plain):
            removed_chrome += 1
            continue
        spans, cursor, line_has_uri = [], 0, False
        matches = [(m.start(), m.end(), 'data') for m in DATA_URI.finditer(line)]
        matches += [(m.start(), m.end(), 'link') for m in MARKDOWN_TARGET.finditer(line)]
        for first_uri, last_uri, uri_kind in sorted(matches):
            if first_uri < cursor:
                continue
            spans.append((cursor, first_uri))
            cursor = last_uri
            removed_uri += uri_kind == 'data'
            removed_links += uri_kind == 'link'
            line_has_uri = True
        spans.append((cursor, len(line)))
        for first, last in spans:
            value = line[first:last]
            # Empty image/link punctuation is not useful source text.
            if not value.strip(" ![]()\t") and (line_has_uri or first != 0 or last != len(line)):
                continue
            if not value:
                if first == 0 and last == len(line):
                    segments.append(_fragment("", number, 0, 0, len(line)))
                continue
            while first < last:
                end = min(last, first + fragment_chars)
                if end < last:
                    boundary = line.rfind(" ", first + fragment_chars // 2, end)
                    if boundary > first:
                        end = boundary
                segments.append(_fragment(line[first:end], number, first, end, len(line)))
                first = end
    return segments, {"data_uri_omissions": removed_uri, "chrome_line_omissions": removed_chrome,
                      'link_target_omissions': removed_links}


def segment_chunks(segments: list[dict], size: int = 5500, overlap: int = 3):
    if size < 1:
        raise ValueError("chunk size must be positive")
    start = 0
    while start < len(segments):
        end, count = start, 0
        while end < len(segments):
            length = len(segments[end]["text"]) + (1 if end > start else 0)
            if end > start and count + length > size:
                break
            if length > size:
                raise ValueError("segment exceeds chunk size; fragment source lines first")
            count += length
            end += 1
        selected = segments[start:end]
        if any(s["text"].strip() for s in selected):
            yield selected
        if end == len(segments):
            break
        start = max(start + 1, end - overlap)


def segments_payload(segments: list[dict]) -> str:
    import json
    return json.dumps([{k: v for k, v in item.items() if k != "text"} for item in segments])


def load_segments(text: str, payload: str | None, start_line: int) -> tuple[list[dict], dict]:
    if payload:
        import json
        positions = json.loads(payload)
        texts = text.split("\n")
        if len(positions) != len(texts):
            raise ValueError("passage span metadata does not match normalized text")
        return [{**position, "text": value} for position, value in zip(positions, texts)], {}
    # Compatibility with indexes built before source-coordinate segments existed.
    return normalized_segments(text.split("\n"), start_line)


def citation_ranges(segments: list[dict], path: str, *, include_path: bool = False) -> list[dict]:
    """Compact contiguous original lines without hiding omitted source spans."""
    result = []
    for segment in segments:
        if (result and result[-1]['end_line'] + 1 == segment['line']
                and result[-1]['end_column'] == result[-1]['_last_line_length']
                and segment['start_column'] == 0):
            item = result[-1]
            item.update({'end_line': segment['line'], 'end_column': segment['end_column'],
                         '_last_line_length': segment['line_length']})
            item['partial_line'] = item['start_column'] != 0 or item['end_column'] != segment['line_length']
        else:
            result.append({'start_line': segment['line'], 'end_line': segment['line'],
                           'start_column': segment['start_column'], 'end_column': segment['end_column'],
                           'partial_line': segment['start_column'] != 0 or segment['end_column'] != segment['line_length'],
                           '_last_line_length': segment['line_length']})
    compact = [{key: value for key, value in item.items() if not key.startswith('_')} for item in result]
    if include_path:
        compact = [{**item, 'path': path, 'column_convention': 'zero_based_end_exclusive'} for item in compact]
    return compact


def preview(segments: list[dict], plan: dict, max_chars: int, path: str) -> dict:
    """Choose the best query-covering window and enforce a hard character budget."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not segments:
        return {"text": "", "citation_ranges": [], "truncated": False, "range_kind": "empty"}
    # Each source segment is normalized/matched once. Window candidates combine
    # those matches instead of refolding and rescanning overlapping text.
    matches = [relevance(segment['text'], '', plan)[1] for segment in segments]
    options = []
    for first in range(len(segments)):
        selected, count = [], 0
        terms, aliases = set(), set()
        for index in range(first, len(segments)):
            source = segments[index]
            room = max_chars - count - (1 if selected else 0)
            if room <= 0:
                break
            value = source["text"]
            if len(value) > room:
                if selected:
                    break
                # A long first source line must obey the same budget.
                window_start = 0
                hits = [m.start() for term in plan["expanded_terms"]
                        for m in re.finditer(re.escape(term), fold(value))]
                if hits:
                    window_start = max(0, hits[0] - min(80, max_chars // 4))
                    window_start = min(window_start, max(0, len(value) - room))
                clipped = {**source, "text": value[window_start:window_start + room],
                           "start_column": source["start_column"] + window_start,
                           "end_column": source["start_column"] + window_start + room}
                selected.append(clipped)
                count += len(clipped["text"])
                match = relevance(clipped['text'], '', plan)[1]
                terms.update(match['body_terms']); aliases.update(match['body_alias_groups'])
                break
            selected.append(source)
            count += len(value) + (1 if len(selected) > 1 else 0)
            terms.update(matches[index]['body_terms']); aliases.update(matches[index]['body_alias_groups'])
        text = "\n".join(s["text"] for s in selected)
        if not text.strip():
            continue
        score, coverage = _coverage([t for t in plan['terms'] if t in terms], [],
                                    [a['name'] for a in plan['aliases'] if a['name'] in aliases], plan)
        # Prefer compact matching windows; avoid early boilerplate when a later
        # span covers more of the user's actual evidence request.
        options.append((score, -len(text) if score else len(text), -first, selected, coverage))
    if not options:
        return {"text": "", "citation_ranges": [], "truncated": False, "range_kind": "empty"}
    _, _, _, selected, coverage = max(options, key=lambda value: value[:3])
    ranges = citation_ranges(selected, path)
    contiguous = bool(selected) and all(not s["partial_line"] for s in ranges)
    contiguous = contiguous and all(b["start_line"] == a["end_line"] + 1 for a, b in zip(ranges, ranges[1:]))
    full = len(selected) == len(segments) and selected == segments
    return {"text": "\n".join(s["text"] for s in selected), 'path': path,
            "start_line": ranges[0]["start_line"], "end_line": ranges[-1]["end_line"],
            'citation_column_convention': 'zero_based_end_exclusive',
            "citation_ranges": ranges, "truncated": not full,
            "partial_line": any(item["partial_line"] for item in ranges),
            "range_kind": "verbatim_lines" if contiguous else "bounding_lines_with_explicit_spans",
            "preview_chars": sum(len(s["text"]) for s in selected) + max(0, len(selected) - 1),
            "matched_evidence": coverage}


def focus_segments(parent: list[dict], coordinates: list[dict] | None) -> list[dict]:
    """Resolve an optional candidate's coordinates against indexed evidence.

    Provider text is never trusted or used to manufacture evidence. Coordinates
    must select existing same-line spans, including partial-line intersections.
    """
    if not coordinates:
        return parent
    result = []
    for item in coordinates:
        line = item.get('line', item.get('start_line'))
        if item.get('end_line', line) != line:
            continue
        start, end = item.get('start_column'), item.get('end_column')
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            continue
        for source in parent:
            if source['line'] != line or source['start_column'] > start or source['end_column'] < end:
                continue
            offset = start - source['start_column']
            result.append({**source, 'text': source['text'][offset:offset + end - start],
                           'start_column': start, 'end_column': end})
            break
    return result


def parse_date(value: str | None, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            result = datetime.combine(date.fromisoformat(value), time.max if end else time.min)
        else:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def filter_document(kind: str, metadata: dict, *, since: str | None = None, until: str | None = None,
                    date_basis: str = "video", unknown_dates: str = "exclude", roles=None, qualities=None) -> tuple[bool, dict]:
    if date_basis not in {"video", "source"}:
        raise ValueError("date_basis must be video or source")
    if unknown_dates not in {"exclude", "include"}:
        raise ValueError("unknown_dates must be exclude or include")
    roles = [roles] if isinstance(roles, str) else roles
    qualities = [qualities] if isinstance(qualities, str) else qualities
    if roles and not set(roles).intersection(metadata.get("link_roles", [])):
        return False, {}
    if qualities and metadata.get("quality") not in set(qualities):
        return False, {}
    lower, upper = parse_date(since), parse_date(until, end=True)
    if since and lower is None or until and upper is None:
        raise ValueError("since/until must be valid ISO dates or timestamps")
    if lower and upper and lower > upper:
        raise ValueError("since must not be after until")
    if date_basis == "video":
        candidates = ([metadata.get("video_published_at") or metadata.get("published_at")] if kind == "video" else
                      list(metadata.get("video_publication_dates", [])) + [m.get("video_published_at") for m in metadata.get("video_mentions", [])])
    else:
        candidates = ([metadata.get("source_published_at") or metadata.get("published_at")] if kind == "source" else
                      list(metadata.get("source_publication_dates", [])))
    evidenced = [(value, parse_date(value)) for value in dict.fromkeys(candidates) if value]
    evidenced = [(raw, parsed) for raw, parsed in evidenced if parsed is not None]
    matches = [raw for raw, parsed in evidenced if (lower is None or parsed >= lower) and (upper is None or parsed <= upper)]
    active = since is not None or until is not None
    accepted = not active or bool(matches) or (not evidenced and unknown_dates == "include")
    ordered_matches = sorted(matches, key=lambda raw: parse_date(raw), reverse=True)
    if not active:
        return accepted, {'basis': date_basis + '_publication', 'applied': False, 'date_known': bool(evidenced)}
    return accepted, {"basis": date_basis + "_publication", "since": since, "until": until,
                      "unknown_date_policy": unknown_dates, "date_known": bool(evidenced),
                      "matched_evidenced_dates": ordered_matches[:3], 'matched_evidenced_date_count': len(matches), "applied": active,
                      "date_only_policy": "calendar dates interpreted as UTC bounds; no video/source date substitution"}
