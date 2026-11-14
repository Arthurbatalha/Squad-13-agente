"""Integração ING-02 em CPU. Pesos reais, fixtures sintéticas e GLPI opcional.

python -m scripts.verificar_embeddings --batch-size 2 --glpi --output /tmp/ing02.json
Sem --download, usa exclusivamente a revisão fixa já presente no cache.
"""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
import psutil

from src.rag.busca_artigos import buscar_artigos
from src.rag.chunk_contract import MINILM_MODEL, MINILM_REVISION
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService, TokenLimitError, validate_vectors


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ["O que conferir quando aparece o erro VPN-FIX-691?",
             "Como reconectar o cliente VPN após o erro VPN-FIX-809?"]


def synthetic_sources():
    directory = ROOT / "test" / "fixtures" / "ing01"
    result = []
    for record in json.loads((directory / "sources.json").read_text(encoding="utf-8")):
        assert record["fixture"] is True
        result.append((record["source_type"], {
            "id": record["id"], "title": record["title"],
            "content": (directory / record["html_file"]).read_text(encoding="utf-8"),
            "source_reference": record["source_reference"],
        }))
    # Fixture sintética longa derivada do artigo; não vem do laboratório.
    result.append(("article", {**result[0][1], "id": 93003, "content": result[0][1]["content"] * 6}))
    return result


def cpu_name():
    if Path("/proc/cpuinfo").exists():
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def query_twice(search, corpus, questions):
    before = search.encoder.stats
    original_vectors = corpus.vectors.tobytes()
    queries = []
    for question in questions:
        started = perf_counter()
        hits = buscar_artigos(question, corpus, service=search)
        duration = perf_counter() - started
        queries.append({"question": question, "seconds": duration,
                        "tokens": search.encoder.token_count(question),
                        "hits": [{key: hit[key] for key in ("id", "source_type", "chunk_id", "score")} for hit in hits]})
        assert search.encoder.stats["document_texts"] == before["document_texts"]
    after = search.encoder.stats
    assert after["question_texts"] - before["question_texts"] == len(questions)
    assert original_vectors == corpus.vectors.tobytes()
    return {"queries": queries, "stats_before_queries": before, "stats_after_queries": after,
            "document_vectors_reused": True}


