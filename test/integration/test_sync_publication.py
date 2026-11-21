"""Testes de integração da ING-04 com LocalIndexStore real, falhas injetadas e reinícios (Alternativa C)."""

from dataclasses import asdict, replace
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

from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.corpus import CorpusMetadata, PreparedCorpus
from src.rag.embeddings import DEFAULT_CONFIG, EmbeddingConfig, EmbeddingUnavailable
from src.rag.local_index import LocalIndexStore
from src.rag.manifest import load_manifest, save_manifest_atomic
from src.rag.sync import (
    CandidateValidationError,
    CollectionBatch,
    reconcile_store_with_manifest,
    run_sync,
    validate_candidate,
)


def _alt_embedding_config() -> EmbeddingConfig:
    """Produz uma EmbeddingConfig diferente da padrão (mantendo a dimensão) para testar IncompatibleConfig."""
    fields = asdict(DEFAULT_CONFIG)
    for key in ("revision", "model", "model_name"):
        if key in fields:
            current = fields[key]
            new_val = f"{current}-v2" if isinstance(current, str) and current else "rev-v2"
            return replace(DEFAULT_CONFIG, **{key: new_val})
    raise AssertionError("DEFAULT_CONFIG não possui campo esperado para alterar revisão/modelo.")


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


def _make_case(
    ticket_id: int,
    title: str,
    solution: str,
    *,
    eligible: bool = True,
) -> dict:
    return {
        "id": ticket_id,
        "title": title,
        "solution": solution,
        "source_reference": f"/Assistance/Ticket",
        "eligible": eligible,
    }


def _fake_prepare_article(article: dict) -> list[dict]:
    """Divide conteúdo por '||' em PreparedChunk válidos para source_type='article'."""
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


def _fake_prepare_case(case: dict) -> list[dict]:
    """Divide solução por '||' em PreparedChunk válidos para source_type='case'."""
    parts = [part.strip() for part in case["solution"].split("||") if part.strip()]
    return [
        {
            "source_type": "case",
            "source_id": case["id"],
            "source_reference": case["source_reference"],
            "title": case["title"],
            "chunk_id": f"{PREPARATION_VERSION}:case:{case['id']}:{idx:04d}",
            "content": part,
            "preparation_version": PREPARATION_VERSION,
        }
        for idx, part in enumerate(parts)
    ]


