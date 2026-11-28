#!/usr/bin/env python3
"""Avaliação opt-in da busca publicada de artigos (MiniLM local, sem Gemini)."""

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CASES = ROOT / "tests" / "data" / "article_retrieval_cases.json"
DEFAULT_THRESHOLDS = tuple(round(value / 100, 2) for value in range(20, 81))


def _parse_thresholds(value: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use números separados por vírgula") from exc
    if not values or any(not -1 <= item <= 1 for item in values):
        raise argparse.ArgumentTypeError("cada limiar deve estar entre -1 e 1")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("os limiares não podem se repetir")
    return tuple(sorted(values))


def _load_cases(path: Path) -> tuple[list[dict], list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    clarification = payload.get("clarification_cases")
    retrieval = payload.get("retrieval_cases")
    if not isinstance(clarification, list) or not isinstance(retrieval, list) or not retrieval:
        raise ValueError("arquivo deve conter clarification_cases e retrieval_cases não vazios")
    identifiers = set()
    for case in retrieval:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not case["id"] or case["id"] in identifiers
                or case.get("split") not in {"calibration", "holdout"}
                or not isinstance(case.get("query"), str) or not case["query"].strip()
                or not isinstance(case.get("expected_source_titles"), list)
                or not all(isinstance(title, str) and title.strip()
                           for title in case["expected_source_titles"])
                or type(case.get("reference")) is not int):
            raise ValueError("caso de recuperação inválido ou duplicado")
        identifiers.add(case["id"])
    if any(case["split"] == "calibration" for case in retrieval) is False:
        raise ValueError("é necessário ao menos um caso de calibração")
    if any(not case["expected_source_titles"] for case in retrieval if case["split"] == "calibration") is False:
        raise ValueError("a calibração precisa incluir casos rotulados sem evidência")
    for case in clarification:
        if (not isinstance(case, dict) or type(case.get("reference")) is not int
                or case.get("action") != "clarify_without_retrieval"
                or not isinstance(case.get("query"), str) or not case["query"].strip()):
            raise ValueError("caso de esclarecimento inválido")
    return clarification, retrieval


def _evaluate_cases(reader, principal, cases: Sequence[dict], expected_generation: str | None):
    observed_generation = expected_generation
    details = []
    for case in cases:
        started = perf_counter()
        result = reader.retrieve(case["query"], principal)
        elapsed_ms = (perf_counter() - started) * 1000
        article_state = result.get("collections", {}).get("article", {})
        generation = article_state.get("generation")
        if result.get("status") == "index_unavailable" or not generation:
            raise RuntimeError("recuperação real indisponível; confira ACTIVE e a geração do índice article")
        if observed_generation is None:
            observed_generation = generation
        elif generation != observed_generation:
            raise RuntimeError("a geração do índice mudou durante a avaliação; repita sem sincronização concorrente")

        expected = set(case["expected_source_titles"])
        scores = {}
        source_ids = {}
        for chunk in result.get("chunks", []):
            title = chunk["title"]
            scores[title] = max(scores.get(title, -1.0), float(chunk["score"]))
            source_ids[title] = chunk["source_id"]
        actual = set(scores)
        details.append({
            "id": case["id"],
            "reference": case["reference"],
            "split": case["split"],
            "status": result["status"],
            "expected_source_titles": sorted(expected),
            "retrieved_source_titles": sorted(actual),
            "retrieved_source_ids": {title: source_ids[title] for title in sorted(source_ids)},
            "scores_by_title": {title: scores[title] for title in sorted(scores)},
            "hit": bool(expected & actual) if expected else None,
            "false_evidence": not expected and result["status"] == "evidence",
            "latency_ms": round(elapsed_ms, 3),
        })
    return observed_generation, details


def _metrics(details: Sequence[dict]) -> dict:
    answerable = [row for row in details if row["expected_source_titles"]]
    no_evidence = [row for row in details if not row["expected_source_titles"]]
    hits = sum(row["hit"] for row in answerable)
    false_positives = sum(row["false_evidence"] for row in no_evidence)
    return {
        "answerable_hit_at_4": hits / len(answerable) if answerable else None,
        "answerable_hits": hits,
        "answerable_count": len(answerable),
        "no_evidence_false_positive_rate": false_positives / len(no_evidence) if no_evidence else None,
        "no_evidence_false_positives": false_positives,
        "no_evidence_count": len(no_evidence),
    }


def _recommend_threshold(sweep: Sequence[dict]) -> float | None:
    """Escolhe maior recall sem falsas evidências; empate favorece maior corte."""
    eligible = [row for row in sweep
                if row["no_evidence_false_positives"] == 0 and row["answerable_hits"] > 0]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (row["answerable_hits"], row["threshold"]))["threshold"]


