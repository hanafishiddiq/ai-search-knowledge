"""Behavioral tests use a synthetic encoder; CI never downloads a model."""
import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest

from ai_search_knowledge.semantic import (
    SemanticConfig, SemanticUnavailable, build_semantic_index, load_backend,
    search_semantic, semantic_candidates, semantic_status, split_passage,
)


class SyntheticBackend:
    max_tokens = 120

    def __init__(self, model="synthetic-v1"):
        self.identity = {"model_name": model, "dimensions": 3, "max_tokens": self.max_tokens}
        self.calls = []

    def token_count(self, text, mode="passage"):
        return len(text) + 1

    def encode(self, texts, mode="passage"):
        self.calls.append((mode, list(texts)))
        output = []
        for text in texts:
            low = text.lower()
            if any(word in low for word in ["speech", "voice", "suara"]):
                output.append([1.0, 0.1, 0.0])
            elif any(word in low for word in ["video", "matting"]):
                output.append([0.0, 0.1, 1.0])
            else:
                output.append([0.1, 1.0, 0.1])
        return output


def passage(doc="source:tts", text="A speech model supports voice cloning.", line=15, kind="source"):
    return {"doc_id": doc, "kind": kind, "title": "Synthetic title", "path": f"knowledge/{doc.replace(':', '-')}.md",
            "text": text, "start_line": line, "end_line": line + text.count("\n"),
            "metadata": {"source_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "published_at": None}}


def test_disabled_or_missing_backend_is_explicit_without_false_semantic_hits(tmp_path, monkeypatch):
    assert semantic_status(tmp_path)["reason"] == "disabled"
    result = build_semantic_index(tmp_path, [passage()], config=SemanticConfig(enabled=False))
    assert result["status"] == "unavailable" and result["hits"] == []
    monkeypatch.setattr("ai_search_knowledge.semantic.importlib.util.find_spec", lambda name: None)
    result = build_semantic_index(tmp_path, [passage()], config=SemanticConfig())
    assert result["reason"] == "missing_dependency"
    assert not (tmp_path / "data/semantic.sqlite").exists()


def test_exact_unicode_slices_preserve_the_evidence_and_token_limit():
    backend = SyntheticBackend(); backend.max_tokens = 14
    original = passage(text="中文 suara\nSome second line.\nLast line.", line=8)
    original["start_char"] = 300
    original["start_column"] = 2
    parts = split_passage(original, backend)
    assert len(parts) > 1
    assert "".join(part["text"] for part in parts) == original["text"]
    for part in parts:
        first, last = part["passage_char_start"], part["passage_char_end"]
        assert part["text"] == original["text"][first:last]
        assert part["start_char"] == 300 + first
        assert part["end_char"] == 300 + last
        assert backend.token_count(part["text"]) <= backend.max_tokens
        assert part["path"] == original["path"]
        assert part["metadata"] == original["metadata"]
        assert part["start_line"] == 8 + original["text"][:first].count("\n")


def test_same_text_at_different_source_locations_retains_both_provenances(tmp_path):
    backend = SyntheticBackend()
    report = build_semantic_index(tmp_path, [passage(line=15), passage(line=30)], backend=backend)
    assert report["segments"] == 2
    assert report["embedded_unique_texts"] == 1
    result = search_semantic(tmp_path, "voice", 5, backend=backend)
    assert {hit["start_line"] for hit in result["hits"]} == {15, 30}
    assert len({hit["passage_id"] for hit in result["hits"]}) == 2


def test_content_model_and_mode_cache_avoid_reembedding_unchanged_text(tmp_path):
    backend = SyntheticBackend()
    inputs = [passage(), passage("source:video", "A video matting model.")]
    first = build_semantic_index(tmp_path, inputs, backend=backend)
    assert first["embedded_unique_texts"] == 2
    second = build_semantic_index(tmp_path, inputs, backend=backend)
    assert second["embedded_unique_texts"] == 0 and second["cache_hits"] == 2
    inputs[1] = passage("source:video", "A new video matting model.")
    third = build_semantic_index(tmp_path, inputs, backend=backend)
    assert third["embedded_unique_texts"] == 1
    q1 = search_semantic(tmp_path, "suara", backend=backend)
    q2 = search_semantic(tmp_path, "suara", backend=backend)
    assert not q1["query_cache_hit"] and q2["query_cache_hit"]
    assert q1["hits"][0]["doc_id"] == "source:tts"
    incompatible = search_semantic(tmp_path, "suara", backend=SyntheticBackend("synthetic-v2"))
    assert incompatible["status"] == "unavailable" and incompatible["reason"] == "index_model_mismatch"


def test_semantic_filters_and_shared_predicate_run_before_top_k(tmp_path):
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, [passage(), passage("note:tts", "Speech and voice.", kind="note")], backend=backend)
    result = search_semantic(tmp_path, "voice", 1, filters={"kind": "note"}, backend=backend)
    assert result["hits"][0]["kind"] == "note"
    result = search_semantic(tmp_path, "voice", 1, predicate=lambda hit: hit["doc_id"] == "source:tts", backend=backend)
    assert result["hits"][0]["doc_id"] == "source:tts"
    assert search_semantic(tmp_path, "voice", filters={"kind": "missing"}, backend=backend)["hits"] == []


def test_oversize_query_is_reported_instead_of_silently_truncated(tmp_path):
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, [passage()], backend=backend)
    result = search_semantic(tmp_path, "x" * 150, backend=backend)
    assert result["status"] == "unavailable" and result["reason"] == "query_too_long"


