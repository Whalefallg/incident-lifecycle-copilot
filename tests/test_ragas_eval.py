"""Pure retrieval metric tests. Live evaluation lives in test_live_rag_mcp.py."""
import pytest


def hit_rate_at_k(rows):
    return sum(bool(set(got) & set(expected)) for got, expected in rows) / len(rows) if rows else 0.0


def reciprocal_rank(got, expected):
    wanted = set(expected)
    return next((1 / rank for rank, doc_id in enumerate(got, 1) if doc_id in wanted), 0.0)


def recall_at_k(got, expected):
    return len(set(got) & set(expected)) / len(set(expected)) if expected else 0.0


@pytest.mark.retrieval
def test_retrieval_metrics():
    assert hit_rate_at_k([(["a", "b"], ["b"]), (["x"], ["y"])]) == 0.5
    assert reciprocal_rank(["x", "b"], ["b"]) == 0.5
    assert recall_at_k(["a", "b"], ["a", "b", "c"]) == pytest.approx(2 / 3)


@pytest.mark.retrieval
def test_empty_metric_inputs_are_explicit():
    assert hit_rate_at_k([]) == 0.0
    assert reciprocal_rank([], ["a"]) == 0.0
    assert recall_at_k(["a"], []) == 0.0
