"""Contrato da preparação ING-01, implementado em src.rag.preparation."""

from typing import Literal, Protocol, TypedDict


SourceType = Literal["article", "case"]
PREPARATION_VERSION = "ing-01-v2"
MINILM_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Limite do SentenceTransformer, incluindo tokens especiais (não os 512 do tokenizer).
MINILM_MAX_TOKENS = 128


class PreparationSource(TypedDict):
    """Campos normalizados da GLPI-04; content ainda contém HTML.

    O adaptador de casos deverá fornecer o mesmo formato. Campos adicionais,
    como date_mod, podem acompanhar a entrada sem integrar o trecho.
    """

    id: int
    title: str
    content: str
    source_reference: str


class PreparedChunk(TypedDict):
    """Dicionário serializável; content contém texto convertido com html2text.

    chunk_id: {preparation_version}:{source_type}:{source_id}:{ordinal:04d}.
    A posição começa em zero dentro de cada fonte; title nunca identifica a fonte.
    """

    source_type: SourceType
    source_id: int
    source_reference: str
    title: str
    chunk_id: str
    content: str
    preparation_version: str


class PreparationTokenizer(Protocol):
    def encode(
        self, text: str, *, add_special_tokens: bool = True, truncation: bool = False,
    ) -> list[int]: ...


class PrepareSource(Protocol):
    """Assinatura de src.rag.preparation.prepare_source.

    Recebe o tokenizer real do MiniLM por injeção, sem carregar embeddings.
    O orçamento se aplica ao content final de cada trecho, sem truncamento.
    """

    def __call__(
        self, source: PreparationSource, *, source_type: SourceType,
        tokenizer: PreparationTokenizer, max_tokens: int = MINILM_MAX_TOKENS,
    ) -> list[PreparedChunk]: ...
