"""Testes de integração do Delta Sync com Chroma real, falhas injetadas e reinícios (ING-04)."""

import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src").is_dir()
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.chroma_config import IndexConfig
from src.rag.chroma_store import ChromaGenerationStore
from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.embeddings import EmbeddingUnavailable
from src.rag.manifest import load_manifest, save_manifest_atomic
from src.rag.sync import (
    CandidateValidationError,
    CollectionBatch,
    reconcile_store_with_manifest,
    run_delta_sync,
    validate_candidate,
)


def _make_config(revision: str = "e5-rev-1") -> IndexConfig:
    return IndexConfig(
        model="intfloat/multilingual-e5-small",
        revision=revision,
        dimension=384,
    )


def _make_article(
    article_id: int,
    title: str,
    content: str,
    *,
    eligible: bool = True,
) -> dict:
    return {
        "id": article_id,
        "title": title,
        "content": content,
        "source_reference": "/Knowledgebase/Article",
        "eligible": eligible,
    }


def _fake_prepare(article: dict) -> list[dict]:
    """Divide o conteúdo por '||' em chunks válidos no contrato PreparedChunk (ING-01)."""
    parts = [part.strip() for part in article["content"].split("||") if part.strip()]
    return [
        {
            "source_type": "article",
            "source_id": article["id"],
            "source_reference": article["source_reference"],
            "title": article["title"],
            "chunk_id": f"{PREPARATION_VERSION}:article:{article['id']}:{idx:04d}",
            "content": part,
            "preparation_version": PREPARATION_VERSION,
        }
        for idx, part in enumerate(parts)
    ]


def _deterministic_vector(text: str, dimension: int = 384) -> np.ndarray:
    """Produz um vetor float32 determinístico e normalizado (norma L2 = 1)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "little")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dimension).astype(np.float32)
    return vec / np.linalg.norm(vec)


class _CountingEncoder:
    """Fake de embeddings determinístico que regista chamadas e permite injetar falhas."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.calls: int = 0
        self.encoded_chunk_ids: list[str] = []
        self.fail_with: Exception | None = None

    def __call__(self, chunks: list[dict]) -> np.ndarray:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        if not chunks:
            return np.empty((0, self.dimension), dtype=np.float32)
        self.encoded_chunk_ids.extend(chunk["chunk_id"] for chunk in chunks)
        return np.stack([_deterministic_vector(chunk["content"], self.dimension) for chunk in chunks])


# ------------------------------------------------------------------ 1. Carga inicial e sem mudanças


def test_initial_sync_and_no_changes_skips_embeddings_and_updates_checked_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter([
        "2026-11-19T10:00:00+00:00",
        "2026-11-19T10:05:00+00:00",
    ])
    monkeypatch.setattr("src.rag.sync._utc_now", lambda: next(timestamps))

    store = ChromaGenerationStore(tmp_path, _make_config())
    encoder = _CountingEncoder()
    articles = [
        _make_article(10, "VPN Corporativa", "Instale o cliente VPN||Informe suas credenciais"),
        _make_article(20, "Impressora", "Selecione a fila do andar"),
    ]

    first = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )

    assert first.status == "published"
    assert first.generation == 1
    assert first.vectors_computed == 3
    assert store.active_generation() == 1
    assert encoder.calls == 1

    # Segunda execução idêntica: não calcula vetores nem cria nova geração
    second = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )

    assert second.status == "no_changes"
    assert second.generation == 1
    assert second.vectors_computed == 0
    assert encoder.calls == 1
    assert store.active_generation() == 1

    manifest = load_manifest(first.manifest_path)
    assert manifest["active_generation"] == 1
    assert manifest["last_published_at"] == "2026-11-19T10:00:00+00:00"
    assert manifest["last_checked_at"] == "2026-11-19T10:05:00+00:00"

    with store.capture_active() as reader:
        hits = reader.query(_deterministic_vector("Selecione a fila do andar"), limit=1)
    assert hits[0]["source_id"] == 20
    assert hits[0]["title"] == "Impressora"


# ------------------------------------------------------------------ 2. Só metadados (sem reembutir)


def test_metadata_only_update_reuses_all_vectors_without_reembedding(tmp_path: Path) -> None:
    store = ChromaGenerationStore(tmp_path, _make_config())
    encoder = _CountingEncoder()

    initial_articles = [
        _make_article(10, "VPN Antigo", "Passo 1 VPN||Passo 2 VPN"),
        _make_article(20, "Email", "Configurar SMTP"),
    ]
    first = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=initial_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    assert first.vectors_computed == 3
    assert encoder.calls == 1

    # Altera apenas o título do artigo 10 mantendo exatamente o mesmo texto
    renamed_articles = [
        _make_article(10, "VPN Corporativa Atualizada", "Passo 1 VPN||Passo 2 VPN"),
        _make_article(20, "Email", "Configurar SMTP"),
    ]
    second = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=renamed_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.generation == 2
    assert second.delta["metadata_modified"] == [10]
    assert second.delta["content_modified"] == []
    assert second.vectors_computed == 0
    assert encoder.calls == 1  # nenhum vetor foi recalculado

    with store.capture_active() as reader:
        hits = reader.query(_deterministic_vector("Passo 1 VPN"), limit=1)
    assert hits[0]["source_id"] == 10
    assert hits[0]["title"] == "VPN Corporativa Atualizada"


