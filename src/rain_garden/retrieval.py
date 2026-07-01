"""Retrieval for the search_guidance RAG layer.

Structured as a provider-independent seam plus a concrete implementation. The
seam is the :class:`Embedder` interface and the brute-force cosine-similarity
primitives (:func:`l2_normalize`, :func:`cosine_top_k`); introducing it first
meant the HALT 1 footprint pause blocked only the concrete embedder, not the
surrounding wiring. HALT 1 resolved to choice A, so the concrete
:class:`OnnxEmbedder` (local ONNX, no key) and the artifact-loading
:func:`search` entry point live here too.

Two invariants this module exists to protect:

1. **One embedding space.** The runtime query embedder MUST be the same model
   that built the shipped index — otherwise query and chunk vectors live in
   different spaces and cosine scores are meaningless. Both the offline build
   (``scripts/build_rag_index.py``) and the request path obtain their embedder
   through this same :class:`Embedder` seam.
2. **No heavy runtime deps.** On the Render free tier (~512MB, already carrying
   FastAPI + pandas + the CSVs) we do NOT load torch / full sentence-transformers
   at runtime. A concrete :class:`Embedder` must be a small-footprint
   implementation (quantized ONNX, or a thin API client).

Retrieval itself is brute-force cosine top-k over a shipped numpy array — at
N in the hundreds an ANN index (FAISS/vector DB) is premature and an extra
dependency (spec section 3).
"""

from __future__ import annotations

import importlib.resources as resources
import json
from typing import Protocol, runtime_checkable

import numpy as np

#: Vendored embedding model (shipped as package data under rain_garden/data/),
#: so there is no runtime download and no huggingface_hub dependency on the hot
#: path. Source: qdrant/bge-small-en-v1.5-onnx-q (BAAI bge-small-en-v1.5, an
#: optimized/quantized ONNX export). BERT encoder, 384-dim, [CLS] pooling.
EMBED_MODEL_DIR = "embedding_model"
EMBED_DIM = 384
MAX_SEQ_LEN = 512


@runtime_checkable
class Embedder(Protocol):
    """Turns text into unit vectors in one fixed embedding space.

    A concrete implementation wraps exactly one embedding model. The same
    instance/model type must be used to build the index and to embed queries at
    request time (invariant 1 above).
    """

    #: Dimensionality of the produced vectors (columns of the returned array).
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed ``texts`` into an ``(len(texts), dim)`` L2-normalized array.

        Implementations MUST L2-normalize each row so that a dot product against
        the (also normalized) shipped index is a cosine similarity. Returns
        ``float32``.
        """
        ...


class OnnxEmbedder:
    """Concrete :class:`Embedder` (HALT 1 choice A): local ONNX, no API, no key.

    Runs the vendored bge-small ONNX model via onnxruntime and the ``tokenizers``
    fast tokenizer. onnxruntime and tokenizers are imported lazily in the
    constructor so merely importing this module (e.g. for :func:`cosine_top_k`)
    does not pull the ONNX runtime.

    The SAME class is used by the offline index build (``scripts/build_rag_index``)
    and the request path, so query and chunk vectors are guaranteed to share one
    embedding space — the space invariant is structural, not a matched pair of
    call sites. Both sides encode identically (no asymmetric query instruction),
    so the guarantee holds regardless of bge's retrieval-prefix convention.
    """

    dim = EMBED_DIM

    def __init__(self, model_dir: str | None = None) -> None:
        import onnxruntime as ort  # lazy: heavy native runtime
        from tokenizers import Tokenizer

        base = (
            resources.files("rain_garden") / "data" / EMBED_MODEL_DIR
            if model_dir is None
            else _PathLike(model_dir)
        )
        self._session = ort.InferenceSession(
            str(base / "model_optimized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed ``texts`` -> ``(len(texts), 384)`` L2-normalized float32 array."""
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        encs = self._tokenizer.encode_batch(texts)
        feed = {
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encs], dtype=np.int64),
        }
        last_hidden = self._session.run(["last_hidden_state"], feed)[0]
        cls = last_hidden[:, 0]  # [CLS] pooling (bge sentence embedding)
        return l2_normalize(cls)


