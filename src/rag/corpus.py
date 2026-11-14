"""Corpus MiniLM reutilizável em memória. Persistência pertence à ING-03."""

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
from threading import Lock, RLock
from types import MappingProxyType

import numpy as np

from src.rag.chunk_contract import PREPARATION_VERSION, PreparedChunk
from src.rag.embeddings import (
    EmbeddingConfig, EmbeddingService, IncompatibleConfig, validate_chunks, validate_vectors,
)


class CorpusUnavailable(RuntimeError):
    """Ainda não existe um corpus válido; diferente de corpus válido vazio."""


@dataclass(frozen=True)
class CorpusMetadata:
    embedding: EmbeddingConfig
    preparation_version: str
    chunk_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.embedding, EmbeddingConfig):
            raise TypeError("embedding deve ser EmbeddingConfig.")
        if not isinstance(self.chunk_ids, tuple) or not all(isinstance(item, str) for item in self.chunk_ids):
            raise TypeError("chunk_ids deve ser uma tupla ordenada de strings.")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PreparedCorpus:
    chunks: tuple[Mapping, ...]
    vectors: np.ndarray
    metadata: CorpusMetadata

    def __post_init__(self):
        checked = validate_chunks(self.chunks)
        if tuple(chunk["chunk_id"] for chunk in checked) != self.metadata.chunk_ids:
            raise ValueError("A ordem de chunk_id não corresponde à ordem dos vetores/metadados.")
        if self.metadata.preparation_version != PREPARATION_VERSION:
            raise IncompatibleConfig("Versão da preparação do corpus incompatível.")
        values = validate_vectors(self.vectors, len(checked), self.metadata.embedding.dimension)
        # Bytes imutáveis impedem alterações acidentais ou setflags(write=True).
        frozen_vectors = np.frombuffer(values.tobytes(), dtype=np.float32).reshape(values.shape)
        object.__setattr__(self, "vectors", frozen_vectors)
        object.__setattr__(self, "chunks", tuple(MappingProxyType(chunk) for chunk in checked))


def validate_query(question, limit) -> bool:
    if type(limit) is not int:
        raise TypeError("limit deve ser inteiro.")
    if question is not None and not isinstance(question, str):
        raise TypeError("A pergunta deve ser string.")
    return limit > 0 and bool(question and question.strip())


