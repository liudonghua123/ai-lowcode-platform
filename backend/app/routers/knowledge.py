"""Knowledge base: collections, multi-format document upload, chunk indexing and RAG search."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .. import db, deps
from ..config import settings
from ..services import documents as doc_service
from ..services import model_providers, rag

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


def _document_out(row: dict) -> dict:
    out = db.loads(row, "chunks") or {}
    out["file_label"] = doc_service.label_for(out.get("file_type") or "")
    return out


@router.get("/formats", summary="Supported knowledge-base upload formats")
def upload_formats(_user: dict = Depends(deps.require("knowledge:read"))):
    return doc_service.formats()


@router.post("/upload", status_code=201, summary="Upload and index documents (Office / PDF / Markdown / text / images)")
async def upload_documents(collection_id: int = Form(...),
                           files: list[UploadFile] = File(...),
                           title: str | None = Form(None),
                           user: dict = Depends(deps.require("knowledge:write")),
                           request: Request = None):
    if not db.q1("SELECT id FROM kb_collections WHERE id=?", (collection_id,)):
        raise HTTPException(status_code=404, detail="Collection not found")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Upload at most 20 files per request")
    results: list[dict] = []
    for upload in files:
        filename = upload.filename or "upload"
        try:
            data = await upload.read()
            parsed = doc_service.parse(filename, data)
        except doc_service.UnsupportedFormat as exc:
            results.append({"file_name": filename, "ok": False, "error": str(exc)})
            continue
        except Exception as exc:  # malformed uploads must not abort the batch
            results.append({"file_name": filename, "ok": False,
                            "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
            continue
        doc_title = (title.strip() if title and len(files) == 1 and title.strip()
                     else Path(filename).stem) or filename
        did = db.insert("kb_documents", {
            "collection_id": collection_id, "title": doc_title,
            "content": parsed["text"], "source": "upload",
            "status": "indexed" if parsed["text"] else "empty", "chunks": [],
            "file_name": parsed["file_name"], "file_type": parsed["file_type"],
            "file_size": parsed["file_size"], "parse_status": parsed["parse_status"],
            "parse_error": parsed["parse_error"], "created_at": db.now(),
        })
        chunks = rag.index_document(did) if parsed["text"] else 0
        results.append({"id": did, "ok": True, "title": doc_title,
                        "file_name": parsed["file_name"], "file_type": parsed["file_type"],
                        "file_label": parsed["file_label"], "file_size": parsed["file_size"],
                        "parse_status": parsed["parse_status"], "parse_error": parsed["parse_error"],
                        "chars": parsed["chars"], "chunks": chunks})
    created = [r for r in results if r["ok"]]
    deps.audit(user["username"], "knowledge.upload", f"kb:{collection_id}",
               {"files": len(files), "created": len(created)}, request=request)
    return {"uploaded": len(created), "failed": len(results) - len(created),
            "collection_id": collection_id, "documents": results}


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
        d["file_label"] = doc_service.label_for(d.get("file_type") or "")
        d.pop("chunks", None)
        out.append(d)
    return {"documents": out, "total": len(out)}


@router.get("/documents/{document_id}", summary="Get a document with chunks")
def get_document(document_id: int, _user: dict = Depends(deps.require("knowledge:read"))):
    row = db.q1("SELECT * FROM kb_documents WHERE id=?", (document_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_out(row)


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
    return _document_out(db.q1("SELECT * FROM kb_documents WHERE id=?", (did,)) or {})


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
    return _document_out(db.q1("SELECT * FROM kb_documents WHERE id=?", (document_id,)) or {})


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
    embedding = model_providers.default_for("embedding")
    rerank = model_providers.default_for("rerank")
    by_type = {r["file_type"]: r["count"] for r in db.q(
        "SELECT file_type, COUNT(*) AS count FROM kb_documents "
        "WHERE file_type IS NOT NULL GROUP BY file_type")}
    return {"collections": int(db.scalar("SELECT COUNT(*) FROM kb_collections") or 0),
            "documents": int(db.scalar("SELECT COUNT(*) FROM kb_documents") or 0),
            "chunks": sum(len((db.loads(r, "chunks") or {}).get("chunks") or [])
                          for r in db.q("SELECT chunks FROM kb_documents")),
            "uploaded": int(db.scalar(
                "SELECT COUNT(*) FROM kb_documents WHERE source='upload'") or 0),
            "formats_supported": doc_service.formats()["total"],
            "by_file_type": by_type,
            "retriever": embedding["model"] if embedding else "bm25-local",
            "embedding_model": embedding["model"] if embedding else "bm25-local",
            "embedding_provider": embedding["code"] if embedding else None,
            "rerank_provider": rerank["model"] if rerank else "none"}
