"""Preparação ING-01: HTML para trechos Markdown, sem embeddings ou I/O."""

from collections.abc import Iterator, Mapping
from html.parser import HTMLParser
import re

import html2text

from src.rag.chunk_contract import (
    MINILM_MAX_TOKENS, PREPARATION_VERSION, PreparationSource,
    PreparationTokenizer, PreparedChunk, SourceType,
)


class _ListItemCounts(HTMLParser):
    """Conta itens por lista para o início implícito de ol reversed."""

    def __init__(self) -> None:
        super().__init__()
        self.counts: list[int] = []
        self.stack: list[int] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("ol", "ul"):
            self.stack.append(len(self.counts))
            self.counts.append(0)
        elif tag == "li" and self.stack:
            self.counts[self.stack[-1]] += 1

    def handle_endtag(self, tag):
        if tag in ("ol", "ul") and self.stack:
            self.stack.pop()


def _list_integer(value: str | None, default: int) -> int:
    # Atributos inválidos usam o valor implícito, como listas HTML comuns.
    if value is None or not re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        return default
    return int(value)


class _NumberedHTML2Text(html2text.HTML2Text):
    """Mantém o renderizador html2text, ajustando somente seu contador de li.

    Integração com HTML2Text.list/ListElement.num da versão fixada 2025.4.15.
    Cada lista tem seu próprio próximo número e direção, inclusive aninhadas.
    """

    def __init__(self, counts: list[int]) -> None:
        super().__init__()
        self.body_width = 0
        self._counts = iter(counts)
        self._numbering: list[tuple[int, int] | None] = []

    def handle_tag(self, tag, attrs, start):
        if start and tag in ("ol", "ul"):
            count = next(self._counts)
            if tag == "ol":
                direction = -1 if "reversed" in attrs else 1
                initial = _list_integer(attrs.get("start"), count if direction == -1 else 1)
                self._numbering.append((initial, direction))
                attrs = dict(attrs, start=str(initial))
            else:
                self._numbering.append(None)
        elif start and tag == "li" and self._numbering and self._numbering[-1] is not None:
            number, direction = self._numbering[-1]
            number = _list_integer(attrs.get("value"), number)
            # html2text incrementa num imediatamente antes de emitir o marcador.
            self.list[-1].num = number - 1
            self._numbering[-1] = (number + direction, direction)

        super().handle_tag(tag, attrs, start)
        if not start and tag in ("ol", "ul") and self._numbering:
            self._numbering.pop()


def prepare_source(
    source: PreparationSource, *, source_type: SourceType,
    tokenizer: PreparationTokenizer, max_tokens: int = MINILM_MAX_TOKENS,
) -> list[PreparedChunk]:
    """Converte uma fonte sem modificá-la e conta cada trecho sem truncamento.

    Tipos incorretos geram TypeError; campos ausentes, valores inválidos ou
    orçamento insuficiente geram ValueError. O tokenizer é fornecido pelo
    chamador; esta função não carrega modelos nem acessa a rede.
    """
    if not isinstance(source, Mapping):
        raise TypeError("source deve ser um mapeamento.")
    if not isinstance(source_type, str) or source_type not in ("article", "case"):
        raise ValueError("source_type deve ser article ou case.")
    for field in ("id", "title", "content", "source_reference"):
        if field not in source:
            raise ValueError(f"Campo obrigatório ausente: {field}.")
    if type(source["id"]) is not int:
        raise TypeError("id deve ser inteiro, sem aceitar booleanos.")
    if source["id"] < 0:
        raise ValueError("id não pode ser negativo.")
    for field in ("title", "content", "source_reference"):
        if not isinstance(source[field], str):
            raise TypeError(f"{field} deve ser string.")
        if not source[field].strip():
            raise ValueError(f"{field} não pode ser vazio.")
    reference = {
        "article": "/Knowledgebase/Article", "case": "/Assistance/Ticket",
    }[source_type]
    if source["source_reference"] != reference:
        raise ValueError("source_reference incompatível com source_type.")
    if type(max_tokens) is not int:
        raise TypeError("max_tokens deve ser inteiro, sem aceitar booleanos.")
    if not 0 < max_tokens <= MINILM_MAX_TOKENS:
        raise ValueError(f"max_tokens deve estar entre 1 e {MINILM_MAX_TOKENS}.")
    if not callable(getattr(tokenizer, "encode", None)):
        raise TypeError("tokenizer deve fornecer encode.")

    def fits(text: str) -> bool:
        return len(tokenizer.encode(
            text, add_special_tokens=True, truncation=False,
        )) <= max_tokens

    if len(tokenizer.encode("", add_special_tokens=True, truncation=False)) >= max_tokens:
        raise ValueError("max_tokens não comporta conteúdo além dos tokens especiais.")

    counter = _ListItemCounts()
    counter.feed(source["content"])
    counter.close()
    converter = _NumberedHTML2Text(counter.counts)
    text = converter.handle(source["content"]).strip()
    if not text:
        raise ValueError("content não contém texto após a conversão do HTML.")

    def units() -> Iterator[str]:
        # Mantém linhas/listas inteiras quando cabem. Nunca decodifica subwords:
        # fatias do Markdown original preservam acentos, códigos e pontuação.
        for line in text.splitlines(keepends=True):
            if fits(line):
                yield line
                continue
            for word in re.findall(r"\S+\s*|\s+", line):
                if fits(word):
                    yield word
                else:
                    for character in word:
                        if not fits(character):
                            raise ValueError("max_tokens insuficiente para um caractere do conteúdo.")
                        yield character

    contents = []
    current = ""
    for unit in units():
        candidate = current + unit
        if current and not fits(candidate):
            if current.strip():
                contents.append(current)
            current = unit
        else:
            current = candidate
    if current.strip():
        contents.append(current)

    return [
        {
            "source_type": source_type,
            "source_id": source["id"],
            "source_reference": source["source_reference"],
            "title": source["title"],
            "chunk_id": f"{PREPARATION_VERSION}:{source_type}:{source['id']}:{ordinal:04d}",
            "content": content,
            "preparation_version": PREPARATION_VERSION,
        }
        for ordinal, content in enumerate(contents)
    ]
