"""
Vector-based product description matching.

Architecture:
  - Qdrant (external Docker service) stores fastembed vectors for PO descriptions.
  - BAAI/bge-small-en-v1.5 (~130MB ONNX) used automatically by qdrant-client[fastembed].
  - Top-K candidates are retrieved then reranked using a combined score:
      combined = VECTOR_WEIGHT * cosine + TOKEN_WEIGHT * token_overlap
  - Token overlap uses a soft metric (Jaccard + substring bonus) so abbreviated
    PO descriptions ("CHRZO D CEBU") match verbose invoice descriptions
    ("Chorizo de Cebu").
"""

import os
import re

from qdrant_client import QdrantClient

COLLECTION = "po_descriptions"

# Primary threshold — high-confidence match.
COMBINED_THRESHOLD = 0.55

# Relaxed threshold for second-pass (remaining unknowns vs remaining PO items).
RELAXED_THRESHOLD = 0.40

# Weight split between semantic (vector) and lexical (token overlap) scoring.
VECTOR_WEIGHT = 0.50
TOKEN_WEIGHT = 0.50

_client: QdrantClient | None = None

# ---------------------------------------------------------------------------
# Abbreviation / noise maps for food-distribution product descriptions
#
# Built from the full po_lines.product_full_desc corpus.  Both the PO side
# and the invoice side are normalised, so we need expansions in both
# directions (abbreviated PO → full word, full invoice → same full word).
# ---------------------------------------------------------------------------

_ABBREVIATIONS: dict[str, str] = {
    # Hotdog variants
    "hdog": "hotdog", "hdg": "hotdog", "hd": "hotdog", "htdg": "hotdog",
    # Protein type
    "chkn": "chicken", "chckn": "chicken", "chcken": "chicken",
    "prk": "pork", "brgr": "burger",
    # Product type
    "chrzo": "chorizo", "tcno": "tocino", "tcn": "tocino",
    "lnchnmeat": "luncheon meat", "lncnmt": "luncheon meat",
    "lnchmt": "luncheon meat",
    "sausg": "sausage", "sausge": "sausage",
    "mndrn": "mandarin",
    "hmnd": "hamonado", "hmndo": "hamonado",
    "lgnsz": "longganisa", "lngnz": "longganisa", "lngnza": "longganisa",
    "lmpia": "lumpia", "wrpper": "wrapper",
    "crnd": "corned", "crn": "corned",
    "frzn": "frozen", "frzn": "frozen",
    "chns": "chinese", "styl": "style",
    # Size / grade
    "prm": "premium", "prem": "premium",
    "reg": "regular", "rg": "regular",
    "jmb": "jumbo", "jmbo": "jumbo", "jum": "jumbo", "jb": "jumbo",
    "clsc": "classic", "cls": "classic",
    "bg": "big", "sht": "shot",
    "bnls": "boneless", "skg": "skinless",
    "spcd": "spiced", "spcy": "spicy",
    "smky": "smoky",
    # Packaging / processing
    "ctl": "cocktails", "cktails": "cocktails",
    "wch": "with cheese", "wchs": "with cheese", "wcheese": "with cheese",
    "cheesedog": "cheesedog", "chesedog": "cheesedog",
    "chsedog": "cheesedog",
    # Brand abbreviations vendors use on invoices
    "vir": "virginia", "virgnia": "virginia", "vrgna": "virginia",
    "vfi": "virginia",
    "el": "el", "rncho": "rancho",
    "wnnr": "winner",
    # Body parts / descriptors that come up in meat products
    "ln": "lean", "all": "all",
    # Cooking style
    "hngurian": "hungarian", "hngarian": "hungarian",
    "nwyrk": "new york",
    # Misc
    "pa": "party", "karage": "karaage",
    "chikn": "chicken", "chcknppprs": "chicken poppers",
}

# Brand aliases: alternative brand names that vendors print on invoices
# for the same manufacturer products.  Key = normalised invoice brand,
# value = list of canonical brand tokens to inject.
_BRAND_ALIASES: dict[str, list[str]] = {
    "happy booster": ["virginia", "premium"],
    "booster": ["virginia", "premium"],
}

