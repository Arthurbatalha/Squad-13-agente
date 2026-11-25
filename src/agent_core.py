"""Ponto de integração de geração RAG-04.

A recuperação e autorização são responsabilidade do chamador; este módulo
recebe apenas evidências já selecionadas e delega a geração ao adaptador.
"""
from src.model.gemini_adapter import GeminiAdapter


class RAGGenerationGraph:
    """Fachada mínima até RAG-01 conectar ferramentas e estado do agente."""

    def __init__(self, adapter=None, *, checkpointer=None):
        # Inicialização preguiçosa: a API/UI em modo mock não exige chave Gemini.
        self.adapter = adapter
        self.checkpointer = checkpointer

    def invoke(self, state, config=None):
        if not isinstance(state, dict):
            raise TypeError("state deve ser um dicionário.")
        question = state.get("question") or state.get("input")
        evidence = state.get("evidence", [])
        history = state.get("history")
        adapter = self.adapter or GeminiAdapter.from_env()
        result = adapter.generate(question, evidence, history)
        return {
            **state,
            "answer": result.text,
            "prompt_evidence": result.prompt_evidence,
            "model": result.model,
            "input_tokens_estimated": result.input_tokens_estimated,
        }


def build_graph(checkpointer=None, *, model_adapter=None):
    """Constrói a fachada sem exigir acesso ao provedor durante o startup.

    `checkpointer` e a injeção de modelo preservam o contrato esperado pela API
    e pelos testes; a composição completa do agente/tooling pertence à RAG-01.
    """
    return RAGGenerationGraph(model_adapter, checkpointer=checkpointer)
