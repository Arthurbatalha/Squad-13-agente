"""RAG-05 (metade A) — validação determinística de citações e de especificidades.

Entra a resposta gerada (RAG-04) e a lista EXATA de evidências enviadas ao
gerador (`GenerationResult.prompt_evidence`). Sai um veredito. Nada aqui chama LLM, rede,
índice ou GLPI, e nada depende do prompt: é uma checagem posterior.

O que verifica
  1. Toda citação por `chunk_id` existe nas evidências fornecidas.
  2. Toda referência em linguagem natural ("artigo 12", "chamado 34") ou por
     caminho (`/Knowledgebase/Article/12`) aponta uma fonte fornecida. IDs só
     valem com o tipo: artigo 12 não autoriza caso 12.
  3. A resposta não traz especificidades ausentes das evidências: códigos com
     dígito (VPN-FIX-691), versões (2.3.1) e "passo N". A pergunta do usuário
     só conta como origem em recusas e esclarecimentos.
  4. As fontes mostradas ao usuário vêm do CATÁLOGO RECUPERADO, nunca do texto
     do modelo (título/referência inventados não chegam à tela).

O que NÃO verifica (limites declarados)
  * Suporte semântico: não prova que a frase decorre do trecho. Isso é
    avaliação (RAG-02) e revisão humana.
  * Números simples, nomes, autoria e datas por extenso.
  * Se a resposta é uma recusa/esclarecimento: quem decide é a política da
    metade B, que chama com `require_citation=False` nesses casos.

Falha fechada: na dúvida, o veredito NÃO é `valid`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import chain
from typing import Any, Iterable, Mapping

from src.rag.chunk_contract import PREPARATION_VERSION

VERDICT_VALID = "valid"
VERDICT_NO_CITATION = "no_citation"
VERDICT_INVALID_CITATION = "invalid_citation"
VERDICT_UNSUPPORTED = "unsupported_specifics"

KIND_CHUNK_ID = "chunk_id"
KIND_ARTICLE_REFERENCE = "article_reference"
KIND_TICKET_REFERENCE = "ticket_reference"

REASON_NOT_RETRIEVED = "not_retrieved"
REASON_UNKNOWN_SOURCE = "unknown_source"

EXCERPT_MAX_CHARS = 280

_REQUIRED_EVIDENCE_KEYS = ("chunk_id", "source_type", "source_id", "title", "content")

# `{preparation_version}:{source_type}:{source_id}:{ordinal}` (chunk_contract.py).
# Capture também sufixos incorretos para que um prefixo válido não passe por ID.
# Um ponto final da frase só pertence ao identificador se vier seguido de texto.
_ID = r"[\w-]+(?:\.[\w-]+)*"
# Símbolos admitidos em segmentos de URL também distinguem uma referência
# inválida de um ID numérico seguido de pontuação da frase.
_SOURCE_ID = r"[\w%+~@=&$-]+(?:\.[\w%+~@=&$-]+)*"
_NUMBER_LABEL = r"\s*(?:n[º°o.]*\s*)?#?\s*"
_CHUNK_PREFIX = rf"(?:{_ID}:(?:article|case)|{re.escape(PREPARATION_VERSION)}:[\w-]+)"
_CITATION_RE = re.compile(
    rf"(?P<chunk>(?<![\w.-]){_CHUNK_PREFIX}:{_ID}:{_ID}(?::[\w.-]+)*)"
    rf"|(?:/Knowledgebase/Article/|\b(?:artigo|article)\b{_NUMBER_LABEL}(?=\d))(?P<article>{_SOURCE_ID})"
    rf"|(?:/(?:Assistance/)?Ticket/|\b(?:chamado|ticket)\b{_NUMBER_LABEL}(?=\d))(?P<case>{_SOURCE_ID})",
    re.IGNORECASE,
)

_VERSION_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+){1,3}(?!\w|\.\d)")
_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_])"
)
_STEP_RE = re.compile(r"\b(?:passo|etapa|step)\b" + _NUMBER_LABEL + r"(\d+)\b", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(\d+)[.)]\s")


@dataclass(frozen=True)
class InvalidCitation:
    token: str   # texto encontrado na resposta
    kind: str    # chunk_id | article_reference | ticket_reference
    reason: str  # not_retrieved | unknown_source


@dataclass(frozen=True)
class ValidationResult:
    verdict: str
    cited_chunk_ids: tuple[str, ...]
    invalid_citations: tuple[InvalidCitation, ...]
    unsupported_specifics: tuple[str, ...]
    # Fontes para exibir, no formato `Source` do contrato da UI-01.
    sources: tuple[dict[str, str], ...]

    @property
    def ok(self) -> bool:
        return self.verdict == VERDICT_VALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "ok": self.ok,
            "cited_chunk_ids": list(self.cited_chunk_ids),
            "invalid_citations": [
                {"token": c.token, "kind": c.kind, "reason": c.reason}
                for c in self.invalid_citations
            ],
            "unsupported_specifics": list(self.unsupported_specifics),
            "sources": [dict(s) for s in self.sources],
        }


def _canon(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _contains(haystack: str, needle: str) -> bool:
    # Admite "Windows 11" para "Windows-11", preservando as bordas do código.
    parts = re.split(r"[-_]", needle)
    token = r"(?:[-_]|[^\S\r\n]+)".join(map(re.escape, parts))
    pattern = r"(?<![\w-])(?<!\d\.)" + token + r"(?![\w-]|\.\d)"
    return re.search(pattern, haystack) is not None


def _normalise_evidence(evidence: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    items = []
    for item in evidence:
        if not isinstance(item, Mapping):
            raise TypeError("Cada evidência deve ser um mapeamento.")
        if any(item.get(key) in (None, "") for key in _REQUIRED_EVIDENCE_KEYS):
            raise ValueError("Evidência sem identificação/rastreabilidade completa.")
        items.append({
            "chunk_id": str(item["chunk_id"]),
            "source_type": str(item["source_type"]),
            "source_id": str(item["source_id"]),
            "title": str(item["title"]),
            "content": str(item["content"]),
            "reference": str(item.get("source_reference") or ""),
        })
    return items


def _display_source(item: Mapping[str, str]) -> dict[str, str]:
    excerpt = " ".join(item["content"].split())
    if len(excerpt) > EXCERPT_MAX_CHARS:
        excerpt = excerpt[: EXCERPT_MAX_CHARS - 1].rstrip() + "…"
    return {
        "source_type": item["source_type"],
        "source_id": item["source_id"],
        "title": item["title"],
        "reference": item["reference"],
        "chunk_id": item["chunk_id"],
        "excerpt": excerpt,
    }


def _blank_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _evidence_steps(corpus: str) -> set[str]:
    steps = {m.group(1) for m in _STEP_RE.finditer(corpus)}
    steps |= {m.group(1) for m in _LIST_ITEM_RE.finditer(corpus)}
    return steps


def _unsupported_specifics(answer: str, corpus: str) -> list[str]:
    canon_corpus = _canon(corpus)
    found: list[str] = []

    def add(label: str) -> None:
        if label not in found:
            found.append(label)

    for regex in (_CODE_RE, _VERSION_RE):
        for match in regex.finditer(answer):
            token = match.group(0)
            if not _contains(canon_corpus, _canon(token)):
                add(token)

    steps = _evidence_steps(corpus)
    for match in _STEP_RE.finditer(answer):
        if match.group(1) not in steps:
            add(" ".join(match.group(0).split()))
    return found


def validate_answer(
    answer: str,
    evidence: Iterable[Mapping[str, Any]],
    *,
    question: str = "",
    require_citation: bool = True,
) -> ValidationResult:
    """Valida `answer` contra as `evidence` que foram enviadas ao gerador.

    `evidence` deve ser o `prompt_evidence` devolvido pelo adaptador após aplicar
    o orçamento do prompt aos trechos autorizados da RAG-03.
    `require_citation=False` serve para recusa/esclarecimento, que não cita.

    Precedência do veredito: invalid_citation > unsupported_specifics >
    no_citation > valid.
    """
    if not isinstance(answer, str):
        raise TypeError("answer deve ser texto.")
    items = _normalise_evidence(evidence)
    by_chunk = {item["chunk_id"]: item for item in items}
    matches = list(_CITATION_RE.finditer(answer))
    cited = list(dict.fromkeys(m["chunk"] for m in matches if m["chunk"] in by_chunk))

    # Uma referência à fonte prefere um trecho explicitamente citado dela.
    preferred = {}
    for item in chain((by_chunk[token] for token in cited), items):
        preferred.setdefault((item["source_type"], item["source_id"]), item)

    invalid = []
    display = {}
    chunk_spans = []
    for match in matches:
        kind = match.lastgroup
        if kind == "chunk":
            chunk_spans.append(match.span())
            item = by_chunk.get(match["chunk"])
            if item is None:
                invalid.append(InvalidCitation(match[0], KIND_CHUNK_ID, REASON_NOT_RETRIEVED))
        else:
            item = preferred.get((kind, match[kind]))
            if item is None:
                label = KIND_ARTICLE_REFERENCE if kind == "article" else KIND_TICKET_REFERENCE
                invalid.append(InvalidCitation(match[0], label, REASON_UNKNOWN_SOURCE))
        if item is not None:
            display[item["chunk_id"]] = item

    corpus = "\n".join(f"{i['title']}\n{i['content']}" for i in items)
    if not require_citation:
        corpus += "\n" + question
    unsupported = _unsupported_specifics(_blank_spans(answer, chunk_spans), corpus)

    if invalid:
        verdict = VERDICT_INVALID_CITATION
    elif unsupported:
        verdict = VERDICT_UNSUPPORTED
    elif require_citation and not display:
        verdict = VERDICT_NO_CITATION
    else:
        verdict = VERDICT_VALID

    return ValidationResult(
        verdict=verdict,
        cited_chunk_ids=tuple(cited),
        invalid_citations=tuple(invalid),
        unsupported_specifics=tuple(unsupported),
        sources=tuple(_display_source(item) for item in display.values()),
    )
