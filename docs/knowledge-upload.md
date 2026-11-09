# Knowledge Upload & Document Parsing

| Field | Value |
| --- | --- |
| Document ID | `KNB-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Machine-readable source | `GET /api/v1/knowledge/formats`, `backend/app/services/documents.py` |
| Related | [REST & MCP API Reference](api-reference.md) · [Data Model](data-model.md) · [AI System Design](ai-design.md) · [Security Architecture](security.md) · [ADR-0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md) |

> 中文摘要：知识库除手工录入文本外，还支持**批量上传 43 种扩展名**的文档（Office 2007+/97-2003、OpenDocument、PDF、EPUB、RTF、Markdown、CSV/JSON/YAML、HTML/XML、源码、图片 OCR 等）。解析全部基于 **Python 标准库**（OOXML / OpenDocument / EPUB 本质是 ZIP+XML）与可选的 `pdftotext` / `tesseract` 命令行工具，不引入 `python-docx` / `openpyxl` 等重依赖。上传后写入 `kb_documents` 的文件元数据与解析状态，抽取文本**立即分块并进入 BM25 索引**，界面提供拖拽上传、格式清单与逐文件结果。单文件 ≤20 MB、每批 ≤20 个、抽取文本上限 40 万字符；所有解析均为 best-effort，绝不执行文件内容。

## 1. Scope and design goals

The original knowledge base accepted **text documents only** (`POST /knowledge/documents`). Real-world knowledge is usually stored in Office files, PDFs and Markdown, so KNB-001 adds a multipart upload path with three goals:

1. **Widest practical format coverage** using only the standard library plus CLI helpers already available on the host — no heavyweight parsing dependencies.
2. **Immediate searchability** — an uploaded file must be retrievable by the existing mixed zh/en BM25 engine without a separate "build index" step.
3. **Graceful partial failure** — one malformed or unsupported file must not abort the whole batch; every file reports its own parse status.

Out of scope: OCR language packs beyond English, full-fidelity layout/tables/images extraction, macro execution, virus scanning, and remote/object storage.

## 2. Supported formats

`GET /api/v1/knowledge/formats` returns the authoritative list (43 extensions in 7 groups), plus `max_file_bytes` and `max_text_chars`.

| Group | Count | Extensions | Extraction |
| --- | --- | --- | --- |
| `text` | 10 | `.md`, `.markdown`, `.txt`, `.text`, `.rst`, `.log`, `.py`, `.js`, `.ts`, `.eml` | Decoded as-is |
| `data` | 13 | `.csv`, `.tsv`, `.json`, `.jsonl`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.xml`, `.html`, `.htm`, `.sql` | CSV/TSV flattened, JSON pretty-printed, HTML/XML tags stripped |
| `office` | 8 | `.docx`, `.xlsx`, `.xlsm`, `.pptx`, `.odt`, `.ods`, `.odp`, `.rtf` | ZIP+XML (OOXML / OpenDocument), RTF control words stripped |
| `office-legacy` | 3 | `.doc`, `.xls`, `.ppt` | Best-effort via `antiword` / `catdoc` / `xls2csv` / `libreoffice` |
| `pdf` | 1 | `.pdf` | `pdftotext -layout -enc UTF-8`, optional `pypdf` fallback |
| `ebook` | 1 | `.epub` | XHTML/HTML chapters stripped and concatenated |
| `image` | 7 | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp` | `tesseract … -l eng` OCR (`parse_status=ocr`) |

Encoding fallback order is `utf-8-sig → utf-8 → gb18030 → big5 → latin-1 → utf-8(errors=ignore)`, covering Chinese-language documents.

## 3. Parsing pipeline

```
UploadFile → read() → ext_of(filename) → allow-list check → size check
           → documents.parse(filename, data)
               ├─ OOXML / ODF / EPUB : zipfile + ElementTree
               ├─ PDF                : pdftotext (30 s) → pypdf fallback
               ├─ legacy Office      : antiword / catdoc / xls2csv / libreoffice
               ├─ image              : tesseract (60 s, eng)
               └─ text / data        : decode, HTML strip, CSV/JSON/RTF helpers
           → clean, truncate to 400,000 chars → {text, metadata, parse_status}