def run(index_dir: Path, cases_path: Path, thresholds: Sequence[float]) -> dict:
    # Imports aqui mantêm coleta/testes unitários sem inicializar o encoder real.
    from src.authorization.policies import Principal
    from src.authorization.service import AuthorizationService
    from src.rag.embeddings import EmbeddingService
    from src.rag.local_index import LocalIndexStore
    from src.rag.retrieval import PublishedRetrieval, RetrievalConfig

    clarification_cases, retrieval_cases = _load_cases(cases_path)
    class QuestionCacheEncoder(EmbeddingService):
        """Evita repetir a mesma inferência ao varrer os limiares."""

        def __init__(self):
            super().__init__(local_files_only=True)
            self._question_cache = {}

        def encode_question(self, question):
            if question not in self._question_cache:
                self._question_cache[question] = super().encode_question(question)
            return self._question_cache[question]

    encoder = QuestionCacheEncoder()
    store = LocalIndexStore(index_dir, "article", embedding=encoder.config)
    try:
        with store.open_active() as active:
            active_generation = active.generation_id
            available_titles = {chunk["title"] for chunk in active.corpus.chunks}
    except Exception as exc:
        raise RuntimeError(f"índice article não publicado ou inválido em {store.directory}") from exc
    expected_titles = {
        title for case in retrieval_cases for title in case["expected_source_titles"]
    }
    missing_titles = sorted(expected_titles - available_titles)
    if missing_titles:
        raise RuntimeError(
            "os títulos rotulados não existem na geração ativa; revise os rótulos/corpus: "
            + "; ".join(missing_titles)
        )

    principal = Principal.staff(13)
    calibration_cases = [row for row in retrieval_cases if row["split"] == "calibration"]
    holdout_cases = [row for row in retrieval_cases if row["split"] == "holdout"]
    sweep = []
    details_at_threshold = {}
    for threshold in thresholds:
        reader = PublishedRetrieval(
            {"article": store}, authorization=AuthorizationService(None), encoder=encoder,
            config=RetrievalConfig(min_similarity=threshold),
        )
        generation, details = _evaluate_cases(reader, principal, calibration_cases, active_generation)
        active_generation = generation
        metrics = _metrics(details)
        row = {"threshold": threshold, **metrics}
        sweep.append(row)
        details_at_threshold[threshold] = details

    recommended_threshold = _recommend_threshold(sweep)
    holdout_sweep = []
    holdout_details_by_threshold = {}
    if holdout_cases:
        for threshold in thresholds:
            reader = PublishedRetrieval(
                {"article": store}, authorization=AuthorizationService(None), encoder=encoder,
                config=RetrievalConfig(min_similarity=threshold),
            )
            generation, details = _evaluate_cases(reader, principal, holdout_cases, active_generation)
            active_generation = generation
            holdout_sweep.append({"threshold": threshold, **_metrics(details)})
            holdout_details_by_threshold[threshold] = details

    holdout_metrics = None
    holdout_details = None
    if recommended_threshold is not None and holdout_cases:
        holdout_metrics = next(
            row for row in holdout_sweep if row["threshold"] == recommended_threshold
        )
        holdout_details = holdout_details_by_threshold[recommended_threshold]

    return {
        "evaluation": "RAG-02 article retrieval; no Gemini call",
        "model": {
            "name": encoder.config.model,
            "revision": encoder.config.revision,
            "dimension": encoder.config.dimension,
            "device": encoder.config.device,
            "weights_policy": "local_files_only; no download",
        },
        "metric": "cosine_similarity",
        "higher_is_more_similar": True,
        "index_generation": active_generation,
        "index_dir": str(index_dir),
        "clarification_cases_excluded_from_ranking": len(clarification_cases),
        "calibration_sweep": sweep,
        "holdout_sweep": holdout_sweep,
        "recommended_threshold": recommended_threshold,
        "recommendation_rule": "maximizar hits respondíveis com zero falsas evidências; empate favorece o maior corte",
        "calibration_details_at_recommended_threshold": details_at_threshold.get(recommended_threshold),
        "holdout_metrics": holdout_metrics,
        "holdout_details": holdout_details,
        "note": (
            "A recomendação usa somente calibration; holdout é reportado sem ajuste. "
            "A amostra é pequena e exploratória, não substitui revisão das fontes rotuladas."
        ),
    }


def main(argv=None) -> int:
    from src.config import INDEX_DIR

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR,
                        help="raiz do LocalIndexStore (padrão: data/index)")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES,
                        help="JSON rotulado da avaliação")
    parser.add_argument("--thresholds", type=_parse_thresholds,
                        default=DEFAULT_THRESHOLDS,
                        help="limiares para varredura, separados por vírgula (padrão: 0.20 a 0.80, passo 0.01)")
    parser.add_argument("--output", type=Path,
                        help="grava o resultado JSON neste caminho; sem opção, imprime no terminal")
    args = parser.parse_args(argv)
    try:
        report = run(args.index_dir, args.cases, args.thresholds)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"RAG-02: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
