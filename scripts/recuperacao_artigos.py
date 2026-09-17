from __future__ import annotations

import html
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

from torch import threshold


MODELO_PADRAO = os.getenv(
    "RAG_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
THRESHOLD_PADRAO = float(os.getenv("RAG_THRESHOLD", "0.42"))
TOP_N_PADRAO = int(os.getenv("RAG_TOP_N", "5"))


class Embedder(Protocol):
    """Interface mínima para permitir trocar o provedor de embeddings."""

    def encode(self, textos: Sequence[str]) -> Sequence[Sequence[float]]:
        ...


class SentenceTransformerEmbedder:
    """Embedder local usando sentence-transformers.

    O import é tardio para que os testes do módulo não dependam do pacote nem
    façam download de modelo.
    """

    def __init__(self, model_name: str = MODELO_PADRAO):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Dependência ausente. Instale com: "
                "pip install sentence-transformers numpy"
            ) from exc

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def encode(self, textos: Sequence[str]) -> Sequence[Sequence[float]]:
        if not textos:
            return []

        return self.model.encode(
            list(textos),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )


@dataclass(frozen=True)
class ChunkArtigo:
    artigo_id: Any
    titulo: str
    chunk_id: int
    conteudo: str

    @property
    def texto_para_embedding(self) -> str:
        # Colocar o título junto do trecho ajuda a distinguir artigos parecidos,
        # por exemplo VPN Windows x VPN macOS.
        return f"Título: {self.titulo}\nConteúdo: {self.conteudo}"


@dataclass(frozen=True)
class ChunkIndexado:
    chunk: ChunkArtigo
    embedding: Sequence[float]


def remover_html(texto: Any) -> str:
    """Converte o HTML retornado pelo GLPI em texto simples."""
    if texto is None:
        return ""

    texto = str(texto)
    texto = re.sub(r"<\s*br\s*/?\s*>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(
        r"</\s*(p|li|h[1-6]|div|ol|ul|tr|td)\s*>",
        "\n",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)

    linhas = [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines()]
    return "\n".join(linha for linha in linhas if linha)


def _quebrar_sentencas(texto: str) -> list[str]:
    """Quebra o texto em unidades legíveis, preservando sentenças/parágrafos."""
    if not texto.strip():
        return []

    partes = re.split(r"(?<=[.!?])\s+|\n+", texto.strip())
    return [parte.strip() for parte in partes if parte.strip()]


def _partir_sentenca_longa(sentenca: str, tamanho: int, sobreposicao: int) -> list[str]:
    palavras = sentenca.split()
    if len(palavras) <= tamanho:
        return [sentenca]

    passo = max(1, tamanho - sobreposicao)
    return [
        " ".join(palavras[inicio : inicio + tamanho])
        for inicio in range(0, len(palavras), passo)
        if palavras[inicio : inicio + tamanho]
    ]


def criar_chunks_texto(
    texto: str,
    tamanho_max_palavras: int = 180,
    sobreposicao_palavras: int = 35,
) -> list[str]:
    """Divide texto em chunks por sentenças, com pequena sobreposição.

    O limite é em palavras para manter o comportamento previsível e evitar que
    um artigo grande domine o contexto. A sobreposição reduz perda de informação
    nas fronteiras dos chunks.
    """
    if tamanho_max_palavras <= 0:
        raise ValueError("tamanho_max_palavras deve ser maior que zero")
    if sobreposicao_palavras < 0:
        raise ValueError("sobreposicao_palavras não pode ser negativa")
    if sobreposicao_palavras >= tamanho_max_palavras:
        raise ValueError("sobreposicao_palavras deve ser menor que o tamanho do chunk")

    sentencas: list[str] = []
    for sentenca in _quebrar_sentencas(texto):
        sentencas.extend(
            _partir_sentenca_longa(
                sentenca,
                tamanho=tamanho_max_palavras,
                sobreposicao=sobreposicao_palavras,
            )
        )

    if not sentencas:
        return []

    chunks: list[str] = []
    atual: list[str] = []
    palavras_atual = 0

    for sentenca in sentencas:
        qtd = len(sentenca.split())

        if atual and palavras_atual + qtd > tamanho_max_palavras:
            chunk = " ".join(atual).strip()
            chunks.append(chunk)

            overlap = chunk.split()[-sobreposicao_palavras:] if sobreposicao_palavras else []
            atual = [" ".join(overlap)] if overlap else []
            palavras_atual = len(overlap)

        atual.append(sentenca)
        palavras_atual += qtd

    if atual:
        ultimo = " ".join(atual).strip()
        if ultimo and (not chunks or ultimo != chunks[-1]):
            chunks.append(ultimo)

    return chunks