# ------------------------------------------------------------------ 3. Edição de 5 para 3 chunks e remoção de inelegíveis


def test_edit_5_to_3_chunks_leaves_exactly_3_and_removes_ineligible(tmp_path: Path) -> None:
    store = ChromaGenerationStore(tmp_path, _make_config())
    encoder = _CountingEncoder()

    initial_articles = [
        _make_article(10, "Manual Rede", "T1||T2||T3||T4||T5"),
        _make_article(20, "Senha", "S1||S2"),
        _make_article(30, "Artigo Temporário", "Remover depois"),
    ]
    first = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=initial_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    assert first.chunks_total == 8
    assert first.vectors_computed == 8

    # Artigo 10 cai de 5 para 3 chunks (2 reaproveitados + 1 alterado); artigo 30 fica inelegível
    updated_articles = [
        _make_article(10, "Manual Rede", "T1||T2||T3-revisado"),
        _make_article(20, "Senha", "S1||S2"),
        _make_article(30, "Artigo Temporário", "Remover depois", eligible=False),
    ]
    second = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=updated_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.delta["content_modified"] == [10]
    assert second.delta["same"] == [20]
    assert second.delta["deleted"] == [30]
    assert second.chunks_total == 5
    assert second.vectors_computed == 1  # apenas o chunk alterado (0002)

    sources_by_id = {s["source_id"]: s for s in store.sources(second.generation)}
    assert set(sources_by_id) == {10, 20}
    assert sources_by_id[10]["chunk_ids"] == [
        f"{PREPARATION_VERSION}:article:10:0000",
        f"{PREPARATION_VERSION}:article:10:0001",
        f"{PREPARATION_VERSION}:article:10:0002",
    ]

    snapshot = store.read_generation(second.generation)
    art10_chunks = [c for c in snapshot.chunks if c["source_id"] == 10]
    assert len(art10_chunks) == 3
    assert [c["content"] for c in art10_chunks] == ["T1", "T2", "T3-revisado"]
    assert all(c["source_id"] != 30 for c in snapshot.chunks)

    manifest = load_manifest(second.manifest_path)
    assert 30 not in manifest["sources"]
    assert len(manifest["sources"][10]["chunk_ids"]) == 3


# ------------------------------------------------------------------ 4. Mudança de versão/modelo