```

Implementation notes (`backend/app/services/documents.py`):

| Parser | What it reads |
| --- | --- |
| `_docx` | `word/document.xml` plus `word/header*/footer*.xml`; collects `w:p` → `w:t` text line by line |
| `_xlsx` | `xl/sharedStrings.xml` + `xl/worksheets/sheetN.xml`; emits `[Sheet N]` headers and `cell \| cell` rows |
| `_pptx` | `ppt/slides/slideN.xml` in numeric order; emits `[Slide N]` plus `a:t` runs |
| `_odf` | `content.xml`; collects `<text:p>` / `<text:h>` via `itertext()` |
| `_epub` | Sorted `.xhtml/.html/.htm` chapters, HTML-stripped |
| `_plain` | HTMLParser (skips `script`/`style`/`noscript`), JSON re-serialization, CSV/TSV (first 20,000 rows), RTF unescaping |

`parse()` returns `text`, `file_name`, `file_type`, `file_label`, `kind`, `mime`, `file_size`, `parse_status`, `parse_error` and `chars`. Status values:

| `parse_status` | Meaning |
| --- | --- |
| `parsed` | Text extracted successfully |
| `ocr` | Text produced by OCR |
| `empty` | Parser ran but found no extractable text (`parse_error` explains) |
| `error` | Parser raised; `parse_error` holds a truncated type/message |

**Safety:** parsers only read bytes — no macros, scripts, formulas or embedded executables are evaluated. `UnsupportedFormat` is raised for unknown extensions, empty files, oversize files, and legacy binaries without a converter; the upload router converts that into a per-file failure entry.

## 4. Upload API

| Endpoint | Permission | Purpose |
| --- | --- | --- |
| `GET /api/v1/knowledge/formats` | `knowledge:read` | Format catalog, groups, limits |
| `POST /api/v1/knowledge/upload` | `knowledge:write` | Multipart batch upload + immediate indexing |
| `GET /api/v1/knowledge/stats` | `knowledge:read` | Adds `uploaded`, `formats_supported`, `by_file_type`, `embedding_provider`, `rerank_provider` |

`POST /knowledge/upload` (`multipart/form-data`, `201`):

| Field | Type | Rule |
| --- | --- | --- |
| `collection_id` | `int` (Form, required) | Must exist, else `404` |
| `files` | `UploadFile[]` (File, required) | At most 20 per request, else `400` |
| `title` | `str` (Form, optional) | Applied only when a single file is uploaded; otherwise `Path(filename).stem` |

Response:

```json
{
  "uploaded": 2,
  "failed": 1,
  "collection_id": 3,
  "documents": [
    {"id": 41, "ok": true, "title": "leave_policy", "file_name": "leave_policy.docx",
     "file_type": "docx", "file_label": "Word 2007+ (.docx)", "file_size": 18432,
     "parse_status": "parsed", "parse_error": null, "chars": 2310, "chunks": 6},
    {"file_name": "notes.exe", "ok": false,
     "error": "Unsupported file type '.exe'. Supported: .bmp, .cfg, .csv, … (43 formats)"}
  ]
}
```

Each created row is `source=upload`, `status=indexed` (or `empty`), and is passed to `rag.index_document(did)` right away. A `knowledge.upload` audit entry records `{files, created}`. Failures are isolated: the loop catches `UnsupportedFormat` and any other exception per file, so the batch always returns a result for every input.

## 5. Storage and retrieval

`kb_documents` gained five upload columns (added by `db._migrate()` for existing databases): `file_name`, `file_type`, `file_size`, `parse_status`, `parse_error`. `idx_kbdocs_file_type` indexes `file_type` and is created **after** migration (see [Data Model](data-model.md) §migration).

`routers/knowledge.py::_document_out()` appends `file_label` (human-readable) to every document response. Uploaded text flows through the same `rag.index_document()` → JSON `chunks` → mixed zh/en BM25 path as manually created documents, so `POST /knowledge/search`, RAG context assembly for agents, and the retrieval test console work unchanged. `GET /knowledge/stats` reports upload counts broken down by file type and surfaces the configured embedding/rerank defaults from [AI Model Services](ai-models.md).

## 6. Frontend

`frontend/src/pages/Knowledge.tsx` adds an **Upload** button and a drag-and-drop dialog:

- Format chips/listing fed by `GET /knowledge/formats` (no hard-coded catalog in the UI).
- Multi-file selection with per-file results: name, type label, size, `parse_status`, chunk count and `parse_error`.
- Document list and detail view show `file_type` / `file_label`, `parse_status`, `file_size` and `parse_error`.
- Uploads use the `upload<T>()` multipart helper in `lib/api.ts` (raw `FormData`, no JSON content type).

## 7. Validation

`backend/tests/smoke.py` (189 assertions) covers: format catalog, plain Markdown/TXT/CSV, OOXML fixtures (docx/xlsx/pptx), PDF via `pdftotext`, JSON/YAML, unsupported-extension rejection, empty-file rejection, per-file failure isolation, document metadata, immediate BM25 retrieval of uploaded content, and `GET /knowledge/stats` upload counters. `ruff check app tests`, `pnpm typecheck`, `pnpm build` and `pnpm check:i18n` (789 en/zh keys) all pass.

## 8. Limitations and production considerations

- **Best-effort parsing.** OOXML/ODF extraction returns text, not layout, tables-as-tables, images, comments or tracked changes. Verify extraction quality for critical documents.
- **Host CLI dependencies.** PDF needs `pdftotext` (or `pypdf`), OCR needs `tesseract` with the `eng` language pack, legacy Office needs a converter. Missing tools produce a clear `parse_status=error` rather than a crash; the recommended path is to convert `.doc/.xls/.ppt` to modern formats before upload.
- **Resource limits.** 20 MB per file / 20 files per batch / 400,000 chars of stored text, with 30–60 s subprocess timeouts. For large corpora, switch to streaming/background parsing and object storage.
- **Untrusted input.** Quarantine and scan uploads before parsing; consider disabling PDF/OCR helpers on untrusted hosts. See [Security Architecture](security.md).
- **No re-parse endpoint yet.** Re-uploading a corrected file creates a new document; `POST /knowledge/documents/{id}/reindex` only rebuilds chunks from already-stored text.