def criar_chunks_artigos(
    artigos: Iterable[dict[str, Any]],
    tamanho_max_palavras: int = 180,
    sobreposicao_palavras: int = 35,
) -> list[ChunkArtigo]:
    """Transforma os artigos do GLPI em chunks rastreáveis até a fonte."""
    chunks: list[ChunkArtigo] = []

    for artigo in artigos or []:
        if not isinstance(artigo, dict):
            continue

        artigo_id = artigo.get("id")
        titulo = str(artigo.get("name") or "").strip()
        conteudo = remover_html(artigo.get("content", ""))

        # Não indexamos uma fonte que depois não possa ser citada corretamente.
        if artigo_id is None or not titulo or not conteudo:
            continue

        partes = criar_chunks_texto(
            conteudo,
            tamanho_max_palavras=tamanho_max_palavras,
            sobreposicao_palavras=sobreposicao_palavras,
        )

        for indice, parte in enumerate(partes):
            chunks.append(
                ChunkArtigo(
                    artigo_id=artigo_id,
                    titulo=titulo,
                    chunk_id=indice,
                    conteudo=parte,
                )
            )

    return chunks


def cosine_similarity(vetor_a: Sequence[float], vetor_b: Sequence[float]) -> float:
    """Cosine similarity sem exigir NumPy nos testes."""
    if len(vetor_a) != len(vetor_b):
        raise ValueError("Vetores com dimensões diferentes")
    if len(vetor_a) == 0:
        return 0.0

    produto = sum(float(a) * float(b) for a, b in zip(vetor_a, vetor_b))
    norma_a = math.sqrt(sum(float(a) ** 2 for a in vetor_a))
    norma_b = math.sqrt(sum(float(b) ** 2 for b in vetor_b))

    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0

    return produto / (norma_a * norma_b)


class RecuperadorArtigos:
    """Índice semântico reutilizável para várias perguntas.

    Os embeddings dos chunks são calculados uma única vez. A cada pergunta,
    somente o embedding da consulta é gerado.
    """

    def __init__(
        self,
        artigos: Iterable[dict[str, Any]],
        embedder: Embedder | None = None,
        tamanho_max_palavras: int = 180,
        sobreposicao_palavras: int = 35,
    ):
        self.embedder = embedder or SentenceTransformerEmbedder()
        self.chunks = criar_chunks_artigos(
            artigos,
            tamanho_max_palavras=tamanho_max_palavras,
            sobreposicao_palavras=sobreposicao_palavras,
        )

        textos = [chunk.texto_para_embedding for chunk in self.chunks]
        embeddings = self.embedder.encode(textos) if textos else []

        if len(embeddings) != len(self.chunks):
            raise RuntimeError(
                "O embedder retornou uma quantidade de vetores diferente da quantidade de chunks"
            )

        self.indice = [
            ChunkIndexado(chunk=chunk, embedding=embedding)
            for chunk, embedding in zip(self.chunks, embeddings)
        ]

    def buscar(
        self,
        pergunta: str,
        top_n: int = TOP_N_PADRAO,
        threshold: float = THRESHOLD_PADRAO,
        limite_por_artigo: int = 2,
        margem_ambiguidade: float = 0.04,
    ) -> dict[str, Any]:
        """Busca os chunks mais relevantes para uma pergunta.

        Retorno importante para a Sprint 1:
        - status == "ok": há contexto acima do threshold;
        - status == "sem_contexto": nenhum chunk passou do mínimo;
        - deve_recusar == True: o agente não deve chamar a geração como se
          houvesse evidência suficiente.
        """
        pergunta = str(pergunta or "").strip()

        if not pergunta:
            return self._sem_contexto(pergunta, threshold, "Pergunta vazia.")
        if top_n <= 0:
            raise ValueError("top_n deve ser maior que zero")
        if not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold deve ficar entre -1.0 e 1.0")
        if limite_por_artigo <= 0:
            raise ValueError("limite_por_artigo deve ser maior que zero")
        if margem_ambiguidade < 0:
            raise ValueError("margem_ambiguidade não pode ser negativa")
        if not self.indice:
            return self._sem_contexto(pergunta, threshold, "A base indexada está vazia.")

        embedding_pergunta_lista = self.embedder.encode([pergunta])
        if embedding_pergunta_lista is None or len(embedding_pergunta_lista) == 0:
            return self._sem_contexto(
                pergunta,
                threshold,
                "Não foi possível gerar embedding para a pergunta.",
            )

        embedding_pergunta = embedding_pergunta_lista[0]
        candidatos: list[tuple[float, ChunkArtigo]] = []

        for item in self.indice:
            similaridade = cosine_similarity(embedding_pergunta, item.embedding)
            if similaridade >= threshold:
                candidatos.append((similaridade, item.chunk))

        candidatos.sort(key=lambda item: item[0], reverse=True)

        # Evita que um artigo muito longo ocupe todo o top-N sozinho.
        selecionados: list[dict[str, Any]] = []
        contagem_por_artigo: dict[Any, int] = {}

        for similaridade, chunk in candidatos:
            usados = contagem_por_artigo.get(chunk.artigo_id, 0)
            if usados >= limite_por_artigo:
                continue

            selecionados.append(
                {
                    "artigo_id": chunk.artigo_id,
                    "titulo": chunk.titulo,
                    "chunk_id": chunk.chunk_id,
                    "conteudo": chunk.conteudo,
                    "similaridade": round(float(similaridade), 4),
                }
            )
            contagem_por_artigo[chunk.artigo_id] = usados + 1

            if len(selecionados) >= top_n:
                break

        if not selecionados:
            return self._sem_contexto(
                pergunta,
                threshold,
                (
                    "Nenhum artigo da base atingiu similaridade suficiente. "
                    "O agente deve admitir que não encontrou resposta na base."
                ),
            )

        # Se dois artigos diferentes aparecem praticamente empatados, expomos
        # isso para o agente não escolher uma fonte quase igual de forma aleatória.
        ambiguo = False
        if len(selecionados) >= 2:
            primeiro = selecionados[0]
            segundo = selecionados[1]
            ambiguo = (
                primeiro["artigo_id"] != segundo["artigo_id"]
                and abs(primeiro["similaridade"] - segundo["similaridade"])
                <= margem_ambiguidade
            )

        return {
            "status": "ok",
            "deve_recusar": False,
            "pergunta": pergunta,
            "threshold": threshold,
            "top_n": top_n,
            "ambiguo": ambiguo,
            "resultados": selecionados,
        }

    @staticmethod
    def _sem_contexto(pergunta: str, threshold: float, motivo: str) -> dict[str, Any]:
        return {
            "status": "sem_contexto",
            "deve_recusar": True,
            "pergunta": pergunta,
            "threshold": threshold,
            "ambiguo": False,
            "resultados": [],
            "mensagem": (
                "Não encontrei informação suficiente na base de conhecimento "
                "para responder com segurança."
            ),
            "motivo": motivo,
        }


