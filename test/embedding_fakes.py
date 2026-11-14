"""Modelo espião sintético: nunca importa SentenceTransformers nem usa rede."""

import numpy as np

from src.rag.chunk_contract import PREPARATION_VERSION


class TokenizerSpy:
    model_max_length = 512

    def encode(self, text, *, add_special_tokens=True, truncation=False):
        assert add_special_tokens is True and truncation is False
        return list(range(len(text.split()) + 2))


def unit(index=0):
    vector = np.zeros(384, dtype=np.float32)
    vector[index] = 1
    return vector


class ModelSpy:
    max_seq_length = 128

    def __init__(self, vector_for_text=None):
        self.tokenizer = TokenizerSpy()
        self.calls = []
        self.fail_on = None
        self.transform = lambda array: array
        self.vector_for_text = vector_for_text or (lambda text: unit(1 if "FONTE_B" in text else 0))

    def get_sentence_embedding_dimension(self):
        return 384

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        if len(self.calls) == self.fail_on:
            raise OSError("Falha sintética em um lote.")
        return self.transform(np.stack([self.vector_for_text(text) for text in texts]))


def chunk(index=0, content="FONTE_A", *, source_type="article", source_id=17):
    return {"source_type": source_type, "source_id": source_id,
            "source_reference": "/Knowledgebase/Article" if source_type == "article" else "/Assistance/Ticket",
            "title": "Mesmo título sintético", "content": content,
            "chunk_id": f"{PREPARATION_VERSION}:{source_type}:{source_id}:{index:04d}",
            "preparation_version": PREPARATION_VERSION}


def articles():
    return [{"id": 17, "title": "Mesmo título sintético", "content": "<p>FONTE_A</p>"},
            {"id": 29, "title": "Mesmo título sintético", "content": "<p>FONTE_B</p>"}]
