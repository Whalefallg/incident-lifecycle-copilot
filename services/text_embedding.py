"""
Text embedding utilities for runbook and incident memory RAG.

Provides semantic similarity search for knowledge documents.
"""

import numpy as np
import faiss
from config.model_provider import create_embedding_model


def find_best_match_indices(text: str, candidates: list) -> list:
    """
    Find best matching candidates using embedding similarity.

    Args:
        text: Query text
        candidates: List of candidate texts

    Returns:
        List of indices sorted by similarity (highest first)
    """
    if not candidates:
        return []
    candidate_embs = [embed_input(c) for c in candidates]
    candidate_embs = np.array(candidate_embs).astype("float32")
    dimension = candidate_embs.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(candidate_embs)
    text_emb = np.array([embed_input(text)]).astype("float32")
    k = len(candidates)
    _, indices = index.search(text_emb, k)
    return indices[0][:k].tolist()


def embed_input(input_text: str, model: str = "text-embedding-ada-002",
                encoding_format: str = "float", dimensions: int = None,
                timeout: int = 600) -> list:
    """Generate embedding vector for input text."""
    embeddings = create_embedding_model()
    return embeddings.embed_query(input_text)
