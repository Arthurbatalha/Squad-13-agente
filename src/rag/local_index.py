"""ING-03: índice local persistente por gerações (matriz .npy + catálogo JSON).

Substitui o Chroma do planejamento antigo. Um `LocalIndexStore` guarda um tipo
de fonte (`article` ou `case`) em `<root>/<source_type>/`:

    ACTIVE                     ponteiro (texto) para a geração ativa
    gen-<id>/vectors.npy       matriz float32 (n, dimensão), norma L2 = 1
    gen-<id>/catalog.json      registros de fonte + trechos (sem vetores)
    gen-<id>/manifest.json     informações da geração: configuração, hashes, data

O armazenamento só guarda e devolve `PreparedCorpus` (ING-02). Ele não gera
embeddings, não coleta do GLPI, não decide autorização nem sincroniza sozinho:
quem decide quando criar e ativar uma candidata é a ING-04/05.

Garantias:
- gravação em diretório temporário + rename; a geração ativa nunca é alterada;
- troca do ponteiro por `os.replace` (atômica no mesmo volume);
- leitura "capturada" (`open_active`) fixa uma geração até `close()`; a limpeza
  não remove gerações ativas, a anterior, candidatas pendentes nem capturadas;
- qualquer incompatibilidade (modelo, revisão, dimensão, versão da preparação,
  hash, IDs) levanta erro; nada é corrigido ou aceito parcialmente.

Limite conhecido: as capturas são contadas dentro do processo. Este contrato
assume um único processo escritor (como a ING-04), sem coordenação entre processos.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from threading import RLock
import time
import uuid

import numpy as np

from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.corpus import CorpusMetadata, CorpusUnavailable, PreparedCorpus
from src.rag.embeddings import (
    DEFAULT_CONFIG, EmbeddingConfig, IncompatibleConfig, validate_chunks, validate_vectors,
)

FORMAT_VERSION = "ing-03-v1"
_GENERATION_ID = re.compile(r"\d{20}-[0-9a-f]{6}")
_SOURCE_TYPES = ("article", "case")


class IndexCorrupt(RuntimeError):
    """Arquivos ausentes, alterados ou inconsistentes; nunca é lido parcialmente."""


@dataclass(frozen=True)
class GenerationInfo:
    generation_id: str
    created_at: str
    source_type: str
    chunk_count: int
    source_count: int
    source_signature: str | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(text: str) -> str:
    return _sha256(text.encode("utf-8"))


def _write_file(path: Path, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:  # Windows não abre diretórios; o rename continua atômico.
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def _matrix_bytes(vectors: np.ndarray) -> bytes:
    import io
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(vectors, dtype=np.float32), allow_pickle=False)
    return buffer.getvalue()


class ActiveGeneration:
    """Leitura capturada: o corpus é imutável e a geração fica protegida da limpeza."""

    def __init__(self, store: "LocalIndexStore", info: GenerationInfo, corpus: PreparedCorpus):
        self._store = store
        self._info = info
        self._corpus = corpus
        self._closed = False

    @property
    def generation_id(self) -> str:
        return self._info.generation_id

    @property
    def info(self) -> GenerationInfo:
        return self._info

    @property
    def corpus(self) -> PreparedCorpus:
        return self._corpus

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._store._release(self._info.generation_id)

    def __enter__(self) -> "ActiveGeneration":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class LocalIndexStore:
    def __init__(self, root: str | os.PathLike, source_type: str,
                 *, embedding: EmbeddingConfig = DEFAULT_CONFIG):
        if source_type not in _SOURCE_TYPES:
            raise ValueError("source_type deve ser article ou case.")
        if not isinstance(embedding, EmbeddingConfig):
            raise TypeError("embedding deve ser EmbeddingConfig.")
        self.source_type = source_type
        self.embedding = embedding
        self.directory = Path(root) / source_type
        self._lock = RLock()
        self._leases: dict[str, int] = {}

    # ---------------------------------------------------------------- caminhos
    def _generation_dir(self, generation_id: str) -> Path:
        if not isinstance(generation_id, str) or not _GENERATION_ID.fullmatch(generation_id):
            raise ValueError("generation_id inválido.")
        return self.directory / f"gen-{generation_id}"

    @property
    def _pointer(self) -> Path:
        return self.directory / "ACTIVE"

    def _generation_ids(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        found = []
        for entry in self.directory.iterdir():
            name = entry.name
            if entry.is_dir() and name.startswith("gen-") and _GENERATION_ID.fullmatch(name[4:]):
                found.append(name[4:])
        return sorted(found)

    def _new_generation_id(self) -> str:
        # 20 dígitos de ns: ordem lexicográfica = ordem de criação, mesmo após reinício.
        newest = max(self._generation_ids(), default="")
        stamp = max(time.time_ns(), int(newest[:20]) + 1 if newest else 0)
        return f"{stamp:020d}-{uuid.uuid4().hex[:6]}"

    # ----------------------------------------------------------------- escrita
    def create_candidate(self, corpus: PreparedCorpus, *, source_signature: str | None = None) -> GenerationInfo:
        """Grava uma geração completa e a relê para validar. Não ativa nem altera a ativa."""
        if not isinstance(corpus, PreparedCorpus):
            raise TypeError("corpus deve ser PreparedCorpus.")
        if corpus.metadata.embedding != self.embedding:
            raise IncompatibleConfig("Configuração de embeddings do corpus difere da configuração do índice.")
        if corpus.metadata.preparation_version != PREPARATION_VERSION:
            raise IncompatibleConfig("Versão da preparação do corpus incompatível.")
        wrong = {chunk["source_type"] for chunk in corpus.chunks} - {self.source_type}
        if wrong:
            raise ValueError(f"Este índice guarda somente {self.source_type}; recebeu {sorted(wrong)}.")
        if source_signature is not None and not isinstance(source_signature, str):
            raise TypeError("source_signature deve ser string ou None.")

        catalog = self._build_catalog(corpus)
        vectors_data = _matrix_bytes(corpus.vectors)
        catalog_data = _json_bytes(catalog)

        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            generation_id = self._new_generation_id()
            temporary = self.directory / f".tmp-{generation_id}"
            final = self._generation_dir(generation_id)
            try:
                temporary.mkdir()
                manifest = {
                    "format_version": FORMAT_VERSION,
                    "generation_id": generation_id,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source_type": self.source_type,
                    "embedding": asdict(self.embedding),
                    "preparation_version": PREPARATION_VERSION,
                    "chunk_count": len(corpus.chunks),
                    "source_count": len(catalog["sources"]),
                    "vectors_shape": list(corpus.vectors.shape),
                    "vectors_sha256": _sha256(vectors_data),
                    "catalog_sha256": _sha256(catalog_data),
                    "source_signature": source_signature,
                }
                _write_file(temporary / "vectors.npy", vectors_data)
                _write_file(temporary / "catalog.json", catalog_data)
                _write_file(temporary / "manifest.json", _json_bytes(manifest))
                _fsync_dir(temporary)
                os.replace(temporary, final)
                _fsync_dir(self.directory)
                # A candidata só existe para leitores se reler íntegra.
                self._load(generation_id)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                shutil.rmtree(final, ignore_errors=True)
                raise
            return self._info_from_manifest(manifest)

    def _build_catalog(self, corpus: PreparedCorpus) -> dict:
        sources: dict[int, dict] = {}
        chunks = []
        for chunk in corpus.chunks:
            record = sources.setdefault(chunk["source_id"], {
                "source_id": chunk["source_id"], "source_reference": chunk["source_reference"],
                "title": chunk["title"], "chunk_ids": [],
            })
            record["chunk_ids"].append(chunk["chunk_id"])
            chunks.append({"chunk_id": chunk["chunk_id"], "source_id": chunk["source_id"],
                           "content": chunk["content"], "content_hash": content_hash(chunk["content"])})
        return {"sources": list(sources.values()), "chunks": chunks}

    def activate(self, generation_id: str) -> None:
        """Troca o ponteiro após reler e validar a geração. Chamada pela ING-04."""
        with self._lock:
            self._load(generation_id)  # nunca aponta para algo ilegível/incompatível
            temporary = self.directory / f"ACTIVE.tmp-{uuid.uuid4().hex[:6]}"
            try:
                _write_file(temporary, generation_id.encode("ascii"))
                os.replace(temporary, self._pointer)
                _fsync_dir(self.directory)
            finally:
                temporary.unlink(missing_ok=True)

    # ----------------------------------------------------------------- leitura
    def active_generation_id(self) -> str | None:
        try:
            value = self._pointer.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise IndexCorrupt("Ponteiro ACTIVE ilegível.") from exc
        if not _GENERATION_ID.fullmatch(value) or not self._generation_dir(value).is_dir():
            raise IndexCorrupt("Ponteiro ACTIVE aponta para geração inexistente ou inválida.")
        return value

    def read_candidate(self, generation_id: str) -> PreparedCorpus:
        """Leitura completa e verificada de qualquer geração (candidata ou ativa)."""
        with self._lock:
            return self._load(generation_id)[1]

    def generation_info(self, generation_id: str) -> GenerationInfo:
        with self._lock:
            return self._load(generation_id)[0]

    def open_active(self) -> ActiveGeneration:
        """Captura a geração ativa atual; a leitura termina nela mesmo se a ativa mudar."""
        with self._lock:
            generation_id = self.active_generation_id()
            if generation_id is None:
                raise CorpusUnavailable("Índice indisponível: nenhuma geração ativa publicada.")
            info, corpus = self._load(generation_id)
            self._leases[generation_id] = self._leases.get(generation_id, 0) + 1
            return ActiveGeneration(self, info, corpus)

    def _release(self, generation_id: str) -> None:
        with self._lock:
            remaining = self._leases.get(generation_id, 0) - 1
            if remaining > 0:
                self._leases[generation_id] = remaining
            else:
                self._leases.pop(generation_id, None)

    def reusable_vectors(self, chunks, generation_id: str | None = None) -> dict[str, np.ndarray]:
        """Vetores da geração (padrão: ativa) válidos para os trechos dados.

        Reaproveita um vetor só se `chunk_id` e conteúdo coincidem com os da geração
        e a configuração do índice é a mesma. Quem reconstrói (ING-04) codifica o resto.
        """
        checked = validate_chunks(chunks)
        with self._lock:
            generation_id = generation_id or self.active_generation_id()
            if generation_id is None:
                return {}
            corpus = self._load(generation_id)[1]
        previous = {chunk["chunk_id"]: (chunk["content"], vector)
                    for chunk, vector in zip(corpus.chunks, corpus.vectors, strict=True)}
        reused = {}
        for chunk in checked:
            old = previous.get(chunk["chunk_id"])
            if old is not None and old[0] == chunk["content"]:
                reused[chunk["chunk_id"]] = np.array(old[1], dtype=np.float32, copy=True)
        return reused

    def _info_from_manifest(self, manifest: dict) -> GenerationInfo:
        return GenerationInfo(
            generation_id=manifest["generation_id"], created_at=manifest["created_at"],
            source_type=manifest["source_type"], chunk_count=manifest["chunk_count"],
            source_count=manifest["source_count"], source_signature=manifest["source_signature"])

    def _load(self, generation_id: str) -> tuple[GenerationInfo, PreparedCorpus]:
        directory = self._generation_dir(generation_id)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            vectors_data = (directory / "vectors.npy").read_bytes()
            catalog_data = (directory / "catalog.json").read_bytes()
        except FileNotFoundError as exc:
            raise IndexCorrupt(f"Geração {generation_id} incompleta ou inexistente.") from exc
        except (OSError, ValueError) as exc:
            raise IndexCorrupt(f"Geração {generation_id} ilegível.") from exc

        required = {"format_version", "generation_id", "created_at", "source_type", "embedding",
                    "preparation_version", "chunk_count", "source_count", "vectors_shape",
                    "vectors_sha256", "catalog_sha256", "source_signature"}
        if not isinstance(manifest, dict) or not required <= manifest.keys():
            raise IndexCorrupt("Manifesto incompleto.")
        if manifest["format_version"] != FORMAT_VERSION:
            raise IncompatibleConfig("Formato do índice incompatível; reconstrua a geração.")
        if manifest["generation_id"] != generation_id or manifest["source_type"] != self.source_type:
            raise IndexCorrupt("Manifesto não corresponde à geração/tipo solicitado.")
        try:
            stored_config = EmbeddingConfig(**manifest["embedding"])
        except (TypeError, ValueError) as exc:
            raise IncompatibleConfig("Configuração de embeddings do manifesto inválida.") from exc
        if stored_config != self.embedding:
            raise IncompatibleConfig("Modelo, revisão ou configuração de embeddings incompatíveis com o índice.")
        if manifest["preparation_version"] != PREPARATION_VERSION:
            raise IncompatibleConfig("Versão da preparação incompatível; reconstrua a geração.")
        if _sha256(vectors_data) != manifest["vectors_sha256"] or _sha256(catalog_data) != manifest["catalog_sha256"]:
            raise IndexCorrupt("Hash dos arquivos não confere com o manifesto.")

        try:
            import io
            matrix = np.load(io.BytesIO(vectors_data), allow_pickle=False)
            catalog = json.loads(catalog_data.decode("utf-8"))
            chunks = self._chunks_from_catalog(catalog, manifest)
            vectors = validate_vectors(matrix, manifest["chunk_count"], self.embedding.dimension)
            if list(matrix.shape) != manifest["vectors_shape"] or matrix.dtype != np.float32:
                raise ValueError("Forma ou dtype dos vetores difere do manifesto.")
            corpus = PreparedCorpus(
                tuple(chunks), vectors,
                CorpusMetadata(self.embedding, PREPARATION_VERSION, tuple(c["chunk_id"] for c in chunks)))
        except IncompatibleConfig:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise IndexCorrupt(f"Conteúdo da geração {generation_id} inconsistente: {exc}") from exc
        return self._info_from_manifest(manifest), corpus

    def _chunks_from_catalog(self, catalog, manifest) -> list[dict]:
        if not isinstance(catalog, dict) or set(catalog) != {"sources", "chunks"}:
            raise ValueError("Catálogo com estrutura inesperada.")
        sources = {}
        for record in catalog["sources"]:
            if record["source_id"] in sources:
                raise ValueError("Fonte duplicada no catálogo.")
            sources[record["source_id"]] = record
        if len(sources) != manifest["source_count"] or len(catalog["chunks"]) != manifest["chunk_count"]:
            raise ValueError("Contagens do catálogo divergem do manifesto.")
        chunks, seen = [], {source_id: [] for source_id in sources}
        for entry in catalog["chunks"]:
            source = sources[entry["source_id"]]  # KeyError => fonte inexistente
            if content_hash(entry["content"]) != entry["content_hash"]:
                raise ValueError("content_hash não confere com o texto do trecho.")
            seen[entry["source_id"]].append(entry["chunk_id"])
            chunks.append({
                "source_type": self.source_type, "source_id": entry["source_id"],
                "source_reference": source["source_reference"], "title": source["title"],
                "chunk_id": entry["chunk_id"], "content": entry["content"],
                "preparation_version": PREPARATION_VERSION,
            })
        if any(seen[source_id] != record["chunk_ids"] for source_id, record in sources.items()):
            raise ValueError("Lista de trechos por fonte diverge do catálogo de trechos.")
        return chunks

    # ----------------------------------------------------------------- limpeza
    def cleanup(self, *, keep_previous: int = 1) -> list[str]:
        """Remove gerações antigas que ninguém lê. Nunca toca na ativa.

        Preservados: a ativa, as `keep_previous` mais recentes anteriores a ela,
        candidatas mais novas que a ativa (ainda não publicadas) e gerações
        capturadas por leitores deste processo. Sem ativa, nada é removido.
        """
        if type(keep_previous) is not int or keep_previous < 0:
            raise ValueError("keep_previous deve ser inteiro não negativo.")
        with self._lock:
            active = self.active_generation_id()
            if active is None:
                return []
            older = [gid for gid in self._generation_ids() if gid < active]
            protected = set(older[len(older) - keep_previous:] if keep_previous else [])
            removed = []
            for generation_id in older:
                if generation_id in protected or self._leases.get(generation_id):
                    continue
                trash = self.directory / f".trash-{generation_id}"
                os.replace(self._generation_dir(generation_id), trash)  # some da lista antes do rmtree
                shutil.rmtree(trash, ignore_errors=True)
                removed.append(generation_id)
            for leftover in self.directory.glob(".tmp-*"):  # restos de gravações interrompidas
                shutil.rmtree(leftover, ignore_errors=True)
            return removed
