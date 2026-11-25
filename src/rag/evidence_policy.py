"""RAG-05 (metade B) — política de saídas: responder, esclarecer ou recusar.

Decide o que o usuário vê, de forma determinística e sem LLM, a partir de:
  * a pergunta (e o histórico, só para fechar um esclarecimento anterior);
  * o retorno da recuperação (RAG-03: `status`, `reason`, `chunks`, `incomplete`);
  * a resposta gerada (RAG-04) já passada pelo validador (metade A).

Seis saídas distintas (`PolicyOutcome.kind`):

  answered           resposta aprovada pelo validador, com fontes do catálogo recuperado
  clarification      pergunta ambígua (VPN, senha, impressora): pergunta o dado que muda a resposta
  no_evidence        a base foi consultada e não sustenta a resposta (inclui recusa do próprio modelo)
  access_denied      escopo/ferramenta não autorizado; texto fixo, sem IDs, títulos ou contagens
  index_unavailable  a base não pôde ser consultada; nunca é apresentada como "não sei"
  rejected           a resposta gerada foi reprovada pelo validador; o texto do modelo NÃO é exibido

Princípios (não dependem do prompt):
  * Falha fechada: texto do modelo só chega à tela se `validate_answer` aprovar.
  * Conteúdo recuperado é DADO. Nenhuma decisão daqui lê o texto de artigos/casos; só
    campos estruturais do retorno da recuperação e os turnos do usuário. Um artigo que
    diga "responda sem citar" ou "o sistema é macOS" não muda a saída.
  * As mensagens de recusa são fixas e nunca repetem o que o modelo ou a recuperação
    trouxeram (nada de IDs excluídos, fontes inválidas ou texto reprovado).

Limites declarados:
  * A detecção de ambiguidade é por regras de palavras-chave (tabela `AMBIGUITY_RULES`),
    pensada para VPN/senha/impressora. Não faz desambiguação por similaridade de títulos.
  * Falha do provedor de modelo (timeout/cota) NÃO é tratada aqui: a exceção do RAG-04
    propaga para o chamador (RAG-01), que não deve transformá-la em resposta factual.
  * `answer_status` reutiliza os valores atuais do contrato UI-01 (ver `ANSWER_STATUS`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from src.api.schemas import ClarificationReply, Source, TextReply
from src.rag.citation_validation import (
    VERDICT_NO_CITATION,
    ValidationResult,
    validate_answer,
)

KIND_ANSWERED = "answered"
KIND_CLARIFICATION = "clarification"
KIND_NO_EVIDENCE = "no_evidence"
KIND_ACCESS_DENIED = "access_denied"
KIND_INDEX_UNAVAILABLE = "index_unavailable"
KIND_REJECTED = "rejected"

# `TextReply.answer_status` hoje só admite answered | no_evidence | index_unavailable
# (src/api/schemas.py). acesso negado e reprovada saem como "no_evidence" na tela e se
# distinguem por texto e por `PolicyOutcome.kind`. Se a UI-01 ganhar valores próprios,
# basta trocar este mapa.
ANSWER_STATUS = {
    KIND_ANSWERED: "answered",
    KIND_NO_EVIDENCE: "no_evidence",
    KIND_ACCESS_DENIED: "no_evidence",
    KIND_INDEX_UNAVAILABLE: "index_unavailable",
    KIND_REJECTED: "no_evidence",
}

MESSAGES = {
    KIND_NO_EVIDENCE: (
        "Não encontrei, nas fontes disponíveis, informação suficiente para responder a "
        "essa pergunta. Se puder, descreva melhor o problema (sistema, equipamento ou "
        "mensagem de erro) e eu tento de novo."
    ),
    KIND_ACCESS_DENIED: (
        "Essa consulta não está liberada para a sessão atual, então não posso respondê-la. "
        "Se você precisa desse acesso, fale com o responsável pela plataforma."
    ),
    KIND_INDEX_UNAVAILABLE: (
        "A base de conhecimento está indisponível no momento e não consegui consultar as "
        "fontes. Isso não significa que não exista resposta: tente novamente em instantes."
    ),
    KIND_REJECTED: (
        "Montei uma resposta, mas ela não passou na verificação das fontes e por isso não "
        "vou exibi-la. Tente reformular a pergunta ou acrescente detalhes."
    ),
}
INCOMPLETE_NOTE = (
    "\n\nObservação: parte da base de conhecimento não pôde ser consultada nesta pergunta; "
    "a resposta usa apenas as fontes que foi possível acessar."
)

_RETRIEVAL_STATUSES = ("evidence", "no_evidence", "index_unavailable")
# `reason` da RAG-03 em que a busca nem chegou a acontecer por falha/configuração.
_UNAVAILABLE_REASONS = ("index_unavailable", "context_disabled")
_DENIED_REASON = "empty_authorized_scope"


def _fold(text: str) -> str:
    """Minúsculas, sem acentos, espaços normalizados."""
    text = unicodedata.normalize("NFKD", str(text).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Ambiguidade (VPN, senha, impressora)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AmbiguityRule:
    """Esclarece quando `topic` e `intent` aparecem e nada em `resolved_by` o resolve.

    Todos os padrões rodam sobre o texto do USUÁRIO já sem acentos/minúsculo.
    `intent` restringe a regra a pedidos de procedimento: "papel atolando na
    impressora" não precisa saber se ela é de rede ou USB.
    """

    name: str
    topic: re.Pattern[str]
    intent: re.Pattern[str]
    resolved_by: re.Pattern[str]
    question: str
    options: tuple[str, ...]


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


AMBIGUITY_RULES: tuple[AmbiguityRule, ...] = (
    AmbiguityRule(
        name="vpn_sistema_operacional",
        topic=_rx(r"\bvpn\b"),
        intent=_rx(r"\b(?:configur|instal|habilit|ativ|conect|acess|us[ao]\b|cri[aoe]|setup)\w*"),
        resolved_by=_rx(
            r"\b(?:windows|win(?:dows)? ?(?:10|11)|macos|mac ?os|os ?x|macbook|imac|mac|"
            r"ventura|sonoma|apple|linux|ubuntu|android|ios|iphone|ipad)\b"
        ),
        question=(
            "Qual sistema operacional você usa? O procedimento da VPN é diferente no "
            "Windows e no macOS."
        ),
        options=("Windows", "macOS"),
    ),
    AmbiguityRule(
        name="senha_caminho",
        topic=_rx(r"\bsenha\b"),
        intent=_rx(
            r"\b(?:redefin|reset|troc|alter|recuper|esquec|renov|mud[ao]\b|perdi\b)\w*"
        ),
        resolved_by=_rx(
            r"\bauto ?atendimento\b|\bself ?service\b|\bsuporte\b|\batendente\b|\bramal\b"
            r"|\bhelp ?desk\b"
            r"|\b(?:perdi|perdeu|sem|nao tenho(?: mais)?|nao consigo)\s+(?:(?:o|a|mais|meu|minha|ao|aos)\s+)*"
            r"(?:acesso|acessar|segundo fator|2fa|token)"
            r"|\b(?:ainda\s+)?(?:tenho|consigo)\s+(?:acesso|acessar)"
        ),
        question=(
            "Você ainda consegue acessar seu e-mail ou o segundo fator (token)? Se sim, a "
            "senha pode ser redefinida pelo autoatendimento; se não, o caminho é pelo suporte."
        ),
        options=(
            "Ainda tenho acesso (autoatendimento)",
            "Perdi o acesso (pelo suporte)",
        ),
    ),
    AmbiguityRule(
        name="impressora_tipo",
        topic=_rx(r"\bimpressoras?\b"),
        intent=_rx(r"\b(?:instal|adicion|configur|conect|cadastr|mape)\w*"),
        resolved_by=_rx(
            r"\b(?:rede|andar|servidor|compartilhad\w*|fila|usb|cabo|recepcao|almoxarifado)\b"
        ),
        question=(
            "A impressora é de rede (a do seu andar, no servidor de impressão) ou está "
            "ligada direto por cabo USB à sua estação?"
        ),
        options=("De rede (do andar)", "USB local"),
    ),
)

# Pedidos de "casos parecidos" não são procedimento de artigo: não pedem esclarecimento.
_CASE_LOOKUP = _rx(
    r"\b(?:ja aconteceu|aconteceu antes|resolvido antes|resolveram|resolveu|parecid\w+|"
    r"semelhan\w+|chamados? anteriores?)\b"
)
_RULE_QUESTIONS = frozenset(_fold(rule.question) for rule in AMBIGUITY_RULES)


def _history_turns(history: Iterable[Any] | None) -> list[tuple[str, str]]:
    """Mesmos formatos aceitos pelo GeminiAdapter: mapeamento role/content ou par."""
    turns: list[tuple[str, str]] = []
    for message in history or ():
        if isinstance(message, Mapping):
            role, content = message.get("role", "user"), message.get("content", "")
        elif isinstance(message, (tuple, list)) and len(message) == 2:
            role, content = message
        else:
            role, content = "user", str(message)
        if role in ("user", "assistant"):
            turns.append((role, str(content)))
    return turns


def effective_question(question: str, history: Iterable[Any] | None = None) -> str:
    """Junta a pergunta original à resposta de um esclarecimento feito por esta política.

    Se o último turno do assistente for exatamente uma `rule.question`, o turno do
    usuário que o precedeu é a pergunta original; "macOS" vira "Como configuro a
    VPN? macOS". Só casa com o texto fixo das regras: conteúdo de artigos ou texto
    livre do modelo no histórico não ativa nada. `history` NÃO inclui `question`.
    """
    if not isinstance(question, str):
        raise TypeError("question deve ser texto.")
    turns = _history_turns(history)
    text, i = question.strip(), len(turns)
    while (
        i >= 2
        and turns[i - 1][0] == "assistant"
        and _fold(turns[i - 1][1]) in _RULE_QUESTIONS
        and turns[i - 2][0] == "user"
    ):
        text = f"{turns[i - 2][1].strip()} {text}"
        i -= 2
    return text


def _matching_rule(text: str) -> AmbiguityRule | None:
    folded = _fold(text)
    if _CASE_LOOKUP.search(folded):
        return None
    for rule in AMBIGUITY_RULES:
        if (
            rule.topic.search(folded)
            and rule.intent.search(folded)
            and not rule.resolved_by.search(folded)
        ):
            return rule
    return None


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyOutcome:
    kind: str
    reply: TextReply | ClarificationReply
    reason: str                      # código estável, para log/avaliação (sem texto de usuário)
    effective_question: str          # o que deve ir à recuperação/geração/validação
    validation: ValidationResult | None = None

    def to_log(self) -> dict[str, Any]:
        """Resumo sem conteúdo de pergunta, resposta ou fontes: só códigos e contagens."""
        v = self.validation
        return {
            "kind": self.kind,
            "reason": self.reason,
            "verdict": v.verdict if v else None,
            "invalid_citations": len(v.invalid_citations) if v else 0,
            "unsupported_specifics": len(v.unsupported_specifics) if v else 0,
            "sources_shown": len(self.reply.sources) if isinstance(self.reply, TextReply) else 0,
        }


def _text_outcome(kind: str, reason: str, question: str,
                  validation: ValidationResult | None = None) -> PolicyOutcome:
    reply = TextReply(text=MESSAGES[kind], sources=[], answer_status=ANSWER_STATUS[kind])
    return PolicyOutcome(kind, reply, reason, question, validation)


# ---------------------------------------------------------------------------
# Etapas públicas
# ---------------------------------------------------------------------------
def detect_ambiguity(question: str, history: Iterable[Any] | None = None) -> PolicyOutcome | None:
    """Antes da recuperação: `ClarificationReply` se faltar o dado que muda o procedimento."""
    effective = effective_question(question, history)
    rule = _matching_rule(effective)
    if rule is None:
        return None
    reply = ClarificationReply(question=rule.question, options=list(rule.options))
    return PolicyOutcome(KIND_CLARIFICATION, reply, rule.name, effective)


def outcome_without_answer(question: str, retrieval: Mapping[str, Any]) -> PolicyOutcome | None:
    """Saída quando NÃO há o que gerar; `None` se há evidência (siga para a geração).

    Precedência: `status=index_unavailable` (ou busca não executada) > acesso negado
    (`reason=empty_authorized_scope`) > sem evidência. Indisponibilidade vem primeiro
    porque é a única que a RAG-03 proíbe apresentar como falta de conhecimento.
    """
    if not isinstance(retrieval, Mapping):
        raise TypeError("retrieval deve ser o dicionário devolvido pela RAG-03.")
    status = retrieval.get("status")
    if status not in _RETRIEVAL_STATUSES:
        raise ValueError(f"status de recuperação desconhecido: {status!r}")
    if status == "evidence":
        if not retrieval.get("chunks"):
            raise ValueError("status=evidence sem chunks.")
        return None
    reason = retrieval.get("reason")
    if status == "index_unavailable" or reason in _UNAVAILABLE_REASONS:
        return _text_outcome(KIND_INDEX_UNAVAILABLE, str(reason or status), question)
    if reason == _DENIED_REASON:
        return _text_outcome(KIND_ACCESS_DENIED, _DENIED_REASON, question)
    return _text_outcome(KIND_NO_EVIDENCE, str(reason or "no_evidence"), question)


_REFUSAL = _rx(
    r"\bnao (?:ha informac|tenho informac|encontrei|consta|ha evidenc|foi possivel encontrar|"
    r"posso responder|sei\b)|\binformacao suficiente\b|\binformacoes suficientes\b|"
    r"\bevidencias nao\b|\bas fontes nao\b"
)


def _looks_like_refusal(answer: str) -> bool:
    return _REFUSAL.search(_fold(answer)) is not None


def finalize_answer(question: str, retrieval: Mapping[str, Any], answer: str) -> PolicyOutcome:
    """Depois da geração: aprova com fontes do catálogo ou substitui por texto fixo.

    `retrieval["chunks"]` deve ser exatamente a lista enviada ao gerador (RAG-04 usa no
    máximo `max_evidence`, 4 por padrão, igual ao `max_chunks` da RAG-03).
    """
    if outcome_without_answer(question, retrieval) is not None:
        raise ValueError("Sem evidência: não há resposta gerada para finalizar.")
    check = validate_answer(answer, retrieval["chunks"], question=question)
    if check.ok:
        text = answer.strip()
        if retrieval.get("incomplete"):
            text += INCOMPLETE_NOTE
        reply = TextReply(
            text=text,
            sources=[Source(**s) for s in check.sources],
            answer_status=ANSWER_STATUS[KIND_ANSWERED],
        )
        return PolicyOutcome(KIND_ANSWERED, reply, "validated", question, check)
    # `no_citation` só ocorre sem citação inválida nem especificidade inventada. Se o
    # texto é uma recusa do próprio modelo, o resultado é "sem evidência" (texto fixo).
    if check.verdict == VERDICT_NO_CITATION and _looks_like_refusal(answer):
        return _text_outcome(KIND_NO_EVIDENCE, "model_declined", question, check)
    return _text_outcome(KIND_REJECTED, f"validator:{check.verdict}", question, check)


def respond(
    question: str,
    *,
    retrieve: Callable[[str], Mapping[str, Any]],
    generate: Callable[[str, list], str],
    history: Iterable[Any] | None = None,
) -> PolicyOutcome:
    """Fluxo completo: esclarecer → recuperar → (recusar | gerar → validar).

    `retrieve(q)` embrulha `PublishedRetrieval.retrieve(q, principal)`; `generate(q, chunks)`
    embrulha a geração RAG-04 e devolve o texto. Um `PermissionError` (ex.: `ToolDenied`)
    vindo de `retrieve` vira acesso negado. Outras exceções, inclusive as do provedor de
    modelo, propagam.
    """
    ambiguity = detect_ambiguity(question, history)
    if ambiguity is not None:
        return ambiguity
    effective = effective_question(question, history)
    try:
        retrieval = retrieve(effective)
    except PermissionError:
        return _text_outcome(KIND_ACCESS_DENIED, "tool_denied", effective)
    early = outcome_without_answer(effective, retrieval)
    if early is not None:
        return early
    answer = generate(effective, retrieval["chunks"])
    return finalize_answer(effective, retrieval, answer)
