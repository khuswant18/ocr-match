"""
Vector-based product description matching.

Architecture:
  - Qdrant (external Docker service) stores fastembed vectors for PO descriptions.
  - BAAI/bge-small-en-v1.5 (~130MB ONNX) used automatically by qdrant-client[fastembed].
  - Top-3 candidates are retrieved then reranked using a combined score:
      combined = 0.65 * vector_cosine + 0.35 * token_jaccard
  - This hybrid approach handles synonyms (vector) AND exact word matches (token).
"""

import os
import re

from qdrant_client import QdrantClient

COLLECTION = "po_descriptions"

# Only accept a match when the combined hybrid score meets this bar.
# 0.50 is deliberately conservative — a product description match should be clear.
COMBINED_THRESHOLD = 0.65

# Weight split between semantic (vector) and lexical (token overlap) scoring.
VECTOR_WEIGHT = 0.65
TOKEN_WEIGHT = 0.35

_client: QdrantClient | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        host = os.environ.get("QDRANT_HOST", "qdrant")
        port = int(os.environ.get("QDRANT_PORT", 6333))
        _client = QdrantClient(host=host, port=port)
    return _client


def _normalize(text: str) -> str:
    """
    Normalise a product description before embedding or token comparison.
    - Lowercase
    - Replace hyphens/slashes with spaces (e.g. "anti-bacterial" → "anti bacterial")
    - Strip all non-alphanumeric characters except spaces
    - Collapse whitespace
    This ensures "RICE 50KG" and "rice  50 kg" produce the same tokens.
    """
    text = text.lower()
    text = re.sub(r"[-/]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_jaccard(a: str, b: str) -> float:
    """
    Jaccard similarity on word-token sets.
    J(A, B) = |A ∩ B| / |A ∪ B|
    Returns 0.0 when either string is empty.
    """
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _combined_score(vector_score: float, a_norm: str, b_norm: str) -> float:
    """Weighted combination of semantic vector score and token overlap."""
    token_score = _token_jaccard(a_norm, b_norm)
    return VECTOR_WEIGHT * vector_score + TOKEN_WEIGHT * token_score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def index_po_items(po_items: dict) -> None:
    """
    Embed every PO item description via fastembed and upsert into Qdrant.
    Recreates the collection on each match run so it always reflects the
    current PO's items.
    """
    client = _get_client()

    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[int] = []

    for idx, (code, data) in enumerate(po_items.items()):
        raw_desc = (data.get("desc") or "").strip()
        if not raw_desc:
            continue
        # Index the *normalised* description so query-side normalisation matches.
        documents.append(_normalize(raw_desc))
        metadatas.append({"product_code": code, "raw_desc": raw_desc})
        ids.append(idx)  # simple sequential ID — avoids any hash collision

    if documents:
        # client.add() creates the collection automatically with fastembed
        # (BAAI/bge-small-en-v1.5, 384-dim cosine, ~130MB ONNX — no PyTorch/CUDA needed)
        client.add(
            collection_name=COLLECTION,
            documents=documents,
            metadata=metadatas,
            ids=ids,
        )
        print(f"[vector_service] Indexed {len(documents)} PO descriptions into Qdrant.")


def find_best_match(inv_desc: str, threshold: float = COMBINED_THRESHOLD) -> str | None:
    """
    Return the product_code whose PO description is most semantically similar
    to inv_desc using hybrid reranking, or None if no match clears the threshold.

    Steps:
      1. Normalise inv_desc.
      2. Query Qdrant for top-3 candidates by pure vector similarity.
      3. Rerank each candidate using combined (vector + token) score.
      4. Return the best candidate only if its combined score >= threshold.
    """
    if not inv_desc.strip():
        return None

    inv_norm = _normalize(inv_desc)
    if not inv_norm:
        return None

    client = _get_client()

    # Fetch top-3 so we can rerank; normalised text is used for the query too
    results = client.query(
        collection_name=COLLECTION,
        query_text=inv_norm,
        limit=3,
    )

    if not results:
        return None

    best_code = None
    best_score = -1.0

    for hit in results:
        vec_score = hit.score
        po_norm = _normalize(hit.metadata.get("raw_desc", ""))
        score = _combined_score(vec_score, inv_norm, po_norm)

        print(
            f"[vector_service] '{inv_desc}' vs '{hit.metadata.get('raw_desc', '')}' "
            f"| vec={vec_score:.3f} token={_token_jaccard(inv_norm, po_norm):.3f} combined={score:.3f}"
        )

        if score > best_score:
            best_score = score
            best_code = hit.metadata.get("product_code")

    if best_score >= threshold:
        print(f"[vector_service] MATCHED → '{best_code}' (score={best_score:.3f})")
        return best_code

    print(f"[vector_service] NO MATCH for '{inv_desc}' (best combined={best_score:.3f} < threshold={threshold})")
    return None
