"""ING-02: adaptador MiniLM lazy, CPU, sem I/O na importação."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import numpy as np

from src.rag.chunk_contract import (
    MINILM_MAX_TOKENS, MINILM_MODEL, MINILM_REVISION, PREPARATION_VERSION,
    PreparationSource, PreparedChunk, SourceType,
)
from src.rag.preparation import prepare_source


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = MINILM_MODEL
    revision: str = MINILM_REVISION
    dimension: int = 384
    normalize: bool = True
    max_tokens: int = MINILM_MAX_TOKENS
    input_format: str = "plain-text"
    precision: str = "float32"
    device: str = "cpu"

    def __post_init__(self):
        if type(self.dimension) is not int or type(self.max_tokens) is not int or type(self.normalize) is not bool:
            raise ValueError("Dimensão/limite devem ser inteiros e normalize deve ser booleano.")
        for value in (self.model, self.revision, self.input_format, self.precision, self.device):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Modelo, revisão e configuração devem ser strings não vazias.")


DEFAULT_CONFIG = EmbeddingConfig()


class IncompatibleConfig(ValueError):
    """O corpus/modelo não corresponde à configuração adotada pela ING-02."""


class TokenLimitError(ValueError):
    """Texto excede o orçamento; o encoder não é chamado com esse texto."""


class EmbeddingUnavailable(RuntimeError):
    """Falha ao carregar o modelo ou executar a inferência."""


def validate_vectors(values, count: int, dimension: int = 384) -> np.ndarray:
    """Valida, sem corrigir vetores inválidos silenciosamente."""
    array = np.asarray(values)
    if array.shape != (count, dimension):
        raise ValueError(f"Embeddings: esperado formato ({count}, {dimension}); recebido {array.shape}.")
    if array.dtype.kind not in "fi" or not np.isfinite(array).all():
        raise ValueError("Embeddings devem conter somente números finitos.")
    if count and not np.allclose(np.linalg.norm(array, axis=1), 1.0, atol=1e-5, rtol=1e-4):
        raise ValueError("Embeddings devem ter norma L2 igual a 1; vetor zero não é válido.")
    return np.array(array, dtype=np.float32, copy=True)


def validate_chunks(chunks: Iterable[PreparedChunk]) -> list[PreparedChunk]:
    if isinstance(chunks, (str, bytes, Mapping)) or chunks is None:
        raise TypeError("chunks deve ser uma coleção de PreparedChunk.")
    result, ids, sources = [], set(), {}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            raise TypeError("Cada trecho deve ser um mapeamento PreparedChunk.")
        required = PreparedChunk.__required_keys__
        if not required <= chunk.keys():
            raise ValueError("Trecho sem os campos obrigatórios da ING-01.")
        copied = {key: chunk[key] for key in required}
        if type(copied["source_id"]) is not int or copied["source_id"] < 0:
            raise ValueError("source_id deve ser inteiro não negativo, sem booleanos.")
        for key in required - {"source_id"}:
            if not isinstance(copied[key], str) or not copied[key].strip():
                raise ValueError(f"Campo do trecho deve ser texto não vazio: {key}.")
        expected_ref = {"article": "/Knowledgebase/Article", "case": "/Assistance/Ticket"}.get(copied["source_type"])
        if expected_ref is None or copied["source_reference"] != expected_ref:
            raise ValueError("Tipo e referência de fonte incompatíveis.")
        if copied["preparation_version"] != PREPARATION_VERSION:
            raise IncompatibleConfig("Versão da preparação incompatível; reprepare a fonte com ING-01.")
        prefix = f"{PREPARATION_VERSION}:{copied['source_type']}:{copied['source_id']}:"
        if not copied["chunk_id"].startswith(prefix) or not copied["chunk_id"][len(prefix):].isdecimal():
            raise ValueError("chunk_id não corresponde à versão, ao tipo e ao ID da fonte.")
        if copied["chunk_id"] in ids:
            raise ValueError("chunk_id duplicado no corpus.")
        ids.add(copied["chunk_id"])
        identity = copied["source_type"], copied["source_id"]
        metadata = copied["source_reference"], copied["title"]
        if identity in sources and sources[identity] != metadata:
            raise ValueError("Metadados divergentes para a mesma fonte.")
        sources[identity] = metadata
        result.append(copied)
    return result


class EmbeddingService:
    """Uma instância por serviço/processo; serializa carga, tokenização e encode.

    O modelo injetado deve implementar tokenizer.encode, max_seq_length,
    get_sentence_embedding_dimension e encode. A fábrica recebe EmbeddingConfig.
    MiniLM recebe texto puro, sem prefixos E5 e sem título adicional.
    """

    def __init__(self, *, model=None, model_factory: Callable | None = None,
                 config: EmbeddingConfig = DEFAULT_CONFIG, batch_size: int = 32,
                 local_files_only: bool = False, cache_dir: str | None = None):
        if config != DEFAULT_CONFIG:
            raise IncompatibleConfig("ING-02 exige MiniLM na revisão fixa, CPU, 384 dimensões, norma L2 e 128 tokens.")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size deve ser inteiro positivo.")
        if model is not None and model_factory is not None:
            raise ValueError("Forneça model ou model_factory, não ambos.")
        self._config = config
        self._batch_size = batch_size
        self._supplied_model = model
        self._factory = model_factory or self._default_factory
        self._local_files_only = local_files_only
        self._cache_dir = cache_dir
        self._model = None
        self._snapshot_path = None
        self._lock = RLock()
        self._stats = {"model_loads": 0, "document_batches": 0, "document_texts": 0,
                       "question_batches": 0, "question_texts": 0}

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def _default_factory(self, config):
        # Importar este módulo ou construir o serviço não carrega pesos.
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer
        snapshot = snapshot_download(
            config.model, revision=config.revision, cache_dir=self._cache_dir,
            local_files_only=self._local_files_only,
            allow_patterns=["*.json", "*.safetensors", "tokenizer.*", "*.model", "README.md"],
            ignore_patterns=["onnx/*", "openvino/*"],
        )
        if Path(snapshot).name != config.revision:
            raise IncompatibleConfig("O snapshot resolvido não corresponde à revisão fixa.")
        # Pesos e tokenizer são lidos da mesma pasta imutável da revisão.
        model = SentenceTransformer(
            snapshot, revision=config.revision, device=config.device,
            local_files_only=True, trust_remote_code=False,
        )
        self._snapshot_path = str(snapshot)
        return model

    def _get_model(self):
        if self._model is None:
            try:
                model = self._supplied_model if self._supplied_model is not None else self._factory(self.config)
            except Exception as exc:
                raise EmbeddingUnavailable("Não foi possível carregar o MiniLM na revisão configurada.") from exc
            if model.max_seq_length != self.config.max_tokens:
                raise IncompatibleConfig("max_seq_length efetivo do modelo deve ser 128; não usar os 512 do tokenizer.")
            if self._dimension(model) != self.config.dimension:
                raise IncompatibleConfig("O modelo carregado deve produzir 384 dimensões.")
            if not callable(getattr(model.tokenizer, "encode", None)):
                raise IncompatibleConfig("O modelo precisa disponibilizar seu tokenizer.")
            self._model = model
            self._stats["model_loads"] += 1
        return self._model

    @staticmethod
    def _dimension(model):
        # Nome atual no SentenceTransformers 6; aceita o nome anterior em adaptadores.
        getter = getattr(model, "get_embedding_dimension", None)
        return getter() if callable(getter) else model.get_sentence_embedding_dimension()

    def load(self) -> None:
        with self._lock:
            self._get_model()

    def runtime_info(self) -> dict:
        with self._lock:
            model = self._get_model()
            return {"max_seq_length": model.max_seq_length,
                    "tokenizer_model_max_length": model.tokenizer.model_max_length,
                    "dimension": self._dimension(model),
                    "weights_and_tokenizer_snapshot": self._snapshot_path}

    def token_count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("O texto deve ser string.")
        with self._lock:
            return len(self._get_model().tokenizer.encode(text, add_special_tokens=True, truncation=False))

    def prepare_source(self, source: PreparationSource, *, source_type: SourceType) -> list[PreparedChunk]:
        with self._lock:
            return prepare_source(source, source_type=source_type,
                                  tokenizer=self._get_model().tokenizer, max_tokens=self.config.max_tokens)

    def _encode(self, texts: list[str], kind: str) -> np.ndarray:
        if not texts:
            return np.empty((0, self.config.dimension), dtype=np.float32)
        with self._lock:
            model = self._get_model()
            # Valida a coleção inteira antes da primeira chamada de encode.
            for text in texts:
                count = self.token_count(text)
                if count > self.config.max_tokens:
                    raise TokenLimitError(
                        f"{kind}: {count} tokens, limite {self.config.max_tokens} incluindo especiais; "
                        "reduza a pergunta ou reprepare os documentos com ING-01."
                    )
            batches = []
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start:start + self.batch_size]
                try:
                    values = model.encode(
                        batch, batch_size=self.batch_size, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False, precision="float32",
                        prompt="", device="cpu",
                    )
                except Exception as exc:
                    raise EmbeddingUnavailable("Falha na inferência MiniLM; nenhum corpus novo foi publicado.") from exc
                group = "document" if kind == "Documento" else "question"
                self._stats[f"{group}_batches"] += 1
                self._stats[f"{group}_texts"] += len(batch)
                batches.append(validate_vectors(values, len(batch), self.config.dimension))
            return np.concatenate(batches)

    def encode_chunks(self, chunks: Iterable[PreparedChunk]) -> np.ndarray:
        checked = validate_chunks(chunks)
        return self._encode([chunk["content"] for chunk in checked], "Documento")

    def encode_question(self, question: str) -> np.ndarray:
        if not isinstance(question, str):
            raise TypeError("A pergunta deve ser string.")
        if not question.strip():
            raise ValueError("A pergunta não pode ser vazia.")
        return self._encode([question], "Pergunta")[0]
