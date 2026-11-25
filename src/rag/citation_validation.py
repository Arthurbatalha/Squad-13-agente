"""RAG-05 (metade A) — validação determinística de citações e de especificidades.

Entra a resposta gerada (RAG-04) e a lista EXATA de evidências enviadas ao
gerador (as `chunks` da RAG-03). Sai um veredito. Nada aqui chama LLM, rede,
índice ou GLPI, e nada depende do prompt: é uma checagem posterior.

O que verifica
  1. Toda citação por `chunk_id` existe nas evidências fornecidas.
  2. Toda referência em linguagem natural ("artigo 12", "chamado 34") ou por
     caminho (`/Knowledgebase/Article/12`) aponta uma fonte fornecida. IDs só
     valem com o tipo: artigo 12 não autoriza caso 12.
  3. A resposta não traz especificidades ausentes das evidências: códigos com
     dígito (VPN-FIX-691), versões (2.3.1) e "passo N". A pergunta do usuário
     também conta como origem, para a recusa poder repeti-la.
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
from typing import Any, Iterable, Mapping

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
# Deliberadamente frouxo no ordinal: um ID quase certo deve ser pego e reprovado.
_CHUNK_ID_RE = re.compile(
    r"(?<![A-Za-z0-9._-])[A-Za-z0-9][A-Za-z0-9._-]*:(?:article|case):\d+:\d+(?![A-Za-z0-9_])"
)
_NUM = r"\s*(?:n[º°o.]*\s*)?#?\s*(\d+)\b"
_ARTICLE_REF_RE = re.compile(r"\b(?:artigo|article)\b" + _NUM, re.IGNORECASE)
_TICKET_REF_RE = re.compile(r"\b(?:chamado|ticket)\b" + _NUM, re.IGNORECASE)
_ARTICLE_PATH_RE = re.compile(r"/Knowledgebase/Article/(\d+)", re.IGNORECASE)
_TICKET_PATH_RE = re.compile(r"/Ticket/(\d+)", re.IGNORECASE)

_VERSION_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+){1,3}(?!\w|\.\d)")
_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_])"
)
_STEP_RE = re.compile(r"\b(?:passo|etapa|step)\b" + _NUM, re.IGNORECASE)
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
    """Minúsculas, sem acento de composição e com `-`/`_` tratados como espaço."""
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = re.sub(r"[-_]", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _contains(haystack: str, needle: str) -> bool:
    """Presença com limites: `691` não casa com `6910`, nem `2.3` com `2.3.1`."""
    pattern = (
        r"(?<![a-z0-9])(?<!\d\.)" + re.escape(needle) + r"(?![a-z0-9])(?!\.\d)"
    )
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

    `evidence` deve ser exatamente a lista passada ao `GeminiAdapter` (RAG-04),
    isto é, `result["chunks"]` da RAG-03 quando `status == "evidence"`.
    `require_citation=False` serve para recusa/esclarecimento, que não cita.

    Precedência do veredito: invalid_citation > unsupported_specifics >
    no_citation > valid.
    """
    if not isinstance(answer, str):
        raise TypeError("answer deve ser texto.")
    items = _normalise_evidence(evidence)
    by_chunk = {item["chunk_id"]: item for item in items}
    first_of_source: dict[tuple[str, str], dict[str, str]] = {}
    for item in items:
        first_of_source.setdefault((item["source_type"], item["source_id"]), item)

    invalid: list[InvalidCitation] = []
    cited: list[str] = []
    display: list[dict[str, str]] = []
    displayed_chunks: set[str] = set()

    def show(item: Mapping[str, str]) -> None:
        if item["chunk_id"] not in displayed_chunks:
            displayed_chunks.add(item["chunk_id"])
            display.append(_display_source(item))

    # 1) citações por chunk_id
    chunk_spans = []
    for match in _CHUNK_ID_RE.finditer(answer):
        chunk_spans.append(match.span())
        token = match.group(0)
        item = by_chunk.get(token)
        if item is None:
            invalid.append(InvalidCitation(token, KIND_CHUNK_ID, REASON_NOT_RETRIEVED))
        elif token not in cited:
            cited.append(token)
            show(item)

    # 2) referências em linguagem natural ou por caminho (tipo + ID)
    reference_sources: list[dict[str, str]] = []
    for kind, source_type, regexes in (
        (KIND_ARTICLE_REFERENCE, "article", (_ARTICLE_REF_RE, _ARTICLE_PATH_RE)),
        (KIND_TICKET_REFERENCE, "case", (_TICKET_REF_RE, _TICKET_PATH_RE)),
    ):
        for regex in regexes:
            for match in regex.finditer(answer):
                source = first_of_source.get((source_type, match.group(1)))
                if source is None:
                    invalid.append(
                        InvalidCitation(match.group(0).strip(), kind, REASON_UNKNOWN_SOURCE)
                    )
                else:
                    reference_sources.append(source)

    cited_source_keys = {
        (by_chunk[c]["source_type"], by_chunk[c]["source_id"]) for c in cited
    }
    for source in reference_sources:
        key = (source["source_type"], source["source_id"])
        if key not in cited_source_keys:
            cited_source_keys.add(key)
            show(source)

    # 3) especificidades sem suporte (IDs de chunk não contam como código)
    corpus = "\n".join(f"{i['title']}\n{i['content']}" for i in items) + "\n" + question
    unsupported = _unsupported_specifics(_blank_spans(answer, chunk_spans), corpus)

    has_citation = bool(cited_source_keys)
    if invalid:
        verdict = VERDICT_INVALID_CITATION
    elif unsupported:
        verdict = VERDICT_UNSUPPORTED
    elif require_citation and not has_citation:
        verdict = VERDICT_NO_CITATION
    else:
        verdict = VERDICT_VALID

    return ValidationResult(
        verdict=verdict,
        cited_chunk_ids=tuple(cited),
        invalid_citations=tuple(invalid),
        unsupported_specifics=tuple(unsupported),
        sources=tuple(display),
    )
