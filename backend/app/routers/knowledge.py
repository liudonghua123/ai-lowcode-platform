"""Knowledge base: collections, documents, chunk indexing and RAG search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..config import settings
from ..services import rag

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


class CollectionIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    name: str
    description: str | None = None
    embedding_model: str = "bm25-local"
    chunk_size: int = 480


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None


class DocumentIn(BaseModel):
    collection_id: int
    title: str
    content: str
    source: str | None = "manual"


class DocumentPatch(BaseModel):
    title: str | None = None
    content: str | None = None
    source: str | None = None


class SearchIn(BaseModel):
    query: str
    collection_ids: list[int] | None = None
    top_k: int = 4


def _collection_out(row: dict) -> dict:
    return row


@router.get("/collections", summary="List knowledge collections")
def list_collections(_user: dict = Depends(deps.require("knowledge:read"))):
    rows = db.q("SELECT c.*, (SELECT COUNT(*) FROM kb_documents d WHERE d.collection_id=c.id) "
                "AS document_count FROM kb_collections c ORDER BY c.id")
    return {"collections": rows, "total": len(rows)}


@router.post("/collections", status_code=201, summary="Create a collection")
def create_collection(body: CollectionIn, user: dict = Depends(deps.require("knowledge:write")),
                      request: Request = None):
    if db.q1("SELECT id FROM kb_collections WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Collection code already exists")
    cid = db.insert("kb_collections", {**body.model_dump(), "created_by": user["username"],
                                       "created_at": db.now()})
    deps.audit(user["username"], "knowledge.collection.create", f"kb:{body.code}", {}, request=request)
    return _collection_out(db.q1("SELECT * FROM kb_collections WHERE id=?", (cid,)))


@router.put("/collections/{collection_id}", summary="Update a collection")
def update_collection(collection_id: int, body: CollectionPatch,
                      user: dict = Depends(deps.require("knowledge:write")), request: Request = None):
    if not db.q1("SELECT id FROM kb_collections WHERE id=?", (collection_id,)):
        raise HTTPException(status_code=404, detail="Collection not found")
    db.update("kb_collections", collection_id, body.model_dump(exclude_none=True))
    if body.chunk_size:
        for d in db.q("SELECT id FROM kb_documents WHERE collection_id=?", (collection_id,)):
            rag.index_document(d["id"], body.chunk_size)
    deps.audit(user["username"], "knowledge.collection.update", f"kb:{collection_id}", {}, request=request)
    return db.q1("SELECT * FROM kb_collections WHERE id=?", (collection_id,))


@router.delete("/collections/{collection_id}", summary="Delete a collection and its documents")
def delete_collection(collection_id: int, user: dict = Depends(deps.require("knowledge:write")),
                      request: Request = None):
    row = db.q1("SELECT code FROM kb_collections WHERE id=?", (collection_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Collection not found")
    db.run("DELETE FROM kb_documents WHERE collection_id=?", (collection_id,))
    db.delete("kb_collections", collection_id)
    deps.audit(user["username"], "knowledge.collection.delete", f"kb:{row['code']}", {}, request=request)
    return {"ok": True}


@router.get("/documents", summary="List documents")
def list_documents(collection_id: int | None = None, q: str | None = None,
                   _user: dict = Depends(deps.require("knowledge:read"))):
    sql, args = "SELECT * FROM kb_documents WHERE 1=1", []
    if collection_id:
        sql += " AND collection_id=?"
        args.append(collection_id)
    if q:
        sql += " AND (title LIKE ? OR content LIKE ?)"
        args += [f"%{q}%"] * 2
    rows = db.q(sql + " ORDER BY id DESC", tuple(args))
    out = []
    for r in rows:
        d = db.loads(r, "chunks") or {}
        d["chunk_count"] = len(d.get("chunks") or [])
        d["content_preview"] = (d.get("content") or "")[:180]
        d.pop("chunks", None)
        out.append(d)
    return {"documents": out, "total": len(out)}


@router.get("/documents/{document_id}", summary="Get a document with chunks")
def get_document(document_id: int, _user: dict = Depends(deps.require("knowledge:read"))):
    row = db.q1("SELECT * FROM kb_documents WHERE id=?", (document_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.loads(row, "chunks")


@router.post("/documents", status_code=201, summary="Create and index a document")
def create_document(body: DocumentIn, user: dict = Depends(deps.require("knowledge:write")),
                    request: Request = None):
    if not db.q1("SELECT id FROM kb_collections WHERE id=?", (body.collection_id,)):
        raise HTTPException(status_code=404, detail="Collection not found")
    did = db.insert("kb_documents", {**body.model_dump(), "status": "indexed", "chunks": [],
                                     "created_at": db.now()})
    count = rag.index_document(did)
    deps.audit(user["username"], "knowledge.document.create", f"kb-doc:{did}",
               {"chunks": count}, request=request)
    return db.loads(db.q1("SELECT * FROM kb_documents WHERE id=?", (did,)), "chunks")


@router.put("/documents/{document_id}", summary="Update and reindex a document")
def update_document(document_id: int, body: DocumentPatch,
                    user: dict = Depends(deps.require("knowledge:write")), request: Request = None):
    if not db.q1("SELECT id FROM kb_documents WHERE id=?", (document_id,)):
        raise HTTPException(status_code=404, detail="Document not found")
    patch = body.model_dump(exclude_none=True)
    db.update("kb_documents", document_id, patch)
    if "content" in patch:
        rag.index_document(document_id)
    deps.audit(user["username"], "knowledge.document.update", f"kb-doc:{document_id}", {}, request=request)
    return db.loads(db.q1("SELECT * FROM kb_documents WHERE id=?", (document_id,)), "chunks")


@router.post("/documents/{document_id}/reindex")
def reindex(document_id: int, user: dict = Depends(deps.require("knowledge:write")),
            request: Request = None):
    count = rag.index_document(document_id)
    if not count and not db.q1("SELECT id FROM kb_documents WHERE id=?", (document_id,)):
        raise HTTPException(status_code=404, detail="Document not found")
    deps.audit(user["username"], "knowledge.document.reindex", f"kb-doc:{document_id}",
               {"chunks": count}, request=request)
    return {"ok": True, "chunks": count}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, user: dict = Depends(deps.require("knowledge:write")),
                    request: Request = None):
    if not db.q1("SELECT id FROM kb_documents WHERE id=?", (document_id,)):
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete("kb_documents", document_id)
    deps.audit(user["username"], "knowledge.document.delete", f"kb-doc:{document_id}", {}, request=request)
    return {"ok": True}


@router.post("/search", summary="RAG retrieval over the knowledge base")
def search(body: SearchIn, user: dict = Depends(deps.require("knowledge:read")),
           request: Request = None):
    hits = rag.search(body.query, body.collection_ids, min(body.top_k, 10) or settings.rag_top_k)
    deps.audit(user["username"], "knowledge.search", "kb",
               {"query": body.query, "hits": len(hits)}, request=request)
    return {"query": body.query, "hits": hits, "count": len(hits),
            "context": rag.build_context(hits)}


@router.get("/stats", summary="Knowledge base statistics")
def stats(_user: dict = Depends(deps.require("knowledge:read"))):
    return {"collections": int(db.scalar("SELECT COUNT(*) FROM kb_collections") or 0),
            "documents": int(db.scalar("SELECT COUNT(*) FROM kb_documents") or 0),
            "chunks": sum(len((db.loads(r, "chunks") or {}).get("chunks") or [])
                          for r in db.q("SELECT chunks FROM kb_documents")),
            "retriever": "bm25-local", "embedding_model": "bm25-local"}