def test_index_config_change_forces_full_reembed(tmp_path: Path) -> None:
    articles = [
        _make_article(10, "VPN", "Bloco 1||Bloco 2"),
        _make_article(20, "Wi-Fi", "Bloco 3"),
    ]
    encoder = _CountingEncoder()

    store_v1 = ChromaGenerationStore(tmp_path, _make_config(revision="e5-rev-1"))
    first = run_delta_sync(
        store=store_v1,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    assert first.generation == 1
    assert first.vectors_computed == 3

    # Nova revisão do modelo no mesmo diretório: exige reembutir tudo sem reutilizar vetores antigos
    store_v2 = ChromaGenerationStore(tmp_path, _make_config(revision="e5-rev-2"))
    second = run_delta_sync(
        store=store_v2,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.generation == 2
    assert second.delta["content_modified"] == [10, 20]
    assert second.vectors_computed == 3
    assert store_v2.active_generation() == 2

    manifest = load_manifest(second.manifest_path)
    assert manifest["index_config"]["revision"] == "e5-rev-2"


# ------------------------------------------------------------------ 5. Injeção de falhas em cada etapa


def test_failures_in_collect_encode_write_and_validate_preserve_active_and_allow_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": "2026-11-19T11:00:00+00:00"}
    monkeypatch.setattr("src.rag.sync._utc_now", lambda: clock["now"])

    store = ChromaGenerationStore(tmp_path, _make_config())
    encoder = _CountingEncoder()

    v1_articles = [_make_article(10, "Guia Base", "Texto original")]
    first = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v1_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    manifest_before = load_manifest(first.manifest_path)

    # Avança o relógio para provar que nenhuma falha altera last_checked_at nem last_published_at
    clock["now"] = "2026-11-19T11:10:00+00:00"
    v2_articles = [
        _make_article(10, "Guia Base", "Texto atualizado"),
        _make_article(20, "Novo Artigo", "Conteúdo novo"),
    ]

    # (a) Falha na coleta
    def _broken_collect() -> CollectionBatch:
        raise ConnectionError("falha de rede na coleta GLPI")

    with pytest.raises(ConnectionError, match="coleta GLPI"):
        run_delta_sync(
            store=store,
            collect_fn=_broken_collect,
            prepare_fn=_fake_prepare,
            encode_fn=encoder,
        )
    assert store.active_generation() == 1
    assert load_manifest(first.manifest_path) == manifest_before

    # (b) Falha no modelo de embeddings (E5)
    encoder.fail_with = EmbeddingUnavailable("falha simulada no encoder E5")
    with pytest.raises(EmbeddingUnavailable, match="encoder E5"):
        run_delta_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
            prepare_fn=_fake_prepare,
            encode_fn=encoder,
        )
    encoder.fail_with = None
    assert store.active_generation() == 1
    assert load_manifest(first.manifest_path) == manifest_before

    # (c) Falha na gravação da coleção Chroma
    def _broken_create_collection(*args, **kwargs):
        raise RuntimeError("falha simulada na gravação Chroma")

    with monkeypatch.context() as mp:
        mp.setattr(store._client, "create_collection", _broken_create_collection)
        with pytest.raises(RuntimeError, match="gravação Chroma"):
            run_delta_sync(
                store=store,
                collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
                prepare_fn=_fake_prepare,
                encode_fn=encoder,
            )
    assert store.active_generation() == 1
    assert load_manifest(first.manifest_path) == manifest_before

    # (d) Falha na validação da candidata
    def _broken_validator(*args, **kwargs):
        raise CandidateValidationError("candidata reprovada na consulta de validação")

    with pytest.raises(CandidateValidationError, match="reprovada"):
        run_delta_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
            prepare_fn=_fake_prepare,
            encode_fn=encoder,
            validator_fn=_broken_validator,
        )
    assert store.active_generation() == 1
    assert load_manifest(first.manifest_path) == manifest_before

    # Validação real também reprova quando a lista esperada diverge da candidata gravada
    with pytest.raises(CandidateValidationError):
        validate_candidate(store, 1, [])

    # (e) Repetição após falhas conclui normalmente
    clock["now"] = "2026-11-19T11:20:00+00:00"
    retry = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    assert retry.status == "published"
    assert retry.generation > 1
    assert store.active_generation() == retry.generation
    assert load_manifest(retry.manifest_path)["last_published_at"] == "2026-11-19T11:20:00+00:00"


# ------------------------------------------------------------------ 6. Reinícios antes e depois da publicação


def test_restart_before_and_after_publication_respects_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    encoder = _CountingEncoder()

    store = ChromaGenerationStore(tmp_path, config)
    v1_articles = [_make_article(10, "Artigo v1", "Conteúdo versão 1")]
    first = run_delta_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v1_articles, is_complete=True),
        prepare_fn=_fake_prepare,
        encode_fn=encoder,
    )
    manifest_path = first.manifest_path
    assert store.active_generation() == 1

    # Cenário A: falha/reinício ANTES de gravar o novo manifesto
    v2_articles = [_make_article(10, "Artigo v2", "Conteúdo versão 2")]

    def _crash_before_publish(*args, **kwargs):
        raise OSError("queda simulada antes da troca atômica do manifesto")

    with monkeypatch.context() as mp:
        mp.setattr("src.rag.sync.save_manifest_atomic", _crash_before_publish)
        with pytest.raises(OSError, match="troca atômica"):
            run_delta_sync(
                store=store,
                collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
                prepare_fn=_fake_prepare,
                encode_fn=encoder,
            )

    restarted_before = ChromaGenerationStore(tmp_path, config)
    active_after_crash_before = reconcile_store_with_manifest(restarted_before, manifest_path)
    assert active_after_crash_before == 1
    assert restarted_before.active_generation() == 1
    with restarted_before.capture_active() as reader:
        hits = reader.query(_deterministic_vector("Conteúdo versão 1"), limit=1)
    assert hits[0]["title"] == "Artigo v1"

    # Cenário B: reinício DEPOIS de gravar o manifesto mas ANTES de ativar no SQLite do store
    v2_chunks = _fake_prepare(v2_articles[0])
    candidate_v2 = restarted_before.create_candidate(v2_chunks, encode_missing=encoder)
    assert restarted_before.active_generation() == 1  # store ainda aponta para a 1

    manifest_v2 = {
        **load_manifest(manifest_path),
        "active_generation": candidate_v2,
        "last_checked_at": "2026-11-19T12:00:00+00:00",
        "last_published_at": "2026-11-19T12:00:00+00:00",
    }
    save_manifest_atomic(manifest_path, manifest_v2)

    restarted_after = ChromaGenerationStore(tmp_path, config)
    assert restarted_after.active_generation() == 1
    active_after_crash_after = reconcile_store_with_manifest(restarted_after, manifest_path)
    assert active_after_crash_after == candidate_v2
    assert restarted_after.active_generation() == candidate_v2
    with restarted_after.capture_active() as reader:
        hits = reader.query(_deterministic_vector("Conteúdo versão 2"), limit=1)
    assert hits[0]["title"] == "Artigo v2"