def test_line_map_preserves_noncontiguous_source_line_numbers():
    original = passage(text="First line\nSecond line", line=15)
    original["line_map"] = [15, 81]
    part = split_passage(original, SyntheticBackend())[0]
    assert part["start_line"] == 15 and part["end_line"] == 81


def test_normalized_disjoint_fragments_keep_exact_original_columns(tmp_path):
    record = passage(text='Important evidence\nnext fact', line=8)
    record['segments'] = [
        {'line': 8, 'start_column': 4, 'end_column': 22, 'line_length': 100},
        {'line': 8, 'start_column': 80, 'end_column': 89, 'line_length': 100},
    ]
    report = build_semantic_index(tmp_path, [record], backend=SyntheticBackend())
    result = search_semantic(tmp_path, 'evidence', backend=SyntheticBackend())['hits'][0]
    assert result['start_line'] == result['end_line'] == 8
    assert [r['start_column'] for r in result['citation_ranges']] == [4, 80]
    assert [r['end_column'] for r in result['citation_ranges']] == [22, 89]
    assert [s['text'] for s in result['source_segments']] == ['Important evidence', 'next fact']


def test_expected_corpus_fingerprint_rejects_a_different_snapshot(tmp_path):
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, [passage()], backend=backend)
    result = search_semantic(tmp_path, "voice", backend=backend, expected_corpus_fingerprint="incorrect")
    assert result["reason"] == "index_stale"


def test_candidate_adapter_keeps_parent_row_and_explicit_availability(tmp_path):
    backend = SyntheticBackend()
    record = passage();record['passage_rowid'] = 42;record['passage_id'] = 42
    build_semantic_index(tmp_path, [record], backend=backend)
    result = semantic_candidates(tmp_path, 'voice', backend=backend)
    assert result['status'] == 'ok'
    candidate = result['candidates'][0]
    assert candidate['passage_rowid'] == 42
    assert 0 <= candidate['score'] <= 1
    assert candidate['retrieval_mode'] == 'semantic'
    assert candidate['source_segments'][0]['start_column'] == 0
    unavailable = semantic_candidates(tmp_path, 'voice', config=SemanticConfig(enabled=False))
    assert unavailable['status'] == 'unavailable' and unavailable['candidates'] == []


def test_duplicate_identical_input_is_idempotent(tmp_path):
    record = passage()
    result = build_semantic_index(tmp_path, [record, dict(record)], backend=SyntheticBackend())
    assert result['segments'] == 1
    assert result['duplicate_segments_omitted'] == 1


def test_failed_encoding_keeps_previous_good_index(tmp_path):
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, [passage()], backend=backend)
    path = tmp_path / "data/semantic.sqlite"
    previous = path.read_bytes()
    def fail(texts, mode="passage"):
        raise RuntimeError("Synthetic encoder failure")
    backend.encode = fail
    with pytest.raises(RuntimeError, match="encoder failure"):
        build_semantic_index(tmp_path, [passage(text="Changed evidence.")], backend=backend)
    assert path.read_bytes() == previous