def buscar_artigos_relevantes(
    pergunta: str,
    artigos: Iterable[dict[str, Any]],
    top_n: int = TOP_N_PADRAO,
    threshold: float = THRESHOLD_PADRAO,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Atalho para uma busca única.

    Para várias perguntas sobre a mesma base, prefira criar RecuperadorArtigos
    uma vez e reutilizar o objeto, evitando recalcular embeddings do corpus.
    """
    recuperador = RecuperadorArtigos(artigos=artigos, embedder=embedder)
    return recuperador.buscar(
        pergunta=pergunta,
        top_n=top_n,
        threshold=threshold,
    )


def _executar_cli() -> None:
    """Exemplo usando os artigos reais do GLPI do laboratório."""
    try:
        from coletar_dados import buscar_todos, obter_token
    except ImportError:
        from scripts.coletar_dados import buscar_todos, obter_token

    print("Carregando artigos do GLPI...")
    token = obter_token()
    artigos = buscar_todos("/api.php/v2/Knowledgebase/Article", token)

    print(f"Artigos carregados: {len(artigos)}")
    print(f"Modelo: {MODELO_PADRAO}")
    print(f"Threshold padrão: {THRESHOLD_PADRAO}")
    print("Indexando chunks...\n")

    recuperador = RecuperadorArtigos(artigos)
    print(f"Chunks indexados: {len(recuperador.chunks)}")
    print("Digite 'sair' para encerrar.\n")

    while True:
        pergunta = input("Pergunta: ").strip()
        if pergunta.lower() in {"sair", "exit", "quit"}:
            break

        resultado = recuperador.buscar(pergunta)

        if resultado["deve_recusar"]:
            print(f"\n{resultado['mensagem']}\n")
            continue

        print()
        for posicao, item in enumerate(resultado["resultados"], start=1):
            print(
                f"{posicao}. Artigo {item['artigo_id']} | "
                f"similaridade={item['similaridade']:.4f} | {item['titulo']}"
            )
            print(f"   chunk={item['chunk_id']} | {item['conteudo']}\n")

        if resultado["ambiguo"]:
            print(
                "Aviso: os melhores resultados estão muito próximos; "
                "o agente deve considerar pedir esclarecimento ao usuário.\n"
            )


if __name__ == "__main__":
    _executar_cli()
