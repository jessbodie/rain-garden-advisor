"""Offline build script for the search_guidance RAG corpus.

NOT in the request path. Mirrors the CSV pattern: build offline, ship the
artifact, no runtime index build. Deterministic given corpus + chunking params.

This script owns the *chunking* half of the pipeline (Step 2 of the RAG plan):
it reads the corpus manifest, extracts unstructured why/how prose from each
source, normalizes it, splits it into overlapping word windows, drops
table-like/low-content windows (a structural nod to spec section 1: unstructured
prose only, no ingested tables), and writes a row-aligned JSONL sidecar plus a
chunk/source inventory.

The *embedding* half (write the L2-normalized ``.npy`` aligned to this sidecar)
is deliberately deferred to after HALT 1, when the embedder provider (A: local
ONNX vs B: Voyage) is chosen. It will be added here behind the ``Embedder`` seam
in ``rain_garden.retrieval`` and consume ``guidance_chunks.jsonl`` verbatim, so
row alignment is preserved.

Usage (from repo root, with the project venv):
    python scripts/build_rag_index.py            # build sidecar + print inventory
    python scripts/build_rag_index.py --inventory-only   # inventory, no write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from pypdf import PdfReader

# stdout may carry Unicode (curly quotes, en-dashes) from the PDFs; a Windows
# cp1252 console raises UnicodeEncodeError on print. Make it tolerant.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "data" / "corpus" / "manifest.json"
SIDECAR_OUT = REPO_ROOT / "src" / "rain_garden" / "data" / "guidance_chunks.jsonl"
EMBED_OUT = REPO_ROOT / "src" / "rain_garden" / "data" / "guidance_embeddings.npy"

# Chunking params (small fixed-word windows with overlap). ~180 words is roughly
# a 230-token window; a 40-word overlap keeps a sentence that straddles a window
# boundary retrievable from either side.
CHUNK_WORDS = 180
OVERLAP_WORDS = 40

# Quality gate — drop windows that are table-like or too thin to be useful prose.
MIN_ALPHA_WORDS = 25          # need enough real words to be a coherent passage
MIN_ALPHA_RATIO = 0.55        # alphabetic words / all tokens
MAX_DIGIT_TOKEN_RATIO = 0.30  # tokens containing a digit / all tokens (tables)

_WS = re.compile(r"\s+")
_ALPHA_WORD = re.compile(r"[A-Za-z]{2,}")


def normalize(text: str) -> str:
    """Collapse a raw extracted string into a single clean whitespace-run stream.

    Rejoins words split by a hyphen at a line break ("gar-\\nden" -> "garden"),
    drops soft hyphens, canonicalizes the Unicode hyphen, and collapses all
    whitespace to single spaces.
    """
    text = text.replace("­", "")               # soft hyphen
    text = re.sub(r"[-‐]\n", "", text)          # hyphenation at line break
    text = text.replace("‐", "-")               # Unicode hyphen -> ASCII
    return _WS.sub(" ", text).strip()


def extract_segments(source: dict) -> list[list[tuple[str, int | None]]]:
    """Return contiguous ``[(word, page_or_None), ...]`` segments for one source.

    PDFs are walked page by page so each word carries the page it came from
    (drives a page-aware citation later); text sources carry ``page=None``.

    Dedicated table/list/boilerplate pages are dropped whole (spec section 1: do
    not ingest a table into the corpus) rather than relying on the chunk-level
    digit heuristic, which plant-name tables slip past. Dropping a middle page
    would otherwise let a window span the gap and mix topics across it, so a new
    segment is started at every discontinuity in kept pages — chunks never cross
    an exclusion gap, and each chunk's page label stays honest.
    """
    path = REPO_ROOT / source["path"]
    if source["kind"] != "pdf":  # text: one segment, no pages
        words = [(w, None) for w in normalize(path.read_text(encoding="utf-8")).split()]
        return [words] if words else []

    exclude = set(source.get("exclude_pages", []))
    reader = PdfReader(str(path))
    segments: list[list[tuple[str, int | None]]] = []
    current: list[tuple[str, int | None]] = []
    prev_page: int | None = None
    for page_no, page in enumerate(reader.pages, start=1):
        if page_no in exclude:
            continue
        if prev_page is not None and page_no != prev_page + 1 and current:
            segments.append(current)  # gap in kept pages -> break the segment
            current = []
        for w in normalize(page.extract_text() or "").split():
            current.append((w, page_no))
        prev_page = page_no
    if current:
        segments.append(current)
    return segments


def _is_quality(tokens: list[str]) -> bool:
    """True if a window reads as prose, not a table fragment or thin scrap."""
    if not tokens:
        return False
    alpha = [t for t in tokens if _ALPHA_WORD.search(t)]
    digit = [t for t in tokens if any(ch.isdigit() for ch in t)]
    if len(alpha) < MIN_ALPHA_WORDS:
        return False
    if len(alpha) / len(tokens) < MIN_ALPHA_RATIO:
        return False
    if len(digit) / len(tokens) > MAX_DIGIT_TOKEN_RATIO:
        return False
    return True


def chunk_source(source: dict) -> list[dict]:
    """Window one source into quality-filtered chunk dicts (no id yet).

    Windows are formed within each contiguous page segment, so no chunk spans an
    excluded-page gap.
    """
    stride = CHUNK_WORDS - OVERLAP_WORDS
    chunks: list[dict] = []
    for segment in extract_segments(source):
        for start in range(0, max(1, len(segment)), stride):
            window = segment[start : start + CHUNK_WORDS]
            if not window:
                break
            tokens = [w for w, _ in window]
            if _is_quality(tokens):
                chunks.append({
                    "text": " ".join(tokens),
                    "source_doc": source["source_doc"],
                    "source_url": source["source_url"],
                    "citation_label": source["citation_label"],
                    "page": window[0][1],
                })
            if start + CHUNK_WORDS >= len(segment):
                break
    return chunks


def build(manifest: dict) -> list[dict]:
    """Build the full row-aligned chunk list across all active sources."""
    rows: list[dict] = []
    for source in manifest["sources"]:
        rows.extend(chunk_source(source))
    for i, row in enumerate(rows):
        row["id"] = i  # row index == embedding-array row (Step 5 alignment)
    return rows


def print_inventory(manifest: dict, rows: list[dict]) -> None:
    """Emit the chunk/source inventory (Step 2 deliverable for gold derivation)."""
    per_source: dict[str, int] = {}
    for r in rows:
        per_source[r["source_doc"]] = per_source.get(r["source_doc"], 0) + 1
    print("=" * 72)
    print(f"CORPUS INVENTORY  ({len(rows)} chunks total)")
    print(f"  chunk window: {CHUNK_WORDS} words, overlap {OVERLAP_WORDS}")
    print("=" * 72)
    for source in manifest["sources"]:
        sd = source["source_doc"]
        print(f"\n[{sd}]  {per_source.get(sd, 0)} chunks  <- {source['citation_label']}")
        sample = next((r for r in rows if r["source_doc"] == sd), None)
        if sample:
            snippet = sample["text"][:280]
            print(f"    e.g. (p{sample['page']}): {snippet}...")
    pending = manifest.get("pending_sources") or []
    if pending:
        print("\nPENDING (not yet ingested):")
        for p in pending:
            print(f"  - {p['source_doc']}: {p['license']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory-only", action="store_true",
        help="Print the inventory without writing the sidecar.",
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = build(manifest)
    print_inventory(manifest, rows)

    if args.inventory_only:
        return
    SIDECAR_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SIDECAR_OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(rows)} chunks -> {SIDECAR_OUT.relative_to(REPO_ROOT)}")

    # Embed the frozen chunks with the SAME OnnxEmbedder the request path uses,
    # then ship the row-aligned .npy alongside the sidecar. Written together so
    # embeddings[i] always corresponds to sidecar row i (retrieval alignment).
    from rain_garden.retrieval import OnnxEmbedder  # heavy import; only when building
    embeddings = OnnxEmbedder().embed([r["text"] for r in rows])
    assert embeddings.shape[0] == len(rows), "embedding/sidecar row-count mismatch"
    np.save(EMBED_OUT, embeddings)
    print(f"Wrote embeddings {embeddings.shape} -> {EMBED_OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
