"""Aceite ING-01 com fixtures sintéticas; sem GLPI, LLM, embeddings ou índice.

Os xfails cobrem somente a ausência do preparador. Erros de importação internos
e falhas de asserção continuam falhando. Um XPASS exige retirar a marca pendente.
"""

from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

from src.glpi_integration.GLPI_Client import GLPICollection
from src.rag.article_source import source_treatment
from src.rag.chunk_contract import (
    MINILM_MAX_TOKENS, MINILM_MODEL, PREPARATION_VERSION, PrepareSource,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ing01"
MINILM_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


class PreparationPending(NotImplementedError):
    """Somente o módulo de preparação ainda não existe nesta entrega."""


pending_preparation = pytest.mark.xfail(
    strict=True, raises=PreparationPending,
    reason="ING-01: implementar src.rag.preparation.prepare_source na virada de área",
)


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
    try:
        module = import_module("src.rag.preparation")
    except ModuleNotFoundError as exc:
        if exc.name != "src.rag.preparation":
            raise
        raise PreparationPending("Preparador ainda não implementado.") from exc
    return module.prepare_source


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


@pending_preparation
@pytest.mark.parametrize("source_index", [0, 1], ids=["article", "case"])
def test_preparation_preserves_heading_numbered_steps_and_error(
    prepare_source, minilm_tokenizer, sources, source_index,
):
    fixture = sources[source_index]
    source = fixture["source"]
    chunks = prepare_source(source, source_type=fixture["source_type"], tokenizer=minilm_tokenizer)
    assert chunks
    text = "\n".join(chunk["content"] for chunk in chunks)
    assert "VPN indisponível" in text
    assert fixture["error_code"] in text
    assert not re.search(r"</?(?:h2|p|ol|li|code)\b", text)
    assert re.findall(r"(?m)^\s*(\d+)\.\s", text) == ["1", "2", "3"]
    positions = [text.index(step) for step in fixture["steps"]]
    assert positions == sorted(positions)
    for ordinal, chunk in enumerate(chunks):
        assert_metadata(chunk, source, fixture["source_type"], ordinal)


@pending_preparation
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
    assert "INICIO-FIXTURE" in text and "FIM-FIXTURE" in text
    positions = [text.index(f"Etapa{i:02d}") for i in range(30)]
    assert positions == sorted(positions)
    assert text.count("VPN-FIX-691") >= 30


@pending_preparation
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


@pending_preparation
def test_normalized_title_is_authoritative_even_if_legacy_name_is_present(
    prepare_source, minilm_tokenizer, sources,
):
    source = deepcopy(sources[0]["source"])
    source["name"] = "Nome legado divergente (fixture sintética)"
    chunks = prepare_source(source, source_type="article", tokenizer=minilm_tokenizer)
    assert chunks
    assert all(chunk["title"] == source["title"] for chunk in chunks)