def _deterministic_vector(text: str, dimension: int = DEFAULT_CONFIG.dimension) -> np.ndarray:
    """Gera vetor float32 determinístico e normalizado (norma L2 = 1)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "little")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dimension).astype(np.float32)
    return vec / np.linalg.norm(vec)


def _best_hit(corpus: PreparedCorpus, query_text: str) -> dict:
    """Consulta cosseno direta na matriz NumPy normalizada da geração ativa."""
    q = _deterministic_vector(query_text, corpus.metadata.embedding.dimension)
    scores = corpus.vectors @ q
    return dict(corpus.chunks[int(np.argmax(scores))])


class _CountingEncoder:
    """Fake determinístico do MiniLM que contabiliza chamadas e permite injetar falhas."""

    def __init__(self, dimension: int = DEFAULT_CONFIG.dimension) -> None:
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
        "2026-11-21T10:00:00+00:00",
        "2026-11-21T10:05:00+00:00",
    ])
    monkeypatch.setattr("src.rag.sync._utc_now", lambda: next(timestamps))

    store = LocalIndexStore(tmp_path, "article")
    encoder = _CountingEncoder()
    articles = [
        _make_article(10, "VPN Corporativa", "Instale o cliente VPN||Informe suas credenciais"),
        _make_article(20, "Impressora", "Selecione a fila do andar"),
    ]

    first = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )

    assert first.status == "published"
    assert first.source_type == "article"
    assert first.vectors_computed == 3
    assert store.active_generation_id() == first.generation
    assert encoder.calls == 1

    # Segunda execução idêntica: zero embeddings e mesma geração ativa
    second = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )

    assert second.status == "no_changes"
    assert second.generation == first.generation
    assert second.vectors_computed == 0
    assert encoder.calls == 1
    assert store.active_generation_id() == first.generation

    manifest = load_manifest(first.manifest_path)
    assert manifest["active_generation"] == first.generation
    assert manifest["source_signature"] == first.source_signature
    assert manifest["last_published_at"] == "2026-11-21T10:00:00+00:00"
    assert manifest["last_checked_at"] == "2026-11-21T10:05:00+00:00"

    with store.open_active() as active:
        hit = _best_hit(active.corpus, "Selecione a fila do andar")
    assert hit["source_id"] == 20
    assert hit["title"] == "Impressora"


# ------------------------------------------------------------------ 2. Só metadados (sem reembutir)


def test_metadata_only_update_reuses_all_vectors_without_reembedding(tmp_path: Path) -> None:
    store = LocalIndexStore(tmp_path, "article")
    encoder = _CountingEncoder()

    initial_articles = [
        _make_article(10, "VPN Antigo", "Passo 1 VPN||Passo 2 VPN"),
        _make_article(20, "Email", "Configurar SMTP"),
    ]
    first = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=initial_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    assert first.vectors_computed == 3
    assert encoder.calls == 1

    renamed_articles = [
        _make_article(10, "VPN Corporativa Atualizada", "Passo 1 VPN||Passo 2 VPN"),
        _make_article(20, "Email", "Configurar SMTP"),
    ]
    second = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=renamed_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.generation != first.generation
    assert second.delta["metadata_modified"] == [10]
    assert second.delta["content_modified"] == []
    assert second.vectors_computed == 0
    assert encoder.calls == 1  # nenhum vetor recalculado

    with store.open_active() as active:
        hit = _best_hit(active.corpus, "Passo 1 VPN")
    assert hit["source_id"] == 10
    assert hit["title"] == "VPN Corporativa Atualizada"


# ------------------------------------------------------------------ 3. Edição de 5 para 3 chunks e remoção de inelegíveis


def test_edit_5_to_3_chunks_leaves_exactly_3_and_removes_ineligible(tmp_path: Path) -> None:
    store = LocalIndexStore(tmp_path, "article")
    encoder = _CountingEncoder()

    initial_articles = [
        _make_article(10, "Manual Rede", "T1||T2||T3||T4||T5"),
        _make_article(20, "Senha", "S1||S2"),
        _make_article(30, "Artigo Temporário", "Remover depois"),
    ]
    first = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=initial_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
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
    second = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=updated_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.delta["content_modified"] == [10]
    assert second.delta["same"] == [20]
    assert second.delta["deleted"] == [30]
    assert second.chunks_total == 5
    assert second.vectors_computed == 1  # apenas chunk 0002

    corpus = store.read_candidate(second.generation)
    art10_chunks = [c for c in corpus.chunks if c["source_id"] == 10]
    assert len(art10_chunks) == 3
    assert [c["content"] for c in art10_chunks] == ["T1", "T2", "T3-revisado"]
    assert all(c["source_id"] != 30 for c in corpus.chunks)

    manifest = load_manifest(second.manifest_path)
    assert 30 not in manifest["sources"]
    assert len(manifest["sources"][10]["chunk_ids"]) == 3


# ------------------------------------------------------------------ 4. Troca de configuração MiniLM e separação article/case


def test_embedding_config_change_forces_full_reembed(tmp_path: Path) -> None:
    articles = [
        _make_article(10, "VPN", "Bloco 1||Bloco 2"),
        _make_article(20, "Wi-Fi", "Bloco 3"),
    ]
    encoder = _CountingEncoder()

    store_v1 = LocalIndexStore(tmp_path, "article", embedding=DEFAULT_CONFIG)
    first = run_sync(
        store=store_v1,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    assert first.vectors_computed == 3

    alt_config = _alt_embedding_config()
    store_v2 = LocalIndexStore(tmp_path, "article", embedding=alt_config)
    second = run_sync(
        store=store_v2,
        collect_fn=lambda: CollectionBatch(articles=articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )

    assert second.status == "published"
    assert second.generation != first.generation
    assert second.delta["content_modified"] == [10, 20]
    assert second.vectors_computed == 3
    assert store_v2.active_generation_id() == second.generation

    manifest = load_manifest(second.manifest_path)
    assert manifest["embedding_config"] == asdict(alt_config)


def test_article_and_case_stores_remain_isolated_under_same_root(tmp_path: Path) -> None:
    encoder = _CountingEncoder()
    article_store = LocalIndexStore(tmp_path, "article")
    case_store = LocalIndexStore(tmp_path, "case")

    art_report = run_sync(
        store=article_store,
        collect_fn=lambda: CollectionBatch(
            articles=[_make_article(1, "Guia Rede", "Reiniciar roteador")],
            is_complete=True,
        ),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    case_report = run_sync(
        store=case_store,
        collect_fn=lambda: CollectionBatch(
            articles=[
                _make_case(501, "Erro Outlook", "Limpar cache OST"),
                _make_case(502, "Ticket sem solução", "   "),
            ],
            is_complete=True,
        ),
        prepare_fn=_fake_prepare_case,
        encode_fn=encoder,
    )

    assert art_report.source_type == "article"
    assert case_report.source_type == "case"
    assert case_report.chunks_total == 1

    with article_store.open_active() as active_art, case_store.open_active() as active_case:
        assert active_art.info.source_type == "article"
        assert active_case.info.source_type == "case"
        assert active_case.corpus.chunks[0]["source_id"] == 501


# ------------------------------------------------------------------ 5. Injeção de falhas em cada etapa


def test_failures_in_collect_encode_write_and_validate_preserve_active_and_allow_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": "2026-11-21T11:00:00+00:00"}
    monkeypatch.setattr("src.rag.sync._utc_now", lambda: clock["now"])

    store = LocalIndexStore(tmp_path, "article")
    encoder = _CountingEncoder()

    v1_articles = [_make_article(10, "Guia Base", "Texto original")]
    first = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v1_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    manifest_before = load_manifest(first.manifest_path)

    clock["now"] = "2026-11-21T11:10:00+00:00"
    v2_articles = [
        _make_article(10, "Guia Base", "Texto atualizado"),
        _make_article(20, "Novo Artigo", "Conteúdo novo"),
    ]

    # (a) Falha na coleta
    with pytest.raises(ConnectionError, match="coleta GLPI"):
        run_sync(
            store=store,
            collect_fn=lambda: (_ for _ in ()).throw(ConnectionError("falha de rede na coleta GLPI")),
            prepare_fn=_fake_prepare_article,
            encode_fn=encoder,
        )
    assert store.active_generation_id() == first.generation
    assert load_manifest(first.manifest_path) == manifest_before

    # (b) Falha no encoder MiniLM
    encoder.fail_with = EmbeddingUnavailable("falha simulada no encoder MiniLM")
    with pytest.raises(EmbeddingUnavailable, match="encoder MiniLM"):
        run_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
            prepare_fn=_fake_prepare_article,
            encode_fn=encoder,
        )
    encoder.fail_with = None
    assert store.active_generation_id() == first.generation
    assert load_manifest(first.manifest_path) == manifest_before

    # (c) Falha na gravação da geração no LocalIndexStore
    def _broken_create_candidate(*args, **kwargs):
        raise OSError("disco cheio ao gravar candidata local")

    with monkeypatch.context() as mp:
        mp.setattr(store, "create_candidate", _broken_create_candidate)
        with pytest.raises(OSError, match="disco cheio"):
            run_sync(
                store=store,
                collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
                prepare_fn=_fake_prepare_article,
                encode_fn=encoder,
            )
    assert store.active_generation_id() == first.generation
    assert load_manifest(first.manifest_path) == manifest_before

    # (d) Falha na validação da candidata
    def _broken_validator(*args, **kwargs):
        raise CandidateValidationError("candidata reprovada na consulta cosseno")

    with pytest.raises(CandidateValidationError, match="reprovada"):
        run_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
            prepare_fn=_fake_prepare_article,
            encode_fn=encoder,
            validator_fn=_broken_validator,
        )
    assert store.active_generation_id() == first.generation
    assert load_manifest(first.manifest_path) == manifest_before

    # Validação real reprova quando a lista esperada diverge
    with pytest.raises(CandidateValidationError):
        validate_candidate(store, first.generation, [])

    # (e) Repetição posterior conclui normalmente
    clock["now"] = "2026-11-21T11:20:00+00:00"
    retry = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    assert retry.status == "published"
    assert retry.generation != first.generation
    assert store.active_generation_id() == retry.generation
    assert load_manifest(retry.manifest_path)["last_published_at"] == "2026-11-21T11:20:00+00:00"


# ------------------------------------------------------------------ 6. Leitura concorrente (open_active) e reinícios


def test_open_active_lease_survives_publication_and_cleanup(tmp_path: Path) -> None:
    store = LocalIndexStore(tmp_path, "article")
    encoder = _CountingEncoder()

    r1 = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=[_make_article(10, "Artigo v1", "Texto v1")], is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
        cleanup_previous=0,
    )

    with store.open_active() as pinned_v1:
        r2 = run_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=[_make_article(10, "Artigo v2", "Texto v2")], is_complete=True),
            prepare_fn=_fake_prepare_article,
            encode_fn=encoder,
            cleanup_previous=0,
        )
        assert store.active_generation_id() == r2.generation
        assert pinned_v1.generation_id == r1.generation
        assert (store.directory / f"gen-{r1.generation}").is_dir()

    # Após liberar o leitor, a limpeza pode remover a geração antiga
    removed = store.cleanup(keep_previous=0)
    assert r1.generation in removed
    assert not (store.directory / f"gen-{r1.generation}").exists()


def test_restart_before_and_after_publication_respects_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoder = _CountingEncoder()
    store = LocalIndexStore(tmp_path, "article")

    v1_articles = [_make_article(10, "Artigo v1", "Conteúdo versão 1")]
    first = run_sync(
        store=store,
        collect_fn=lambda: CollectionBatch(articles=v1_articles, is_complete=True),
        prepare_fn=_fake_prepare_article,
        encode_fn=encoder,
    )
    manifest_path = first.manifest_path

    # Cenário A: queda ANTES de gravar o novo manifesto
    v2_articles = [_make_article(10, "Artigo v2", "Conteúdo versão 2")]

    def _crash_before_publish(*args, **kwargs):
        raise OSError("queda simulada antes da troca atômica do manifesto")

    with monkeypatch.context() as mp:
        mp.setattr("src.rag.sync.save_manifest_atomic", _crash_before_publish)
        with pytest.raises(OSError, match="troca atômica"):
            run_sync(
                store=store,
                collect_fn=lambda: CollectionBatch(articles=v2_articles, is_complete=True),
                prepare_fn=_fake_prepare_article,
                encode_fn=encoder,
            )

    restarted_before = LocalIndexStore(tmp_path, "article")
    assert reconcile_store_with_manifest(restarted_before, manifest_path) == first.generation
    assert restarted_before.active_generation_id() == first.generation
    with restarted_before.open_active() as active:
        assert _best_hit(active.corpus, "Conteúdo versão 1")["title"] == "Artigo v1"

    # Cenário B: queda DEPOIS de gravar o manifesto mas ANTES de atualizar o ponteiro ACTIVE
    v2_chunks = _fake_prepare_article(v2_articles[0])
    v2_vectors = encoder(v2_chunks)
    v2_corpus = PreparedCorpus(
        tuple(v2_chunks),
        v2_vectors,
        CorpusMetadata(DEFAULT_CONFIG, PREPARATION_VERSION, tuple(c["chunk_id"] for c in v2_chunks)),
    )
    candidate_v2 = restarted_before.create_candidate(v2_corpus, source_signature="sig-v2").generation_id
    assert restarted_before.active_generation_id() == first.generation

    manifest_v2 = {
        **load_manifest(manifest_path),
        "active_generation": candidate_v2,
        "source_signature": "sig-v2",
        "last_checked_at": "2026-11-21T12:00:00+00:00",
        "last_published_at": "2026-11-21T12:00:00+00:00",
    }
    save_manifest_atomic(manifest_path, manifest_v2)

    restarted_after = LocalIndexStore(tmp_path, "article")
    assert restarted_after.active_generation_id() == first.generation
    assert reconcile_store_with_manifest(restarted_after, manifest_path) == candidate_v2
    assert restarted_after.active_generation_id() == candidate_v2
    with restarted_after.open_active() as active:
        assert _best_hit(active.corpus, "Conteúdo versão 2")["title"] == "Artigo v2"