"""Local BM25 retrieval for the knowledge base (no external vector service needed).

Chinese text is tokenized into unigrams + bigrams, English into words, so mixed
zh/en documents are searchable. Swap ``search`` for a vector store adapter to
use a real embedding service in production.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .. import db


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(list(seg))
        tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


def chunk_text(text: str, size: int = 480) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        while len(para) > size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.append(para[:size].strip())
            para = para[size:]
        if len(buf) + len(para) + 1 > size and buf:
            chunks.append(buf.strip())
            buf = ""
        buf = (buf + " " + para).strip()
    if buf:
        chunks.append(buf)
    return chunks


def index_document(doc_id: int, size: int = 480) -> int:
    doc = db.q1("SELECT d.id,d.content,c.chunk_size FROM kb_documents d "
                "JOIN kb_collections c ON c.id=d.collection_id WHERE d.id=?", (doc_id,))
    if not doc:
        return 0
    chunks = chunk_text(doc["content"], doc.get("chunk_size") or size)
    db.update("kb_documents", doc_id, {"chunks": chunks, "status": "indexed"})
    return len(chunks)


def search(query: str, collection_ids: list[int] | None = None, top_k: int = 4) -> list[dict]:
    rows = db.q(
        "SELECT d.id,d.collection_id,d.title,d.content,c.name AS collection_name "
        "FROM kb_documents d JOIN kb_collections c ON c.id=d.collection_id "
        "WHERE d.status='indexed'"
    )
    if collection_ids:
        rows = [r for r in rows if r["collection_id"] in collection_ids]
    if not rows or not query.strip():
        return []
    q_terms = set(tokenize(query))
    if not q_terms:
        return []
    doc_tokens = [tokenize(f"{r['title']} {r['content']}") for r in rows]
    n_docs = len(rows)
    avgdl = max(1.0, sum(len(t) for t in doc_tokens) / n_docs)
    df = Counter()
    for toks in doc_tokens:
        df.update(set(toks))
    k1, b = 1.5, 0.75
    hits: list[dict] = []
    for row, toks in zip(rows, doc_tokens, strict=False):
        tf = Counter(toks)
        dl = max(1, len(toks))
        score = 0.0
        for term in q_terms:
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if score <= 0:
            continue
        content = row["content"] or ""
        lower = content.lower()
        pos = min([lower.find(t) for t in q_terms if len(t) > 1 and lower.find(t) >= 0] or [0])
        start = max(0, pos - 90)
        snippet = content[start:start + 320].strip()
        if start > 0:
            snippet = "…" + snippet
        if start + 320 < len(content):
            snippet += "…"
        hits.append({
            "doc_id": row["id"], "collection_id": row["collection_id"],
            "collection": row["collection_name"], "title": row["title"],
            "snippet": snippet, "score": round(score, 4),
        })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


def build_context(hits: list[dict], max_chars: int = 2200) -> str:
    if not hits:
        return "No relevant knowledge base documents were retrieved."
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"[{i}] {h['title']} (collection: {h['collection']}, score {h['score']})\n{h['snippet']}")
    text = "\n\n".join(parts)
    return text[:max_chars]
