"""MiniLM real + índice reaberto. Publicação é uma fase separada da leitura.

python -m scripts.verificar_recuperacao --output /tmp/rag03-fixtures.json
python -m scripts.verificar_recuperacao --glpi --output /tmp/rag03-glpi.json
python -m scripts.verificar_recuperacao --index-dir data/index --output /tmp/rag03-publicado.json

Sem --index-dir, publica apenas em diretório temporário (fixtures por padrão;
--glpi coleta artigos reais em leitura e usa o coordenador ING-05). Com
--index-dir, não publica nem sincroniza: consulta o índice existente.
Sem --download, exige os pesos no cache. Não chama Gemini.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import psutil

from src.authorization.policies import Principal
from src.authorization.service import AuthorizationService
from src.rag.busca_artigos import recuperar_trechos
from src.rag.chunk_contract import MINILM_MODEL, MINILM_REVISION
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService, validate_vectors
from src.rag.local_index import LocalIndexStore
from src.rag.retrieval import RetrievalConfig, build_published_retrieval
from src.rag.sync_runtime import (
    ArticleSyncCoordinator, LocalArticleSyncEngine, SyncRunLedger,
    make_glpi_article_collector,
)
from scripts.verificar_embeddings import cpu_name, synthetic_sources


def run(args):
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["MKL_NUM_THREADS"] = str(args.threads)
    from huggingface_hub import snapshot_download

    report = {"utc": datetime.now(timezone.utc).isoformat(), "system": platform.platform(),
              "python": platform.python_version(), "cpu": cpu_name(),
              "logical_cpus": os.cpu_count(), "threads": args.threads,
              "batch_size": args.batch_size, "model": MINILM_MODEL, "revision": MINILM_REVISION,
              "device": "cpu", "encoder": "real_minilm", "versions": {
                  name: version(name) for name in ("sentence-transformers", "torch", "transformers",
                                                  "tokenizers", "numpy", "psutil", "huggingface-hub")}}
    started = perf_counter()
    snapshot = snapshot_download(
        MINILM_MODEL, revision=MINILM_REVISION, local_files_only=not args.download,
        allow_patterns=["*.json", "*.safetensors", "tokenizer.*", "*.model", "README.md"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    report["weights"] = {"mode": "download_or_cache" if args.download else "local_cache_only",
                         "lookup_seconds": perf_counter() - started,
                         "download_performed": "not_separately_measured" if args.download else False}
    assert Path(snapshot).name == MINILM_REVISION
    process = psutil.Process()
    rss = lambda: round(process.memory_info().rss / 1024**2, 3)
    report["memory"] = {"metric": "process RSS MiB; amostras, não pico nem só pesos", "before_load": rss()}
    encoder = EmbeddingService(batch_size=args.batch_size, local_files_only=True)
    started = perf_counter()
    encoder.load()
    report["load_seconds"] = perf_counter() - started
    report["memory"]["after_load"] = rss()
    report["embedding_config"] = asdict(encoder.config)
    report["runtime"] = encoder.runtime_info()
    assert Path(report["runtime"]["weights_and_tokenizer_snapshot"]).resolve() == Path(snapshot).resolve()

    with TemporaryDirectory(prefix="rag03-") as temporary:
        root = Path(args.index_dir) if args.index_dir else Path(temporary) / "index"
        started = perf_counter()
        if args.index_dir:
            report["data_origin"] = "existing_published_index_not_recollected"
            report["publication"] = None
        elif args.glpi:
            report["data_origin"] = "GLPI laboratory articles, read-only HTTP"
            writer = LocalIndexStore(root, "article", embedding=encoder.config)
            engine = LocalArticleSyncEngine(store=writer, collect_fn=make_glpi_article_collector(), encoder=encoder)
            coordinator = ArticleSyncCoordinator(engine, SyncRunLedger(root.parent / "article_sync_runs.sqlite3"))
            run_result = coordinator.run("manual")
            report["publication"] = {"status": run_result.status, "generation": run_result.active_generation,
                                     "sources": run_result.sources_total, "chunks": run_result.chunks_total,
                                     "error": run_result.error_code, "scope": "temporary_local_index"}
            if run_result.status == "failed":
                report["validation"] = "blocked_glpi_publication"
                return report
        else:
            report["data_origin"] = "synthetic ING-01 article fixtures; not laboratory data"
            sources = [(kind, source) for kind, source in synthetic_sources() if kind == "article"]
            corpus = CorpusService(encoder).prepare_sources(sources)
            writer = LocalIndexStore(root, "article", embedding=encoder.config)
            info = writer.create_candidate(corpus)
            writer.activate(info.generation_id)
            report["publication"] = {"status": "published", "generation": info.generation_id,
                                     "sources": info.source_count, "chunks": info.chunk_count,
                                     "scope": "temporary_local_index"}
        report["publication_seconds"] = perf_counter() - started
        report["memory"]["after_publication"] = rss()

        # Nova instância de store: todos os dados da leitura vêm do disco.
        reopened = LocalIndexStore(root, "article", embedding=encoder.config)
        with reopened.open_active() as active:
            validate_vectors(active.corpus.vectors, len(active.corpus.chunks))
            token_counts = [encoder.token_count(c["content"]) for c in active.corpus.chunks]
            assert not token_counts or max(token_counts) <= encoder.config.max_tokens
            report["index"] = {"generation": active.generation_id,
                               "generation_created_at": active.info.created_at,
                               "sources": active.info.source_count, "chunks": active.info.chunk_count,
                               "max_chunk_tokens": max(token_counts, default=0),
                               "shape": list(active.corpus.vectors.shape), "reopened": True,
                               "finite": bool(np.isfinite(active.corpus.vectors).all()),
                               "norm_min": float(np.linalg.norm(active.corpus.vectors, axis=1).min()) if token_counts else None,
                               "norm_max": float(np.linalg.norm(active.corpus.vectors, axis=1).max()) if token_counts else None}

        # Não há acesso ao GLPI no leitor de artigos nem código de escrita:
        # qualquer tentativa de preparar/encode de documentos encerra o ensaio.
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Tentativa de preparar/vetorizar documentos durante recuperação.")

        encoder.prepare_source = forbidden
        encoder.encode_chunks = forbidden
        retrieval = build_published_retrieval(AuthorizationService(None), encoder=encoder, index_dir=root,
                                               config=RetrievalConfig(min_similarity=args.min_similarity))
        questions = (args.question or (["Como configurar a VPN no Windows?", "Como instalar uma impressora?"]
                                      if args.glpi or args.index_dir else
                                      ["O que conferir no erro VPN-FIX-691?", "Como abrir o cliente VPN?"]))
        if len(questions) != 2:
            raise ValueError("Forneça exatamente duas perguntas usando --question duas vezes.")
        before = encoder.stats
        report["queries"] = []
        for question in questions:
            started = perf_counter()
            result = recuperar_trechos(question, Principal.staff(13), retriever=retrieval)
            elapsed = perf_counter() - started
            assert result["context_tokens"] <= retrieval.config.context_max_tokens
            report["queries"].append({"question": question, "seconds": elapsed,
                                      "question_tokens": encoder.token_count(question),
                                      "status": result["status"], "reason": result["reason"],
                                      "collections": result["collections"],
                                      "context_tokens": result["context_tokens"], "hits": [
                                          {key: c[key] for key in ("chunk_id", "source_type", "source_id",
                                                                   "source_reference", "generation", "score", "metric")}
                                          for c in result["chunks"]]})
            assert encoder.stats["document_texts"] == before["document_texts"]
        after = encoder.stats
        assert after["question_texts"] - before["question_texts"] == 2
        report["stats_before_read"] = before
        report["stats_after_read"] = after
        report["reading_document_encodes"] = after["document_texts"] - before["document_texts"]
        report["reading_question_encodes"] = after["question_texts"] - before["question_texts"]
        report["memory"]["after_queries"] = rss()
        report["validation"] = "passed"
        report["threshold_provisional"] = True
        report["min_similarity"] = args.min_similarity
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glpi", action="store_true")
    parser.add_argument("--index-dir", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--min-similarity", type=float, default=0.45)
    parser.add_argument("--question", action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.glpi and args.index_dir:
        parser.error("--glpi prepara índice temporário; --index-dir apenas lê um índice existente.")
    if args.threads <= 0 or args.batch_size <= 0:
        parser.error("threads e batch-size devem ser positivos.")
    report = run(args)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["validation"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
