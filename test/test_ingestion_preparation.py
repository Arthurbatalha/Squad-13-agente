"""Aceite ING-01 com fixtures sintéticas; sem GLPI, LLM, embeddings ou índice.

Usa o tokenizer real em cache; não baixa modelos durante os testes.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

from src.glpi_integration.GLPI_Client import GLPICollection
from src.rag.article_source import source_treatment
from src.rag.preparation import prepare_source as prepare
from src.rag.chunk_contract import (
    MINILM_MAX_TOKENS, MINILM_MODEL, PREPARATION_VERSION, PrepareSource,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ing01"
MINILM_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


@pytest.fixture
def sources():
    rows = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
    for row in rows:
        row["source"] = {
            "id": row["id"],
            "title": row["title"],
            "content": (FIXTURES / row["html_file"]).read_text(encoding="utf-8"),
            "source_reference": row["source_reference"],
        }
    return rows


@pytest.fixture
def prepare_source() -> PrepareSource:
    return prepare


@pytest.fixture(scope="module")
def minilm_tokenizer():
    transformers = pytest.importorskip("transformers", reason="Tokenizer real requer transformers.")
    try:
        return transformers.AutoTokenizer.from_pretrained(
            MINILM_MODEL, revision=MINILM_REVISION, local_files_only=True,
        )
    except OSError:
        pytest.skip("Tokenizer MiniLM ausente no cache local; ver docs/ING-01.md.")


@pytest.fixture
def long_source(sources):
    source = deepcopy(sources[0]["source"])
    # Menos de 120 palavras, mas muitos subwords: fracionar por palavras não basta.
    source["content"] = "<h2>Fixture sintética longa</h2><p>INICIO-FIXTURE</p>" + "".join(
        f"<p>Etapa{i:02d}: reautenticação_multifator_incompatível VPN-FIX-691.</p>"
        for i in range(30)
    ) + "<p>FIM-FIXTURE</p>"
    return source


def render_fixture(source):
    """Oráculo de texto da fixture, sem simular a implementação do preparador."""
    html2text = pytest.importorskip("html2text")
    converter = html2text.HTML2Text()
    converter.body_width = 0
    return converter.handle(source["content"]).strip()


def assert_metadata(chunk, source, source_type, ordinal):
    assert chunk["source_type"] == source_type
    assert chunk["source_id"] == source["id"]
    assert chunk["source_reference"] == source["source_reference"]
    assert chunk["title"] == source["title"]
    assert chunk["preparation_version"] == PREPARATION_VERSION
    assert chunk["chunk_id"] == f"{PREPARATION_VERSION}:{source_type}:{source['id']}:{ordinal:04d}"
    assert isinstance(chunk["content"], str) and chunk["content"].strip()


def test_glpi04_fixture_keeps_source_id_and_normalizes_name_to_title(sources):
    article = sources[0]["source"]
    client = Mock()
    client.search_all.return_value = GLPICollection(
        endpoint=article["source_reference"], total=1, pages=1,
        items=[{"id": article["id"], "name": article["title"], "content": article["content"]}],
    )
    result, = source_treatment(client)
    assert result["id"] == article["id"]
    assert result["title"] == article["title"]
    assert result["source_reference"] == article["source_reference"]
    assert result["content"] == article["content"]  # GLPI-04 ainda entrega HTML.
    assert "name" not in result


def test_long_fixture_exceeds_real_minilm_budget_even_with_few_words(long_source, minilm_tokenizer):
    text = render_fixture(long_source)
    assert len(text.split()) < 120
    assert len(minilm_tokenizer.encode(text, add_special_tokens=True, truncation=False)) > MINILM_MAX_TOKENS


@pytest.mark.parametrize("source_index", [0, 1], ids=["article", "case"])
def test_preparation_preserves_heading_numbered_steps_and_error(
    prepare_source, minilm_tokenizer, sources, source_index,
):
    fixture = sources[source_index]
    source = fixture["source"]
    chunks = prepare_source(source, source_type=fixture["source_type"], tokenizer=minilm_tokenizer)
    assert chunks
    text = "\n".join(chunk["content"] for chunk in chunks)
    assert "".join(chunk["content"] for chunk in chunks) == render_fixture(source)
    assert "## VPN indisponível" in text
    assert f"`{fixture['error_code']}`" in text
    assert "VPN indisponível" in text
    assert fixture["error_code"] in text
    assert not re.search(r"</?(?:h2|p|ol|li|code)\b", text)
    assert re.findall(r"(?m)^\s*(\d+)\.\s", text) == ["1", "2", "3"]
    positions = [text.index(step) for step in fixture["steps"]]
    assert positions == sorted(positions)
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, source, fixture["source_type"], ordinal)


def test_long_document_respects_token_limit_without_losing_tail(
    prepare_source, minilm_tokenizer, long_source,
):
    chunks = prepare_source(long_source, source_type="article", tokenizer=minilm_tokenizer)
    assert len(chunks) > 1
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, long_source, "article", ordinal)
        tokens = minilm_tokenizer.encode(chunk["content"], add_special_tokens=True, truncation=False)
        assert len(tokens) <= MINILM_MAX_TOKENS
    text = "\n".join(chunk["content"] for chunk in chunks)
    assert "".join(chunk["content"] for chunk in chunks) == render_fixture(long_source)
    assert "INICIO-FIXTURE" in text and "FIM-FIXTURE" in text
    positions = [text.index(f"Etapa{i:02d}") for i in range(30)]
    assert positions == sorted(positions)
    assert text.count("VPN-FIX-691") >= 30


@pytest.mark.parametrize("pair", ["articles", "article_case", "same_id"], ids=str)
def test_same_title_keeps_source_identity_and_stable_chunk_ids(
    prepare_source, minilm_tokenizer, sources, pair,
):
    first, second = deepcopy(sources)
    if pair == "articles":
        second["source_type"] = "article"
        second["source"]["source_reference"] = first["source"]["source_reference"]
    elif pair == "same_id":
        second["source"]["id"] = first["source"]["id"]
    assert first["source"]["title"] == second["source"]["title"]
    for fixture in (first, second):
        fixture["source"]["content"] *= 4  # Exercita vários trechos por fonte.
    originals = deepcopy([first, second])

    def prepare(fixture):
        return prepare_source(
            fixture["source"], source_type=fixture["source_type"], tokenizer=minilm_tokenizer,
        )

    a, b = prepare(first), prepare(second)
    assert len(a) > 1 and len(b) > 1
    assert {chunk["chunk_id"] for chunk in a}.isdisjoint(chunk["chunk_id"] for chunk in b)
    for fixture, chunks, other in ((first, a, second), (second, b, first)):
        text = "\n".join(chunk["content"] for chunk in chunks)
        assert fixture["marker"] in text and other["marker"] not in text
        assert fixture["error_code"] in text and other["error_code"] not in text
        for ordinal, chunk in enumerate(chunks):
            assert_metadata(chunk, fixture["source"], fixture["source_type"], ordinal)
    # Reprocessar em ordem inversa não pode transformar posição no lote em identidade.
    assert prepare(second) == b
    assert prepare(first) == a
    assert [first, second] == originals


def test_normalized_title_is_authoritative_even_if_legacy_name_is_present(
    prepare_source, minilm_tokenizer, sources,
):
    source = deepcopy(sources[0]["source"])
    source["name"] = "Nome legado divergente (fixture sintética)"
    chunks = prepare_source(source, source_type="article", tokenizer=minilm_tokenizer)
    assert chunks
    assert all(chunk["title"] == source["title"] for chunk in chunks)


@pytest.mark.parametrize("field", ["id", "title", "content", "source_reference"])
def test_missing_required_field(sources, field):
    source = deepcopy(sources[0]["source"])
    del source[field]
    with pytest.raises(ValueError, match=field):
        prepare(source, source_type="article", tokenizer=Mock())


@pytest.mark.parametrize("field,value,error", [
    ("id", True, TypeError), ("id", "91001", TypeError),
    ("id", -1, ValueError), ("title", None, TypeError),
    ("title", "  ", ValueError), ("content", 42, TypeError),
    ("content", "", ValueError), ("source_reference", None, TypeError),
    ("source_reference", "", ValueError),
    ("source_reference", "/Assistance/Ticket", ValueError),
])
def test_invalid_source_fields(sources, field, value, error):
    source = deepcopy(sources[0]["source"])
    source[field] = value
    with pytest.raises(error, match=field):
        prepare(source, source_type="article", tokenizer=Mock())


def test_source_must_be_mapping():
    with pytest.raises(TypeError, match="source"):
        prepare(None, source_type="article", tokenizer=Mock())


@pytest.mark.parametrize("source_type", [None, "ticket", []])
def test_invalid_source_type(sources, source_type):
    with pytest.raises(ValueError, match="source_type"):
        prepare(sources[0]["source"], source_type=source_type, tokenizer=Mock())


@pytest.mark.parametrize("budget,error", [
    (True, TypeError), (128.0, TypeError), (0, ValueError),
    (-1, ValueError), (129, ValueError),
])
def test_invalid_budget(sources, budget, error):
    with pytest.raises(error, match="max_tokens"):
        prepare(sources[0]["source"], source_type="article", tokenizer=Mock(), max_tokens=budget)


def test_tokenizer_must_supply_encode(sources):
    with pytest.raises(TypeError, match="tokenizer"):
        prepare(sources[0]["source"], source_type="article", tokenizer=object())


def test_budget_must_fit_content_and_special_tokens(sources, minilm_tokenizer):
    specials = len(minilm_tokenizer.encode("", add_special_tokens=True, truncation=False))
    with pytest.raises(ValueError, match="tokens especiais"):
        prepare(sources[0]["source"], source_type="article", tokenizer=minilm_tokenizer, max_tokens=specials)


@pytest.mark.parametrize("html", ["<p> </p>", "<!-- sem conteúdo -->", "<script>alert(1)</script>"])
def test_html_without_visible_text_is_invalid(sources, minilm_tokenizer, html):
    source = dict(sources[0]["source"], content=html)
    with pytest.raises(ValueError, match="content"):
        prepare(source, source_type="article", tokenizer=minilm_tokenizer)


@pytest.mark.parametrize("html", [
    "<p>" + "reautenticação_multifator VPN-FIX-691. " * 100 + "FIM</p>",
    "<p>" + "reautenticação_multifator_" * 100 + "FIM</p>",
    "<h2>Procedimento</h2><ul><li>Abra a VPN<ul><li>Confira o perfil</li></ul></li>"
    "<li>Reconecte</li></ul><pre><code>erro = 'VPN-FIX-691'\nprint(erro)</code></pre>",
])
@pytest.mark.parametrize("budget", [32, MINILM_MAX_TOKENS])
def test_complete_markdown_survives_splitting(sources, minilm_tokenizer, html, budget):
    source = dict(sources[0]["source"], content=html)
    original = deepcopy(source)
    chunks = prepare(source, source_type="article", tokenizer=minilm_tokenizer, max_tokens=budget)
    assert chunks
    assert "".join(chunk["content"] for chunk in chunks) == render_fixture(source)
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, source, "article", ordinal)
        assert len(minilm_tokenizer.encode(chunk["content"], add_special_tokens=True, truncation=False)) <= budget
    assert source == original
    assert prepare(source, source_type="article", tokenizer=minilm_tokenizer, max_tokens=budget) == chunks


@pytest.mark.parametrize("html,expected", [
    ('<ol start="5"><li>A</li><li>B</li><li>C</li></ol>', ['5. A', '6. B', '7. C']),
    ('<ol><li value="5">A</li><li value="9">B</li><li>C</li></ol>', ['5. A', '9. B', '10. C']),
    ('<ol reversed start="3"><li>A</li><li>B</li><li>C</li></ol>', ['3. A', '2. B', '1. C']),
    ('<ol reversed><li>A</li><li>B</li><li>C</li></ol>', ['3. A', '2. B', '1. C']),
    ('<ol reversed start="8"><li>A</li><li value="4">B</li><li>C</li></ol>', ['8. A', '4. B', '3. C']),
    ('<ol start="0"><li>A</li><li value="-2">B</li><li>C</li></ol>', ['0. A', '-2. B', '-1. C']),
    ('<ol reversed="false"><li>A</li><li>B</li></ol>', ['2. A', '1. B']),
    ('<ol start="invalid"><li value="invalid">A</li><li>B</li></ol>', ['1. A', '2. B']),
    ('<ol reversed><li>A<ol start="7"><li>X</li><li>Y</li></ol></li>'
     '<li>B<ul><li>Z</li></ul></li><li>C</li></ol>',
     ['3. A', '7. X', '8. Y', '2. B', '* Z', '1. C']),
    ('<ol start="4"><li>A<ol reversed><li>X</li><li>Y</li></ol></li><li>B</li></ol>'
     '<ol><li>C</li></ol>', ['4. A', '2. X', '1. Y', '5. B', '1. C']),
    ('<ul><li value="7">A</li><li>B</li></ul>', ['* A', '* B']),
])
def test_special_list_numbering(sources, minilm_tokenizer, html, expected):
    # Expectativas literais: não usar html2text como oráculo da numeração.
    source = dict(sources[0]["source"], content=html)
    original = deepcopy(source)
    chunks = prepare(source, source_type="article", tokenizer=minilm_tokenizer)
    text = "".join(chunk["content"] for chunk in chunks)
    assert [line.strip() for line in text.splitlines() if line.strip()] == expected
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, source, "article", ordinal)
        assert len(minilm_tokenizer.encode(chunk["content"], add_special_tokens=True, truncation=False)) <= 128
    assert source == original
    assert prepare(source, source_type="article", tokenizer=minilm_tokenizer) == chunks


def test_special_numbering_survives_multiple_chunks(sources, minilm_tokenizer):
    html = '<h2>Procedimento VPN</h2><ol reversed start="40">' + ''.join(
        f'<li>Confira a etapa {i}: <code>VPN-FIX-691</code>.</li>' for i in range(20)
    ) + '</ol><p>FIM</p>'
    source = dict(sources[0]["source"], content=html)
    chunks = prepare(source, source_type="article", tokenizer=minilm_tokenizer)
    assert len(chunks) > 1
    lines = [line.strip() for line in ''.join(c['content'] for c in chunks).splitlines() if line.strip()]
    assert lines == ['## Procedimento VPN'] + [
        f'{40-i}. Confira a etapa {i}: `VPN-FIX-691`.' for i in range(20)
    ] + ['FIM']
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, source, "article", ordinal)
        assert len(minilm_tokenizer.encode(chunk["content"], add_special_tokens=True, truncation=False)) <= 128
