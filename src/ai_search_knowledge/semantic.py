"""Optional local semantic retrieval with explicit availability and evidence spans.

Importing this module does not import an embedding runtime, download a model, or
call a cloud model. Model downloads require an explicit ``allow_download``.
Index/cache files are derived local artifacts; source evidence is never changed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import struct
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
SCHEMA_VERSION = 1


def _sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class SemanticUnavailable(RuntimeError):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        super().__init__(detail)


@dataclass(frozen=True)
class SemanticConfig:
    enabled: bool = True
    model_name: str = DEFAULT_MODEL
    revision: str = DEFAULT_REVISION
    dimensions: int = 384
    max_tokens: int = 512
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    model_file: str = "onnx/model.onnx"
    license: str = "MIT"
    model_cache_dir: str = "data/semantic-models"
    allow_download: bool = False
    max_download_bytes: int = 800_000_000
    batch_size: int = 8
    threads: int = 2


class EmbeddingBackend(Protocol):
    """Small injectable interface; synthetic tests need no optional packages."""
    identity: Mapping[str, Any]
    max_tokens: int

    def token_count(self, text: str, mode: str = "passage") -> int: ...
    def encode(self, texts: Sequence[str], mode: str = "passage") -> Sequence[Sequence[float]]: ...


def _configuration(root: Path, cfg: SemanticConfig | Mapping[str, Any] | None,
                   injected: bool = False) -> SemanticConfig:
    if isinstance(cfg, SemanticConfig):
        return cfg
    if cfg is None:
        path = root / "config.json"
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        cfg = settings.get("semantic", {"enabled": injected})
    allowed = SemanticConfig.__dataclass_fields__
    unknown = set(cfg) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown semantic settings: {', '.join(sorted(unknown))}")
    result = SemanticConfig(**cfg)
    if result.dimensions < 1 or result.max_tokens < 8 or result.batch_size < 1 or result.threads < 1:
        raise ValueError("Invalid semantic dimensions, token limit, batch size or threads")
    return result


def _unavailable(exc: SemanticUnavailable, **extra) -> dict:
    return {"status": "unavailable", "reason": exc.reason, "detail": str(exc), "hits": [], **extra}


class FastEmbedBackend:
    """Pinned public ONNX weights, CPU inference, exact pre-truncation counts.

    The default candidate is multilingual E5-small. Other compatible ONNX text
    encoders can be configured explicitly; their pooling/prefix/token limit must
    be evaluated before use. No remote repository Python code is executed.
    """

    def __init__(self, root: Path, config: SemanticConfig):
        if importlib.util.find_spec("fastembed") is None:
            raise SemanticUnavailable("missing_dependency", "Install the optional fastembed runtime to use semantic retrieval")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", config.model_name):
            raise ValueError("Model name must be a public Hugging Face owner/repository identifier")
        if not re.fullmatch(r"[0-9a-f]{40}", config.revision):
            raise ValueError("Pin the model to a 40-character commit revision")
        if Path(config.model_file).is_absolute() or ".." in Path(config.model_file).parts:
            raise ValueError("Model file must be a relative ONNX file path")
        from importlib.metadata import version
        try:
            from fastembed import TextEmbedding
            from fastembed.common.model_description import ModelSource, PoolingType
            from huggingface_hub import snapshot_download, try_to_load_from_cache, model_info
            from tokenizers import Tokenizer
        except (ImportError, OSError) as exc:
            raise SemanticUnavailable("runtime_import_failed", f"Optional runtime failed to import: {type(exc).__name__}: {exc}") from exc
        self.config = config
        self.max_tokens = config.max_tokens
        cache = (root / config.model_cache_dir).resolve()
        required = [config.model_file, "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
        cached = try_to_load_from_cache(config.model_name, config.model_file, revision=config.revision, cache_dir=cache)
        if not isinstance(cached, str) and not config.allow_download:
            raise SemanticUnavailable("model_not_cached", "Pinned local model is not cached; model download requires explicit allow_download=True")
        if config.allow_download:
            try:
                info = model_info(config.model_name, revision=config.revision, files_metadata=True, token=False)
                sizes = {f.rfilename: f.size for f in info.siblings}
                missing = [name for name in required if name not in sizes]
                if missing:
                    raise SemanticUnavailable("missing_model_assets", f"Pinned model is missing required files: {missing}")
                if any(sizes[name] is None for name in required):
                    raise SemanticUnavailable("unknown_download_size", "Cannot verify a bounded model download")
                if sum(sizes[name] for name in required) > config.max_download_bytes:
                    raise SemanticUnavailable("download_limit", "Selected model exceeds configured download-size limit")
            except SemanticUnavailable:
                raise
            except Exception as exc:
                raise SemanticUnavailable("model_metadata_failed", f"Could not inspect pinned public model: {type(exc).__name__}: {exc}") from exc
        try:
            model_dir = Path(snapshot_download(repo_id=config.model_name, revision=config.revision,
                allow_patterns=required, cache_dir=str(cache), local_files_only=not config.allow_download,
                token=False, max_workers=2))
            if not any(item["model"] == config.model_name for item in TextEmbedding.list_supported_models()):
                TextEmbedding.add_custom_model(model=config.model_name, pooling=PoolingType.MEAN,
                    normalization=True, sources=ModelSource(hf=config.model_name), dim=config.dimensions,
                    model_file=config.model_file, license=config.license)
            self._model = TextEmbedding(model_name=config.model_name, specific_model_path=str(model_dir),
                local_files_only=True, providers=["CPUExecutionProvider"], threads=config.threads)
            self._counter = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
            self._counter.no_truncation()
            self._counter.no_padding()
            self._model.model.tokenizer.enable_truncation(max_length=config.max_tokens)
            file_hashes = {}
            for name in required:
                h = hashlib.sha256()
                with (model_dir / name).open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(block)
                file_hashes[name] = h.hexdigest()
            self.identity = {"backend": "fastembed_onnx_cpu", "model_name": config.model_name,
                "revision": config.revision, "dimensions": config.dimensions, "max_tokens": config.max_tokens,
                "query_prefix": config.query_prefix, "passage_prefix": config.passage_prefix,
                "asset_hashes": file_hashes, "fastembed_version": version("fastembed"),
                "onnxruntime_version": version("onnxruntime"), "license": config.license}
        except Exception as exc:
            raise SemanticUnavailable("model_initialization_failed", f"Pinned ONNX model could not be loaded: {type(exc).__name__}: {exc}") from exc

    def _prefixed(self, text: str, mode: str) -> str:
        if mode not in {"query", "passage"}:
            raise ValueError("Embedding mode must be query or passage")
        return (self.config.query_prefix if mode == "query" else self.config.passage_prefix) + text

    def token_count(self, text: str, mode: str = "passage") -> int:
        return len(self._counter.encode(self._prefixed(text, mode)).ids)

    def encode(self, texts: Sequence[str], mode: str = "passage") -> list[list[float]]:
        if any(self.token_count(text, mode) > self.max_tokens for text in texts):
            raise ValueError("Semantic input exceeds the model token limit; it was not silently truncated")
        return [vector.tolist() for vector in self._model.embed(
            [self._prefixed(text, mode) for text in texts], batch_size=self.config.batch_size, parallel=None)]


_BACKENDS: dict[str, EmbeddingBackend] = {}


def load_backend(root: Path, config: SemanticConfig) -> EmbeddingBackend:
    if not config.enabled:
        raise SemanticUnavailable("disabled", "Semantic retrieval is not enabled in this library")
    key = _sha(_json({"root": str(root.resolve()), **asdict(config)}))
    if key not in _BACKENDS:
        _BACKENDS[key] = FastEmbedBackend(root, config)
    return _BACKENDS[key]


def semantic_status(root: Path, config: SemanticConfig | Mapping[str, Any] | None = None) -> dict:
    """Configuration/runtime presence only; does not import runtime or download."""
    cfg = _configuration(root, config)
    if not cfg.enabled:
        return _unavailable(SemanticUnavailable("disabled", "Semantic retrieval is not configured/enabled"))
    if importlib.util.find_spec("fastembed") is None:
        return _unavailable(SemanticUnavailable("missing_dependency", "Optional fastembed runtime is not installed"))
    return {"status": "configured", "model_name": cfg.model_name, "revision": cfg.revision,
            "model_loaded": False, "index_exists": (root / "data/semantic.sqlite").exists(),
            "note": "Runtime/model initialization and index compatibility have not been checked"}


def _unit_vector(vector: Sequence[float], dimensions: int | None = None) -> list[float]:
    result = [float(value) for value in vector]
    if not result or (dimensions is not None and len(result) != dimensions) or not all(math.isfinite(v) for v in result):
        raise ValueError("Embedding has invalid dimensions or non-finite values")
    norm = math.sqrt(sum(v * v for v in result))
    if not norm:
        raise ValueError("Embedding has zero norm")
    return [v / norm for v in result]


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(value: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(value) // 4}f", value))


def _cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS vectors (model_key TEXT, mode TEXT, content_hash TEXT, vector BLOB, PRIMARY KEY(model_key,mode,content_hash))")
    return db


def _vectors(cache: sqlite3.Connection, backend: EmbeddingBackend, texts: Sequence[str],
             mode: str, batch_size: int) -> tuple[list[list[float]], int, int]:
    key = _sha(_json(dict(backend.identity)))
    found: dict[str, list[float]] = {}
    missing = {}
    hits = 0
    for text in texts:
        sha = _sha(text)
        row = cache.execute("SELECT vector FROM vectors WHERE model_key=? AND mode=? AND content_hash=?", (key, mode, sha)).fetchone()
        if row:
            found[sha] = _unit_vector(_unpack(row[0]), int(backend.identity.get('dimensions', len(row[0]) // 4)))
            hits += 1
        else:
            missing[sha] = text
    todo = list(missing.items())
    for offset in range(0, len(todo), batch_size):
        batch = todo[offset:offset + batch_size]
        encoded = list(backend.encode([text for _, text in batch], mode))
        if len(encoded) != len(batch):
            raise ValueError("Backend returned a different number of embeddings")
        expected = int(backend.identity.get("dimensions", len(encoded[0])))
        for (sha, _), vector in zip(batch, encoded):
            vector = _unit_vector(vector, expected)
            found[sha] = vector
            cache.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)", (key, mode, sha, _pack(vector)))
        cache.commit()
    return [found[_sha(text)] for text in texts], hits, len(todo)


def _source_segments(record: Mapping[str, Any]) -> list[dict]:
    lines = record['text'].split('\n')
    positions = record.get('segments')
    if isinstance(positions, str):
        positions = json.loads(positions)
    if positions is not None:
        if len(positions) != len(lines):
            raise ValueError('Source segment coordinates do not match passage text')
        return [{**item, 'text': value} for item, value in zip(positions, lines)]
    line_map = record.get('line_map')
    return [{'text': value, 'line': line_map[i] if line_map else record['start_line'] + i,
             'start_column': record.get('start_column', 0) if i == 0 else 0,
             'end_column': (record.get('start_column', 0) if i == 0 else 0) + len(value),
             'line_length': (record.get('start_column', 0) if i == 0 else 0) + len(value)}
            for i, value in enumerate(lines)]


def _slice(record: Mapping[str, Any], start: int, end: int) -> dict:
    text = record["text"]
    prefix = text[:start]
    final = text[:end]
    first_line = prefix.count("\n")
    last_line = text[:max(start, end - 1)].count("\n")
    line_map = record.get("line_map")
    start_line = line_map[first_line] if line_map else record["start_line"] + first_line
    end_line = line_map[last_line] if line_map else record["start_line"] + last_line
    start_column = len(prefix.rsplit("\n", 1)[-1]) + (record.get("start_column", 0) if first_line == 0 else 0)
    end_column = len(final.rsplit("\n", 1)[-1])
    if end and text[end - 1] == "\n":
        end_column = len(text[:end - 1].rsplit("\n", 1)[-1]) + 1
    if last_line == 0:
        end_column += record.get("start_column", 0)
    result = dict(record)
    parent_id = str(record.get("passage_id") or _sha(_json({k: record.get(k) for k in ["id", "doc_id", "path", "start_line", "end_line", "start_column", "start_char", "text"]})))
    result.update({"parent_passage_id": parent_id, "passage_id": _sha(f"{parent_id}:{start}:{end}:{_sha(text[start:end])}"),
        "text": text[start:end], "start_line": start_line, "end_line": end_line,
        "start_column": start_column, "end_column": end_column,
        "passage_char_start": start, "passage_char_end": end, "content_hash": _sha(text[start:end])})
    if "start_char" in record:
        result["start_char"] = record["start_char"] + start
        result["end_char"] = record["start_char"] + end
    if line_map:
        result["line_map"] = line_map[first_line:last_line + 1]
    source_segments, cursor = [], 0
    for original in _source_segments(record):
        length = len(original['text'])
        first, last = max(start, cursor), min(end, cursor + length)
        if first < last:
            left, right = first - cursor, last - cursor
            source_segments.append({**original, 'text': original['text'][left:right],
                'start_column': original['start_column'] + left,
                'end_column': original['start_column'] + right})
        cursor += length + 1
    ranges = [{'path': record['path'], 'start_line': item['line'], 'end_line': item['line'],
        'start_column': item['start_column'], 'end_column': item['end_column'],
        'column_convention': 'zero_based_end_exclusive'} for item in source_segments]
    result.update({'source_segments': source_segments, 'citation_ranges': ranges,
                   'range_kind': 'bounding_lines_with_explicit_spans'})
    # Normalized passages may join several disjoint fragments of one source
    # line. Never propagate a fabricated absolute source-character interval.
    if record.get('segments') is not None:
        result.pop('start_char', None); result.pop('end_char', None)
    if ranges:
        result.update({'start_line': ranges[0]['start_line'], 'end_line': ranges[-1]['end_line'],
                       'start_column': ranges[0]['start_column'], 'end_column': ranges[-1]['end_column']})
    return result


def split_passage(record: Mapping[str, Any], backend: EmbeddingBackend) -> list[dict]:
    """Split by exact character slices; never silently truncate model input.

    Line/column coordinates are Unicode-codepoint offsets with end exclusive.
    ``passage_char_*`` always refers to the supplied parent passage. A supplied
    absolute ``start_char`` is propagated. ``line_map`` supports skipped lines.
    """
    text = record.get("text")
    if not isinstance(text, str) or not text or not isinstance(record.get("start_line"), int) or record["start_line"] < 1:
        raise ValueError("Passages need nonempty text, path, doc_id and a positive start_line")
    if not record.get("path") or not (record.get("doc_id") or record.get("id")):
        raise ValueError("Passage provenance needs path and doc_id/id")
    if record.get("line_map") and (len(record["line_map"]) != len(text.split('\n')) or
            not all(isinstance(value, int) and value > 0 for value in record['line_map'])):
        raise ValueError("line_map must contain a source line number for each logical line")
    result, start = [], 0
    while start < len(text):
        if backend.token_count(text[start:], "passage") <= backend.max_tokens:
            end = len(text)
        else:
            low, high = start + 1, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if backend.token_count(text[start:middle], "passage") <= backend.max_tokens:
                    low = middle
                else:
                    high = middle - 1
            end = low
            # Prefer a complete nearby line when that does not produce tiny slices.
            newline = text.rfind("\n", start, end)
            if newline >= start + (end - start) // 2:
                end = newline + 1
        if end <= start or backend.token_count(text[start:end], "passage") > backend.max_tokens:
            raise ValueError("Model token limit cannot encode even one source character")
        result.append(_slice(record, start, end))
        start = end
    return result


def passages_from_index(root: Path) -> list[dict]:
    path = root / "data/knowledge.sqlite"
    if not path.exists():
        raise SemanticUnavailable("evidence_index_missing", "Build the evidence index before building semantic retrieval")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    columns = {row[1] for row in db.execute("PRAGMA table_info(passages)")}
    has_details = bool(db.execute("SELECT name FROM sqlite_master WHERE name='passage_details'").fetchone())
    extras = [name for name in ["start_column", "end_column", "start_char", "end_char", "line_map"] if name in columns]
    query = "SELECT p.rowid AS passage_id,p.rowid AS passage_rowid,p.doc_id,p.text,p.start_line,p.end_line,d.kind,d.title,d.path,d.metadata" + ''.join(',p.' + name for name in extras)
    if has_details:
        query += ',pd.segments'
    query += " FROM passages p JOIN documents d ON d.id=p.doc_id"
    if has_details:
        query += ' LEFT JOIN passage_details pd ON pd.passage_rowid=p.rowid'
    query += ' ORDER BY p.rowid'
    result = []
    for row in db.execute(query):
        item = dict(row); item["metadata"] = json.loads(item["metadata"])
        if isinstance(item.get("line_map"), str):
            item["line_map"] = json.loads(item["line_map"])
        if isinstance(item.get('segments'), str):
            item['segments'] = json.loads(item['segments'])
        result.append(item)
    db.close()
    return result


def _reusable_index(root: Path, cfg: SemanticConfig) -> dict | None:
    """Check the retained artifact/spec without importing an optional runtime.

    This is not validation of installed weights or inference. Normal searching
    still loads/checks its backend identity against the manifest.
    """
    destination, evidence = root / 'data/semantic.sqlite', root / 'data/knowledge.sqlite'
    if not destination.is_file() or not evidence.is_file():
        return None
    db = None
    try:
        db = sqlite3.connect(destination.resolve().as_uri() + '?mode=ro', uri=True)
        manifest = json.loads(db.execute('SELECT value FROM manifest').fetchone()[0])
        db.execute('SELECT 1 FROM passages LIMIT 1').fetchone()
        model = manifest.get('model', {})
        spec = {name: getattr(cfg, name) for name in ['model_name', 'revision', 'dimensions',
                'max_tokens', 'query_prefix', 'passage_prefix']}
        if (manifest.get('schema_version') != SCHEMA_VERSION
                or any(model.get(name) != value for name, value in spec.items())
                or cfg.model_file not in model.get('asset_hashes', {})
                or manifest.get('model_key') != _sha(_json(model))
                or manifest.get('evidence_index_sha256') != _file_hash(evidence)):
            return None
        return manifest
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        # A malformed artifact cannot be reused. A normal rebuild may repair it,
        # and otherwise retains its usual explicit unavailable/error behavior.
        return None
    finally:
        if db is not None:
            db.close()


def build_semantic_index(root: Path, passages: Iterable[Mapping[str, Any]] | None = None, *,
        config: SemanticConfig | Mapping[str, Any] | None = None, backend: EmbeddingBackend | None = None,
        index_path: Path | None = None, cache_path: Path | None = None) -> dict:
    start = time.perf_counter(); root = Path(root).resolve()
    cfg = _configuration(root, config, backend is not None)
    try:
        if not cfg.enabled:
            raise SemanticUnavailable("disabled", "Semantic retrieval is not enabled")
        if passages is None and backend is None and index_path is None:
            retained = _reusable_index(root, cfg)
            if retained is not None:
                return {'status': 'ok', **retained, 'reused_index': True,
                        'runtime_validated': False, 'cache_hits': 0, 'embedded_unique_texts': 0,
                        'elapsed_seconds': time.perf_counter() - start,
                        'index_bytes': (root / 'data/semantic.sqlite').stat().st_size,
                        'notice': 'Unchanged evidence/spec artifact reused; current runtime/weights were not loaded or validated.'}
        backend = backend or load_backend(root, cfg)
        original = list(passages) if passages is not None else passages_from_index(root)
    except SemanticUnavailable as exc:
        return _unavailable(exc)
    prepared = [part for item in original for part in split_passage(item, backend)]
    unique = {}
    for item in prepared:
        previous = unique.get(item['passage_id'])
        if previous is not None and _json(previous) != _json(item):
            raise ValueError('Duplicate semantic passage identity has conflicting provenance')
        unique[item['passage_id']] = item
    segments = list(unique.values())
    destination = index_path or root / "data/semantic.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path or destination.with_name("semantic-vectors.sqlite")
    cache = _cache(cache_path)
    try:
        vectors, hits, misses = _vectors(cache, backend, [item["text"] for item in segments], "passage", cfg.batch_size)
    finally:
        cache.close()
    fingerprint = _sha(_json([{key: item.get(key) for key in ['passage_id','content_hash','path',
        'start_line','end_line','start_column','end_column','citation_ranges','metadata']} for item in segments]))
    evidence_path = root / 'data/knowledge.sqlite'
    manifest = {"schema_version": SCHEMA_VERSION, "built_at": _now(), "model": dict(backend.identity),
        "model_key": _sha(_json(dict(backend.identity))), "corpus_fingerprint": fingerprint,
        "parent_passages": len(original), "segments": len(segments), "silent_truncation": False,
        'duplicate_segments_omitted': len(prepared) - len(segments),
        "segmentation": "exact contiguous character slices bounded by actual model token count; no overlap",
        "evidence_index_sha256": _file_hash(evidence_path) if passages is None else None}
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix="semantic-build-", suffix=".sqlite", delete=False) as handle:
        temporary = Path(handle.name)
    db = None
    try:
        db = sqlite3.connect(temporary)
        db.executescript("CREATE TABLE manifest(value TEXT); CREATE TABLE passages(passage_id TEXT PRIMARY KEY,record TEXT,vector BLOB);")
        db.execute("INSERT INTO manifest VALUES(?)", (_json(manifest),))
        for item, vector in zip(segments, vectors):
            db.execute("INSERT INTO passages VALUES(?,?,?)", (item["passage_id"], _json(item), _pack(vector)))
        db.commit(); db.close()
        temporary.replace(destination)
    finally:
        if db is not None:
            db.close()
        temporary.unlink(missing_ok=True)
    return {"status": "ok", **manifest, 'reused_index': False, "cache_hits": hits, "embedded_unique_texts": misses,
            "elapsed_seconds": time.perf_counter() - start, "index_bytes": destination.stat().st_size}


def _matches(record: dict, filters: Mapping[str, Any] | None) -> bool:
    for key, wanted in (filters or {}).items():
        actual = record.get(key, record.get("metadata", {}).get(key))
        if isinstance(wanted, (list, tuple, set)):
            if actual not in wanted:
                return False
        elif actual != wanted:
            return False
    return True


def search_semantic(root: Path, query: str, limit: int = 5, *, filters: Mapping[str, Any] | None = None,
        config: SemanticConfig | Mapping[str, Any] | None = None, backend: EmbeddingBackend | None = None,
        index_path: Path | None = None, cache_path: Path | None = None,
        expected_corpus_fingerprint: str | None = None,
        predicate: Callable[[dict], bool] | None = None) -> dict:
    start = time.perf_counter(); root = Path(root).resolve()
    cfg = _configuration(root, config, backend is not None)
    path = index_path or root / "data/semantic.sqlite"
    db = None
    try:
        if not cfg.enabled:
            raise SemanticUnavailable("disabled", "Semantic retrieval is not enabled")
        if not path.exists():
            raise SemanticUnavailable("index_missing", "Build the local semantic index before searching")
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        manifest = json.loads(db.execute("SELECT value FROM manifest").fetchone()[0])
        if expected_corpus_fingerprint and manifest['corpus_fingerprint'] != expected_corpus_fingerprint:
            db.close()
            raise SemanticUnavailable('index_stale', 'Semantic corpus fingerprint does not match the requested evidence snapshot')
        if manifest.get('evidence_index_sha256'):
            evidence = root / 'data/knowledge.sqlite'
            if not evidence.exists() or _file_hash(evidence) != manifest['evidence_index_sha256']:
                db.close()
                raise SemanticUnavailable('index_stale', 'Evidence index changed; rebuild semantic retrieval before using its vectors')
        backend = backend or load_backend(root, cfg)
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest["model_key"] != _sha(_json(dict(backend.identity))):
            db.close()
            raise SemanticUnavailable("index_model_mismatch", "Rebuild the semantic index with the selected model/runtime configuration")
        if backend.token_count(query, "query") > backend.max_tokens:
            db.close()
            raise SemanticUnavailable("query_too_long", "Query exceeds the model token limit; narrow it instead of silently truncating")
    except SemanticUnavailable as exc:
        if db is not None:
            db.close()
        return _unavailable(exc)
    except (RuntimeError, OSError, sqlite3.Error, json.JSONDecodeError, KeyError) as exc:
        if db is not None:
            db.close()
        return _unavailable(SemanticUnavailable('runtime_error',
            f'Local semantic initialization/index failed: {type(exc).__name__}: {exc}'))
    if not query.strip():
        db.close()
        return {"status": "ok", "hits": [], "model": manifest["model"], "elapsed_seconds": time.perf_counter() - start}
    try:
        cache = None
        try:
            cache = _cache(cache_path or path.with_name("semantic-vectors.sqlite"))
            vectors, hits, misses = _vectors(cache, backend, [query], "query", 1)
        except Exception as exc:
            # Includes ONNX exceptions and corrupt/incompatible query-cache
            # vectors. User filter/config ValueErrors occur outside this block.
            return _unavailable(SemanticUnavailable('runtime_error',
                f'Local semantic inference/cache failed: {type(exc).__name__}: {exc}'))
        finally:
            if cache is not None:
                cache.close()
        scored = []
        for raw, packed in db.execute("SELECT record,vector FROM passages"):
            item = json.loads(raw)
            if _matches(item, filters) and (predicate is None or predicate(item)):
                vector = _unpack(packed)
                if len(vector) != len(vectors[0]):
                    raise ValueError("Semantic index vector dimensions are inconsistent")
                score = max(-1.0, min(1.0, sum(a * b for a, b in zip(vectors[0], vector))))
                scored.append((score, item))
    except (RuntimeError, OSError, sqlite3.Error, json.JSONDecodeError, struct.error) as exc:
        return _unavailable(SemanticUnavailable('runtime_error',
            f'Local semantic retrieval failed: {type(exc).__name__}: {exc}'))
    finally:
        db.close()
    scored.sort(key=lambda pair: (-pair[0], pair[1]["passage_id"]))
    result = []
    for score, item in scored[:max(1, min(limit, 100))]:
        result.append({**item, "id": item.get("doc_id", item.get("id")), "semantic_score": score,
                       "retrieval_mode": "semantic", "model_key": manifest["model_key"]})
    return {"status": "ok", "hits": result, "model": manifest["model"],
            "corpus_fingerprint": manifest["corpus_fingerprint"], "index_built_at": manifest["built_at"],
            "query_cache_hit": bool(hits), "elapsed_seconds": time.perf_counter() - start,
            "score_note": "Cosine similarity is a ranking signal, not factual confidence or an abstention threshold"}


def semantic_candidates(root: Path, query: str, limit: int = 50, **kwargs) -> dict:
    """Return parent FTS row IDs and mapped semantic windows for hybrid fusion.

    Callers must propagate an unavailable status; an empty candidate list is not
    permission to label lexical results as semantic. Rank fusion is preferable
    to treating shifted cosine scores as calibrated relevance probabilities.
    """
    result = search_semantic(root, query, min(100, max(20, limit * 4)), **kwargs)
    if result['status'] != 'ok':
        return {**result, 'candidates': []}
    candidates, seen = [], set()
    for rank, hit in enumerate(result['hits'], 1):
        rowid = hit.get('passage_rowid')
        if rowid is None:
            try:
                rowid = int(hit['parent_passage_id'])
            except (TypeError, ValueError):
                continue
        if rowid in seen:
            continue
        seen.add(rowid)
        candidates.append({'passage_rowid': rowid, 'score': (hit['semantic_score'] + 1) / 2,
            'semantic_cosine': hit['semantic_score'], 'semantic_rank': rank,
            'retrieval_mode': 'semantic', 'model_key': hit['model_key'],
            'source_segments': [{key: part[key] for key in ['line','start_column','end_column']}
                                for part in hit['source_segments']],
            'citation_ranges': hit['citation_ranges']})
        if len(candidates) >= limit:
            break
    return {key: value for key, value in result.items() if key != 'hits'} | {'candidates': candidates,
        'score_normalization': '(cosine+1)/2 for API range only; not a probability'}