# Words that describe packaging format, not the product itself.
_NOISE_WORDS: set[str] = {
    "ldld", "ladlad", "pack", "bundle", "pcs", "pc", "s",
    "x", "de", "d",
}


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

    Steps:
      1. Lowercase
      2. Extract parenthetical hints like "(Premium Hotdog)" and prepend them
      3. Replace hyphens/slashes/quotes with spaces
      4. Strip weight/packaging patterns: "1kg", "2k/5", "4.52k", "6s", etc.
      5. Strip all remaining non-alpha characters
      6. Expand brand aliases ("Happy Booster" → inject "virginia premium")
      7. Expand known abbreviations (HDOG → hotdog, PRM → premium, etc.)
      8. Remove packaging noise words (LDLD, LADLAD)
      9. Deduplicate tokens while preserving order
     10. Collapse whitespace
    """
    text = text.lower()

    # Pull out parenthetical hints — e.g. "(Premium Hotdog)" → "premium hotdog"
    hints = re.findall(r"\(([^)]+)\)", text)
    text = re.sub(r"\([^)]*\)", " ", text)  # remove the parens from original
    if hints:
        text = " ".join(hints) + " " + text

    text = re.sub(r'[-/\\"\'`]', " ", text)

    # Strip weight/pack patterns: "1kg", "2k", "4.52k", "6s", "12x1kg", "155g"
    # Also handle glued patterns like "JUM1KG" — split letters from digits first
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)  # "jum1kg" → "jum 1kg"
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)  # "200g"  → "200 g" (for next pass)
    text = re.sub(r"\b\d+(\.\d+)?\s*x\s*\d+(\.\d+)?\s*k(g)?\b", " ", text)
    text = re.sub(r"\b\d+(\.\d+)?\s*k(g)?\b", " ", text)
    text = re.sub(r"\b\d+(\.\d+)?\s*g\b", " ", text)
    text = re.sub(r"\b\d+(\.\d+)?\s*s\b", " ", text)  # "6s" packs
    text = re.sub(r"\b\d+(\.\d+)?\b", " ", text)       # any remaining numbers

    text = re.sub(r"[^a-z\s]", "", text)

    # Apply brand aliases before token-level expansion
    for alias, replacements in _BRAND_ALIASES.items():
        if alias in text:
            text = text.replace(alias, " ".join(replacements) + " " + alias)

    # Expand abbreviations and remove noise words
    tokens = text.split()
    expanded: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t in _NOISE_WORDS:
            continue
        word = _ABBREVIATIONS.get(t, t)
        # Handle multi-word expansions (e.g. "lnchnmeat" → "luncheon meat")
        for w in word.split():
            if w not in seen:
                expanded.append(w)
                seen.add(w)

    text = " ".join(expanded)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_overlap(a: str, b: str) -> float:
    """
    Soft token overlap — rewards partial matches more generously than Jaccard.

    Score = (2 * |intersection|) / (|A| + |B|)   (Dice coefficient)

    Plus a substring bonus: if every token of the shorter set appears as a
    substring in some token of the longer set, add 0.15.
    This handles cases like "cheese hotdog" matching "cheesedog jumbo".
    """
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0

    intersection = set_a & set_b
    dice = (2.0 * len(intersection)) / (len(set_a) + len(set_b))

    # Substring bonus: check if the unmatched tokens of the shorter side
    # appear inside tokens of the longer side
    shorter, longer = (set_a, set_b) if len(set_a) <= len(set_b) else (set_b, set_a)
    unmatched = shorter - intersection
    if unmatched:
        substr_hits = 0
        longer_joined = " ".join(longer)
        for token in unmatched:
            if len(token) >= 3 and token in longer_joined:
                substr_hits += 1
        if substr_hits == len(unmatched):
            dice += 0.15

    return min(dice, 1.0)


def _combined_score(vector_score: float, a_norm: str, b_norm: str) -> float:
    """Weighted combination of semantic vector score and token overlap."""
    token_score = _token_overlap(a_norm, b_norm)
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
        documents.append(_normalize(raw_desc))
        metadatas.append({"product_code": code, "raw_desc": raw_desc})
        ids.append(idx)

    if documents:
        client.add(
            collection_name=COLLECTION,
            documents=documents,
            metadata=metadatas,
            ids=ids,
        )
        print(f"[vector_service] Indexed {len(documents)} PO descriptions into Qdrant.")
        for doc, meta in zip(documents, metadatas):
            print(f"  [{meta['product_code']}] normalized: '{doc}'")


def find_best_match(inv_desc: str, threshold: float = COMBINED_THRESHOLD) -> str | None:
    """Convenience wrapper — returns the single best match or None."""
    candidates = find_ranked_candidates(inv_desc, threshold=threshold)
    return candidates[0][0] if candidates else None


def find_ranked_candidates(
    inv_desc: str,
    threshold: float = COMBINED_THRESHOLD,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """
    Return a ranked list of (product_code, combined_score) whose score >= threshold.

    Steps:
      1. Normalise inv_desc.
      2. Query Qdrant for top-K candidates by pure vector similarity.
      3. Rerank each candidate using combined (vector + token) score.
      4. Return all candidates above threshold, sorted best-first.
    """
    if not inv_desc.strip():
        return []

    inv_norm = _normalize(inv_desc)
    if not inv_norm:
        return []

    client = _get_client()

    results = client.query(
        collection_name=COLLECTION,
        query_text=inv_norm,
        limit=top_k,
    )

    if not results:
        return []

    scored: list[tuple[str, float]] = []

    for hit in results:
        vec_score = hit.score
        po_norm = _normalize(hit.metadata.get("raw_desc", ""))
        score = _combined_score(vec_score, inv_norm, po_norm)

        print(
            f"[vector_service] '{inv_desc}' → norm='{inv_norm}' vs "
            f"'{hit.metadata.get('raw_desc', '')}' → norm='{po_norm}' "
            f"| vec={vec_score:.3f} token={_token_overlap(inv_norm, po_norm):.3f} combined={score:.3f}"
        )

        code = hit.metadata.get("product_code")
        if score >= threshold:
            scored.append((code, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    if scored:
        print(f"[vector_service] CANDIDATES for '{inv_desc}': {[(c, round(s,3)) for c,s in scored]}")
    else:
        print(f"[vector_service] NO MATCH for '{inv_desc}' (all below threshold={threshold})")

    return scored