class _PathLike:
    """Tiny ``/``-joinable wrapper so a str model_dir mirrors the resources API."""

    def __init__(self, path: str) -> None:
        import pathlib

        self._p = pathlib.Path(path)

    def __truediv__(self, other: str) -> "pathlib.Path":  # noqa: F821
        return self._p / other


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Return ``matrix`` with each row scaled to unit L2 norm.

    Row-wise: ``v / ||v||``. A zero row is left as zeros (its norm is clamped to
    1.0 to avoid division by zero) so it simply scores 0 against every query
    rather than producing NaNs. Used by both the offline index build and every
    concrete :class:`Embedder` so normalization is defined in exactly one place.
    """
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


def cosine_top_k(
    query_vec: np.ndarray, matrix: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """Return the ``k`` highest-scoring rows of ``matrix`` against ``query_vec``.

    Both operands are assumed already L2-normalized (so the dot product is a
    cosine similarity — this is the brute-force top-k of spec section 3). Returns
    ``[(row_index, score), ...]`` sorted by descending score, length
    ``min(k, n_rows)``. ``query_vec`` may be shape ``(dim,)`` or ``(1, dim)``.
    """
    if k <= 0 or matrix.size == 0:
        return []
    q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    scores = matrix @ q  # (n_rows,)
    k = min(k, scores.shape[0])
    # argpartition for the top-k, then sort just those k by score descending.
    top = np.argpartition(scores, -k)[-k:]
    top = top[np.argsort(scores[top])[::-1]]
    return [(int(i), float(scores[i])) for i in top]


# --- Shipped-index retrieval -------------------------------------------------

DEFAULT_K = 4
_GUIDANCE_CHUNKS = "guidance_chunks.jsonl"
_GUIDANCE_EMB = "guidance_embeddings.npy"

# Loaded once per process (spec section 3: load array + metadata at process start).
_index_cache: tuple[np.ndarray, list[dict]] | None = None
_shared_embedder: OnnxEmbedder | None = None


def load_index() -> tuple[np.ndarray, list[dict]]:
    """Return the shipped ``(embeddings, chunks)`` pair, cached per process.

    ``embeddings`` is the L2-normalized ``(n, dim)`` array; ``chunks`` is the
    row-aligned metadata list. Row ``i`` of the array is ``chunks[i]``. Raises if
    the two artifacts disagree on row count (a stale/mismatched build).
    """
    global _index_cache
    if _index_cache is None:
        data = resources.files("rain_garden") / "data"
        with resources.as_file(data / _GUIDANCE_EMB) as npy:
            embeddings = np.load(npy)
        raw = (data / _GUIDANCE_CHUNKS).read_text(encoding="utf-8")
        chunks = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if embeddings.shape[0] != len(chunks):
            raise RuntimeError(
                f"index mismatch: {embeddings.shape[0]} embeddings vs "
                f"{len(chunks)} chunks — rebuild scripts/build_rag_index.py"
            )
        _index_cache = (embeddings, chunks)
    return _index_cache


def _get_embedder() -> OnnxEmbedder:
    global _shared_embedder
    if _shared_embedder is None:
        _shared_embedder = OnnxEmbedder()
    return _shared_embedder


def search(query: str, k: int = DEFAULT_K, embedder: Embedder | None = None) -> list[dict]:
    """Return the top-``k`` guidance passages for ``query`` (spec sections 3-4).

    Embeds the query in the shipped index's space, scores by cosine, and returns
    ``[{text, source_doc, source_url, citation_label, page, score}, ...]`` sorted
    by descending score. Deterministic given the query + shipped index. ``k`` is
    clamped to the corpus size by :func:`cosine_top_k`. ``embedder`` is injectable
    for tests; production uses the shared :class:`OnnxEmbedder`.
    """
    embeddings, chunks = load_index()
    model = embedder or _get_embedder()
    query_vec = model.embed([query])
    if query_vec.shape[0] == 0:
        return []
    results = []
    for idx, score in cosine_top_k(query_vec[0], embeddings, k):
        chunk = chunks[idx]
        results.append({
            "text": chunk["text"],
            "source_doc": chunk["source_doc"],
            "source_url": chunk["source_url"],
            "citation_label": chunk["citation_label"],
            "page": chunk.get("page"),
            "score": round(score, 4),
        })
    return results