class CorpusService:
    """Publica uma nova referência só depois de preparar e validar todo o corpus."""

    def __init__(self, encoder: EmbeddingService | None = None, *, min_similarity: float = 0.45):
        if isinstance(min_similarity, bool) or not isinstance(min_similarity, (int, float)) or not -1 <= min_similarity <= 1:
            raise ValueError("min_similarity deve estar entre -1 e 1.")
        self.encoder = encoder if encoder is not None else EmbeddingService()
        self.min_similarity = float(min_similarity)  # Provisório; ranking/recusa ainda não avaliados.
        self._corpus = None
        self._signature = None
        self._prepare_lock = RLock()
        self._state_lock = Lock()

    @property
    def corpus(self) -> PreparedCorpus:
        with self._state_lock:
            if self._corpus is None:
                raise CorpusUnavailable("Corpus indisponível: prepare fontes ou trechos antes de consultar.")
            return self._corpus

    def _build(self, chunks) -> PreparedCorpus:
        checked = validate_chunks(chunks)
        vectors = self.encoder.encode_chunks(checked)
        metadata = CorpusMetadata(self.encoder.config, PREPARATION_VERSION,
                                  tuple(chunk["chunk_id"] for chunk in checked))
        return PreparedCorpus(tuple(checked), vectors, metadata)

    def _publish(self, candidate, signature=None):
        with self._state_lock:
            self._corpus, self._signature = candidate, signature
        return candidate

    def prepare_chunks(self, chunks: Iterable[PreparedChunk]) -> PreparedCorpus:
        with self._prepare_lock:
            return self._publish(self._build(chunks))

    def prepare_sources(self, sources: Iterable[tuple[str, Mapping]]) -> PreparedCorpus:
        """Recebe pares (source_type, fonte normalizada da ING-01)."""
        with self._prepare_lock:
            chunks, seen = [], set()
            for source_type, source in sources:
                if not isinstance(source, Mapping):
                    raise TypeError("Cada fonte deve ser um mapeamento.")
                identity = source_type, source.get("id")
                if identity in seen:
                    raise ValueError("Fonte duplicada; envie cada fonte uma vez.")
                seen.add(identity)
                chunks.extend(self.encoder.prepare_source(source, source_type=source_type))
            return self._publish(self._build(chunks))

    def prepare_articles(self, articles) -> PreparedCorpus:
        """Compatibilidade da busca: title canônico, name somente quando title ausente.

        A assinatura detecta mudanças no material recebido, não mudanças remotas
        no GLPI. Mantém somente o último corpus nesta instância, sem persistência.
        """
        if isinstance(articles, (str, bytes, Mapping)):
            raise TypeError("articles deve ser uma coleção de artigos.")
        sources = []
        for article in (() if articles is None else articles):
            if not isinstance(article, Mapping):
                raise TypeError("Cada artigo deve ser um mapeamento.")
            sources.append({
                "id": article.get("id"),
                "title": article["title"] if "title" in article else article.get("name"),
                "content": article.get("content"),
                "source_reference": article.get("source_reference", "/Knowledgebase/Article"),
            })
        signature = hashlib.sha256(json.dumps({
            "sources": sources, "embedding": asdict(self.encoder.config), "preparation_version": PREPARATION_VERSION,
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._prepare_lock:
            with self._state_lock:
                if self._corpus is not None and self._signature == signature:
                    return self._corpus
            chunks, seen = [], set()
            for source in sources:
                if source["id"] in seen:
                    raise ValueError("ID de artigo duplicado.")
                seen.add(source["id"])
                chunks.extend(self.encoder.prepare_source(source, source_type="article"))
            return self._publish(self._build(chunks), signature)

    def search(self, question: str, *, corpus: PreparedCorpus | None = None, limit: int = 3) -> list[dict]:
        if not validate_query(question, limit):
            return []
        snapshot = self.corpus if corpus is None else corpus
        if not isinstance(snapshot, PreparedCorpus):
            raise TypeError("corpus deve ser PreparedCorpus.")
        if snapshot.metadata.embedding != self.encoder.config:
            raise IncompatibleConfig("Configuração de embeddings incompatível, mesmo que a dimensão coincida.")
        if snapshot.metadata.preparation_version != PREPARATION_VERSION:
            raise IncompatibleConfig("Configuração de preparação incompatível.")
        if not snapshot.chunks:
            return []
        scores = snapshot.vectors @ self.encoder.encode_question(question)
        grouped = {}
        for chunk, score in zip(snapshot.chunks, scores, strict=True):
            key = chunk["source_type"], chunk["source_id"]
            if key not in grouped:
                grouped[key] = {"chunks": [], "best": chunk, "score": float(score)}
            item = grouped[key]
            item["chunks"].append(chunk["content"])
            if float(score) > item["score"]:
                item.update(score=float(score), best=chunk)
        results = []
        for item in grouped.values():
            if item["score"] >= self.min_similarity:
                chunk = item["best"]
                results.append({
                    "id": chunk["source_id"], "title": chunk["title"],
                    "content": "".join(item["chunks"]), "score": item["score"],
                    "source_type": chunk["source_type"], "source_reference": chunk["source_reference"],
                    "chunk_id": chunk["chunk_id"],
                })
        results.sort(key=lambda result: result["score"], reverse=True)
        return results[:limit]


_default_service = None
_default_lock = Lock()


def get_search_service() -> CorpusService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = CorpusService()
        return _default_service
