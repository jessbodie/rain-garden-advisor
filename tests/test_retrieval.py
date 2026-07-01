"""Tests for the RAG retrieval layer (rain_garden.retrieval). No network.

The ONNX embedding model and the index (.npy + .jsonl) are shipped as package
data, so these run fully offline. Gold (query -> expected source_doc) assertions
are intentionally ABSENT here: that oracle is derived independently by Chat after
the corpus freeze and lives in a separate eval (spec section 8).
"""

import numpy as np

from rain_garden.retrieval import (
    EMBED_DIM,
    Embedder,
    OnnxEmbedder,
    cosine_top_k,
    l2_normalize,
    load_index,
    search,
)


# --- primitives (embedder-agnostic) ------------------------------------------

def test_l2_normalize_unit_rows_and_zero_safe():
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 0.0]]))
    assert np.allclose(np.linalg.norm(out[0]), 1.0)
    assert np.allclose(out[1], [0.0, 0.0])   # zero row stays zero, not NaN
    assert np.allclose(out[2], [1.0, 0.0])
    assert not np.isnan(out).any()
    assert out.dtype == np.float32


def test_cosine_top_k_orders_and_clamps():
    mat = l2_normalize(np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]))
    q = l2_normalize(np.array([[0.0, 1.0]]))[0]
    res = cosine_top_k(q, mat, 2)
    assert [i for i, _ in res] == [2, 1]          # descending by score
    assert res[0][1] >= res[1][1]
    assert len(cosine_top_k(q, mat, 99)) == 3     # k clamps to n_rows
    assert cosine_top_k(q, mat, 0) == []
    assert cosine_top_k(q, np.empty((0, 2)), 3) == []


def test_dummy_embedder_satisfies_protocol():
    class Dummy:
        dim = 2

        def embed(self, texts):
            return l2_normalize(np.ones((len(texts), 2)))

    assert isinstance(Dummy(), Embedder)


# --- concrete OnnxEmbedder (choice A) ----------------------------------------

def test_onnx_embedder_shape_dtype_and_normalized():
    emb = OnnxEmbedder()
    vecs = emb.embed(["clay soil amendment", "build a berm on the downhill side"])
    assert vecs.shape == (2, EMBED_DIM)
    assert vecs.dtype == np.float32
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-4)
    assert emb.embed([]).shape == (0, EMBED_DIM)   # empty batch is safe


# --- shipped index integrity + search ----------------------------------------

def test_shipped_index_row_aligned_and_unit_norm():
    embeddings, chunks = load_index()
    assert embeddings.shape[0] == len(chunks)      # row alignment invariant
    assert embeddings.shape[1] == EMBED_DIM
    assert np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-3)
    required = {"text", "source_doc", "source_url", "citation_label", "id"}
    for chunk in chunks:
        assert required.issubset(chunk)


def test_search_returns_ranked_cited_passages_deterministically():
    res = search("clay soil amendment drainage before planting", k=3)
    assert 1 <= len(res) <= 3
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)
    fields = {"text", "source_doc", "source_url", "citation_label", "page", "score"}
    for passage in res:
        assert set(passage) == fields
    # deterministic given query + shipped index
    assert search("clay soil amendment drainage before planting", k=3) == res


def test_search_accepts_injected_embedder():
    res = search("mulch and maintenance", k=2, embedder=OnnxEmbedder())
    assert len(res) <= 2
