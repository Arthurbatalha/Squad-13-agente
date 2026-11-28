"""Testes unitários da busca de artigos, sem carregar o MiniLM real."""

import pytest

from scripts.avaliar_recuperacao_rag02 import (
    DEFAULT_CASES,
    DEFAULT_THRESHOLDS,
    _load_cases,
    _metrics,
    _recommend_threshold,
)
from src.rag.artigos_teste import artigos
from src.rag.busca_artigos import buscar_artigos
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService
from test.embedding_fakes import ModelSpy, unit


@pytest.fixture
def search():
    def vector(text):
        key = text.casefold()
        index = 0 if "windows" in key else 1 if "macos" in key else 3 if "cafeteira" in key else 2
        return unit(index)

    return CorpusService(EmbeddingService(model=ModelSpy(vector)))


def test_vpn_windows_retrieves_windows_article(search):
    results = buscar_artigos(
        "Como configurar a VPN no Windows?",
        artigos,
        service=search,
    )

    assert results
    assert results[0]["id"] == 1
    assert results[0]["title"] == "Configurar a VPN corporativa no Windows"
    assert results[0]["content"]


def test_vpn_macos_retrieves_macos_article(search):
    results = buscar_artigos(
        "Como configurar a VPN no macOS?",
        artigos,
        service=search,
    )

    assert results
    assert results[0]["id"] == 2
    assert results[0]["title"] == "Configurar a VPN corporativa no macOS"
    assert results[0]["content"]


def test_question_without_matching_article_returns_no_results(search):
    results = buscar_artigos(
        "Como configurar uma cafeteira?",
        artigos,
        service=search,
    )

    assert results == []


def test_evaluation_dataset_covers_required_references_and_splits():
    clarification, retrieval = _load_cases(DEFAULT_CASES)

    assert {case["reference"] for case in clarification} == {5, 6, 7}
    assert {case["reference"] for case in retrieval} == {1, 2, 3, 4, 5, 6, 7, 17, 18, 19, 20}
    assert {case["split"] for case in retrieval} == {"calibration", "holdout"}
    assert all(case["expected_source_titles"] == [] for case in retrieval if case["reference"] >= 17)


def test_evaluation_metrics_count_hits_and_false_evidence_separately():
    details = [
        {"expected_source_titles": ["VPN Windows"], "hit": True, "false_evidence": False},
        {"expected_source_titles": ["VPN macOS"], "hit": False, "false_evidence": False},
        {"expected_source_titles": [], "hit": None, "false_evidence": False},
        {"expected_source_titles": [], "hit": None, "false_evidence": True},
    ]

    assert _metrics(details) == {
        "answerable_hit_at_4": 0.5,
        "answerable_hits": 1,
        "answerable_count": 2,
        "no_evidence_false_positive_rate": 0.5,
        "no_evidence_false_positives": 1,
        "no_evidence_count": 2,
    }


def test_calibration_threshold_requires_zero_false_evidence_and_some_recall():
    sweep = [
        {"threshold": 0.35, "answerable_hits": 9, "no_evidence_false_positives": 1},
        {"threshold": 0.45, "answerable_hits": 7, "no_evidence_false_positives": 0},
        {"threshold": 0.50, "answerable_hits": 7, "no_evidence_false_positives": 0},
        {"threshold": 0.75, "answerable_hits": 0, "no_evidence_false_positives": 0},
    ]

    assert _recommend_threshold(sweep) == 0.50
    assert _recommend_threshold([sweep[0], sweep[-1]]) is None


def test_default_threshold_sweep_has_one_percent_resolution():
    assert len(DEFAULT_THRESHOLDS) == 61
    assert DEFAULT_THRESHOLDS[0] == 0.20
    assert DEFAULT_THRESHOLDS[-1] == 0.80
    assert all(round(right - left, 2) == 0.01
               for left, right in zip(DEFAULT_THRESHOLDS, DEFAULT_THRESHOLDS[1:]))