def test_evidence_index_change_is_detected_before_semantic_search(tmp_path):
    path = tmp_path / "data/knowledge.sqlite"; path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE documents(id TEXT, kind TEXT, title TEXT, path TEXT, metadata TEXT); CREATE TABLE passages(doc_id TEXT,text TEXT,start_line INT,end_line INT);")
    db.execute("INSERT INTO documents VALUES(?,?,?,?,?)", ("source:tts", "source", "Speech", "knowledge/speech.md", "{}"))
    db.execute("INSERT INTO passages VALUES(?,?,?,?)", ("source:tts", "A speech model.", 15, 15))
    db.commit(); db.close()
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, backend=backend)
    assert search_semantic(tmp_path, "voice", backend=backend)["status"] == "ok"
    db = sqlite3.connect(path); db.execute("UPDATE passages SET text='New evidence'"); db.commit(); db.close()
    assert search_semantic(tmp_path, "voice", backend=backend)["reason"] == "index_stale"


class QueryFailureBackend(SyntheticBackend):
    def encode(self, texts, mode='passage'):
        if mode == 'query':
            raise RuntimeError('Synthetic query inference failure')
        return super().encode(texts, mode)


@pytest.mark.parametrize('mode', ['auto', 'hybrid', 'semantic'])
def test_query_runtime_failure_has_explicit_status_and_honest_mode_fallback(tmp_path, monkeypatch, mode):
    from ai_search_knowledge import research as research_module
    backend = QueryFailureBackend()
    build_semantic_index(tmp_path, [passage()], backend=backend)
    monkeypatch.setattr(research_module, 'search', lambda *a, **kw: [
        {'id': 'source:lexical', 'kind': 'source', 'title': 'Retained lexical evidence',
         'path': 'knowledge/lexical.md', 'text': 'Retained lexical source context.', 'metadata': {}}])
    result = research_module.retrieve(tmp_path, 'voice', mode=mode, semantic_backend=backend)
    assert result['semantic']['status'] == 'unavailable'
    assert result['semantic']['reason'] == 'runtime_error'
    if mode == 'semantic':
        assert result['actual_mode'] == 'unavailable' and result['hits'] == []
    else:
        assert result['actual_mode'] == 'lexical'
        assert result['hits'][0]['id'] == 'source:lexical'


def test_query_cache_failure_is_explicit_without_hiding_filter_or_config_errors(tmp_path, monkeypatch):
    import ai_search_knowledge.semantic as semantic_module
    backend = SyntheticBackend()
    build_semantic_index(tmp_path, [passage()], backend=backend)
    def fail_cache(path):
        raise sqlite3.OperationalError('Synthetic read-only query cache')
    monkeypatch.setattr(semantic_module, '_cache', fail_cache)
    result = search_semantic(tmp_path, 'voice', backend=backend)
    assert result['reason'] == 'runtime_error' and result['hits'] == []
    with pytest.raises(ValueError, match='Unknown semantic settings'):
        search_semantic(tmp_path, 'voice', config={'invalid_option': True}, backend=backend)
    monkeypatch.undo()
    def invalid_filter(hit):
        raise ValueError('Invalid user filter')
    with pytest.raises(ValueError, match='Invalid user filter'):
        search_semantic(tmp_path, 'voice', backend=backend, predicate=invalid_filter)


@pytest.fixture
def reusable_artifact(tmp_path):
    """Create a complete derived artifact with a synthetic backend/spec only."""
    cfg = SemanticConfig(dimensions=3, max_tokens=120)
    backend = SyntheticBackend()
    backend.identity = {name: getattr(cfg, name) for name in ['model_name', 'revision', 'dimensions',
                        'max_tokens', 'query_prefix', 'passage_prefix']}
    backend.identity['asset_hashes'] = {cfg.model_file: 'a' * 64}
    path = tmp_path / 'data/knowledge.sqlite'; path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.executescript('CREATE TABLE documents(id TEXT,kind TEXT,title TEXT,path TEXT,metadata TEXT); '
                     'CREATE TABLE passages(doc_id TEXT,text TEXT,start_line INT,end_line INT);')
    db.execute('INSERT INTO documents VALUES(?,?,?,?,?)', ('source:synthetic', 'source', 'Speech', 'knowledge/speech.md', '{}'))
    db.execute('INSERT INTO passages VALUES(?,?,?,?)', ('source:synthetic', 'Synthetic speech evidence.', 15, 15))
    db.commit(); db.close()
    build_semantic_index(tmp_path, config=cfg, backend=backend)
    return tmp_path, cfg, backend