def run(args):
    # Definido antes de importar/carregar torch. Não altera configuração de outros processos.
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["MKL_NUM_THREADS"] = str(args.threads)
    from huggingface_hub import snapshot_download

    report = {"utc": datetime.now(timezone.utc).isoformat(), "system": platform.platform(),
              "python": platform.python_version(), "cpu": cpu_name(), "logical_cpus": os.cpu_count(),
              "threads": args.threads, "batch_size": args.batch_size, "device": "cpu",
              "versions": {name: version(name) for name in (
                  "sentence-transformers", "torch", "transformers", "tokenizers", "numpy",
                  "psutil", "html2text", "huggingface-hub", "scikit-learn")}}
    started = perf_counter()
    snapshot = snapshot_download(
        MINILM_MODEL, revision=MINILM_REVISION, cache_dir=args.cache_dir,
        local_files_only=not args.download,
        allow_patterns=["*.json", "*.safetensors", "tokenizer.*", "*.model", "README.md"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    elapsed = perf_counter() - started
    assert Path(snapshot).name == MINILM_REVISION
    report["weights"] = {"revision": MINILM_REVISION, "snapshot": snapshot,
                         "mode": "download_or_cache_check" if args.download else "local_cache_only",
                         "download_seconds": elapsed if args.download else None,
                         "cache_lookup_seconds": elapsed if not args.download else None,
                         "note": "Sem --download não há transferência de pesos; a carga é medida separadamente."}
    process = psutil.Process()
    memory = {"before_load_mib": process.memory_info().rss / 1024**2}
    encoder = EmbeddingService(batch_size=args.batch_size, local_files_only=True, cache_dir=args.cache_dir)
    started = perf_counter()
    encoder.load()
    report["load_seconds"] = perf_counter() - started
    memory["after_load_mib"] = process.memory_info().rss / 1024**2
    report["runtime"] = encoder.runtime_info()
    assert report["runtime"]["max_seq_length"] == 128 and report["runtime"]["dimension"] == 384
    assert Path(report["runtime"]["weights_and_tokenizer_snapshot"]).resolve() == Path(snapshot).resolve()
    started = perf_counter()
    sources = synthetic_sources()
    chunks = [chunk for kind, source in sources for chunk in encoder.prepare_source(source, source_type=kind)]
    preparation_seconds = perf_counter() - started
    search = CorpusService(encoder)
    started = perf_counter()
    corpus = search.prepare_chunks(chunks)
    encode_seconds = perf_counter() - started
    memory["after_corpus_mib"] = process.memory_info().rss / 1024**2
    validate_vectors(corpus.vectors, len(chunks))
    counts = [encoder.token_count(chunk["content"]) for chunk in corpus.chunks]
    assert max(counts) <= 128
    fixture = {"synthetic_fixture": True, "sources": len(sources), "chunks": len(chunks),
               "preparation_seconds": preparation_seconds, "corpus_encoding_seconds": encode_seconds,
               "chunk_tokens": counts, "vectors_bytes": corpus.vectors.nbytes,
               "metadata": corpus.metadata.to_dict(), "vectors_finite": bool(np.isfinite(corpus.vectors).all()),
               "norm_min": float(np.linalg.norm(corpus.vectors, axis=1).min()),
               "norm_max": float(np.linalg.norm(corpus.vectors, axis=1).max())}
    fixture.update(query_twice(search, corpus, QUESTIONS))
    oversized = "configuração de autenticação multifator " * 80
    before_rejection = encoder.stats
    for encode in (lambda: encoder.encode_question(oversized),
                   lambda: encoder.encode_chunks([{**chunks[0], "content": oversized}])):
        try:
            encode()
        except TokenLimitError:
            pass
        else:
            raise AssertionError("O encoder aceitou texto acima do limite.")
    assert encoder.stats == before_rejection
    fixture["oversized_input"] = {"tokens": encoder.token_count(oversized),
                                  "question_rejected": True, "document_rejected": True,
                                  "encoder_calls_unchanged": True}
    report["fixture"] = fixture
    memory["after_fixture_queries_mib"] = process.memory_info().rss / 1024**2
    if args.glpi:
        try:
            from scripts.coletar_dados import create_client
            from src.rag.article_source import source_treatment
            started = perf_counter()
            articles = source_treatment(create_client())  # autenticação + leitura, sem escrita GLPI
            collect_seconds = perf_counter() - started
        except Exception as exc:
            # Exceções HTTP podem conter URLs/credenciais; não imprimir valores internos.
            report["glpi"] = {"executed": False, "error_type": type(exc).__name__,
                              "attempt_seconds": perf_counter() - started,
                              "reason": "Configuração/autenticação/conexão GLPI indisponível para leitura."}
        else:
            started = perf_counter()
            real_corpus = search.prepare_articles(articles)
            preparation_and_encoding = perf_counter() - started
            counts = [encoder.token_count(chunk["content"]) for chunk in real_corpus.chunks]
            assert not counts or max(counts) <= 128
            glpi = {"executed": True, "read_only": True, "sources": len(articles),
                    "chunks": len(real_corpus.chunks), "collection_seconds": collect_seconds,
                    "preparation_and_encoding_seconds": preparation_and_encoding,
                    "max_chunk_tokens": max(counts, default=0)}
            if real_corpus.chunks:
                glpi.update(query_twice(search, real_corpus, ["Como configurar a VPN no Windows?", "Como instalar uma impressora de rede?"]))
            report["glpi"] = glpi
    else:
        report["glpi"] = {"executed": False, "reason": "Use --glpi para tentar leitura pelo cliente comum."}
    memory["final_mib"] = process.memory_info().rss / 1024**2
    report["memory"] = {"metric": "RSS instantâneo do processo via psutil; inclui bibliotecas, pesos e runtime; não é pico nem memória exclusiva dos vetores.", **memory}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("O valor deve ser positivo.")
    return number


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--batch-size", type=positive, default=2)
    parser.add_argument("--threads", type=positive, default=2)
    parser.add_argument("--glpi", action="store_true")
    parser.add_argument("--output", type=Path)
    run(parser.parse_args())