def test_unchanged_artifact_reuses_before_loading_tokenizer_encoder_or_runtime(reusable_artifact, monkeypatch):
    import ai_search_knowledge.semantic as semantic_module
    root, cfg, _ = reusable_artifact
    previous = (root / 'data/semantic.sqlite').read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('Unchanged artifact reuse must not load a runtime or tokenize passages')
    monkeypatch.setattr(semantic_module, 'load_backend', forbidden)
    monkeypatch.setattr(semantic_module, 'split_passage', forbidden)
    monkeypatch.setattr(semantic_module, 'passages_from_index', forbidden)
    result = build_semantic_index(root, config=cfg)
    assert result['status'] == 'ok' and result['reused_index'] is True
    assert result['runtime_validated'] is False
    assert result['embedded_unique_texts'] == result['cache_hits'] == 0
    assert (root / 'data/semantic.sqlite').read_bytes() == previous


@pytest.mark.parametrize('field,value', [
    ('model_name', 'example/other-model'), ('revision', '0' * 40), ('dimensions', 4),
    ('max_tokens', 110), ('query_prefix', 'different query: '),
    ('passage_prefix', 'different passage: '), ('model_file', 'onnx/other.onnx'),
])
def test_changed_embedding_spec_cannot_reuse_artifact(reusable_artifact, monkeypatch, field, value):
    import ai_search_knowledge.semantic as semantic_module
    root, cfg, _ = reusable_artifact
    calls = []
    def need_runtime(*args):
        calls.append(True)
        raise SemanticUnavailable('synthetic_runtime_needed', 'A changed spec needs the normal build path')
    monkeypatch.setattr(semantic_module, 'load_backend', need_runtime)
    result = build_semantic_index(root, config=replace(cfg, **{field: value}))
    assert calls == [True] and result['reason'] == 'synthetic_runtime_needed'


def test_changed_evidence_index_cannot_reuse_artifact(reusable_artifact, monkeypatch):
    import ai_search_knowledge.semantic as semantic_module
    root, cfg, _ = reusable_artifact
    db = sqlite3.connect(root / 'data/knowledge.sqlite')
    db.execute("UPDATE passages SET text='Changed evidence.'"); db.commit(); db.close()
    def need_runtime(*args):
        raise SemanticUnavailable('synthetic_runtime_needed', 'Changed evidence needs the normal build path')
    monkeypatch.setattr(semantic_module, 'load_backend', need_runtime)
    assert build_semantic_index(root, config=cfg)['reason'] == 'synthetic_runtime_needed'


@pytest.mark.parametrize('injection', ['passages', 'backend', 'index_path'])
def test_explicit_inputs_skip_whole_artifact_reuse(reusable_artifact, monkeypatch, injection):
    import ai_search_knowledge.semantic as semantic_module
    root, cfg, backend = reusable_artifact
    def forbidden(*args):
        pytest.fail('Explicit inputs must skip whole-index reuse')
    monkeypatch.setattr(semantic_module, '_reusable_index', forbidden)
    if injection == 'backend':
        result = build_semantic_index(root, config=cfg, backend=backend)
        assert result['reused_index'] is False
    else:
        def need_runtime(*args):
            raise SemanticUnavailable('synthetic_runtime_needed', 'Explicit input normal build')
        monkeypatch.setattr(semantic_module, 'load_backend', need_runtime)
        kwargs = {'passages': [passage()]} if injection == 'passages' else {'index_path': root / 'data/semantic.sqlite'}
        assert build_semantic_index(root, config=cfg, **kwargs)['reason'] == 'synthetic_runtime_needed'
