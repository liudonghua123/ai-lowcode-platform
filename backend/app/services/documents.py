"""Best-effort text extraction for knowledge-base uploads.

Design goal: support the widest practical set of document formats with only the
Python standard library plus the already-installed ``pdftotext``/``tesseract``
CLI tools. Office Open XML and OpenDocument files are ZIP containers of XML, so
they are parsed directly with ``zipfile`` + ``ElementTree`` — no python-docx /
openpyxl / python-pptx dependency is required.

Parsed text is stored in ``kb_documents.content`` and indexed by the existing
BM25 chunker, so uploaded documents become immediately searchable.
"""
from __future__ import annotations

import csv
import html.parser
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 400_000

# ext -> (label, kind, mime)
_FORMATS: dict[str, tuple[str, str, str]] = {
    ".md": ("Markdown", "text", "text/markdown"),
    ".markdown": ("Markdown", "text", "text/markdown"),
    ".txt": ("Plain text", "text", "text/plain"),
    ".text": ("Plain text", "text", "text/plain"),
    ".rst": ("reStructuredText", "text", "text/plain"),
    ".log": ("Log file", "text", "text/plain"),
    ".csv": ("CSV", "data", "text/csv"),
    ".tsv": ("TSV", "data", "text/tab-separated-values"),
    ".json": ("JSON", "data", "application/json"),
    ".jsonl": ("JSON Lines", "data", "application/x-ndjson"),
    ".yaml": ("YAML", "data", "application/yaml"),
    ".yml": ("YAML", "data", "application/yaml"),
    ".toml": ("TOML", "data", "application/toml"),
    ".ini": ("INI", "data", "text/plain"),
    ".cfg": ("Config", "data", "text/plain"),
    ".xml": ("XML", "data", "application/xml"),
    ".html": ("HTML", "data", "text/html"),
    ".htm": ("HTML", "data", "text/html"),
    ".sql": ("SQL", "data", "application/sql"),
    ".py": ("Python source", "text", "text/x-python"),
    ".js": ("JavaScript source", "text", "text/javascript"),
    ".ts": ("TypeScript source", "text", "text/typescript"),
    ".rtf": ("Rich Text", "office", "application/rtf"),
    ".pdf": ("PDF", "pdf", "application/pdf"),
    ".docx": ("Word 2007+ (.docx)", "office", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".doc": ("Word 97-2003 (.doc)", "office-legacy", "application/msword"),
    ".xlsx": ("Excel 2007+ (.xlsx)", "office", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xlsm": ("Excel macro (.xlsm)", "office", "application/vnd.ms-excel.sheet.macroenabled.12"),
    ".xls": ("Excel 97-2003 (.xls)", "office-legacy", "application/vnd.ms-excel"),
    ".pptx": ("PowerPoint 2007+ (.pptx)", "office", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".ppt": ("PowerPoint 97-2003 (.ppt)", "office-legacy", "application/vnd.ms-powerpoint"),
    ".odt": ("OpenDocument Text", "office", "application/vnd.oasis.opendocument.text"),
    ".ods": ("OpenDocument Spreadsheet", "office", "application/vnd.oasis.opendocument.spreadsheet"),
    ".odp": ("OpenDocument Presentation", "office", "application/vnd.oasis.opendocument.presentation"),
    ".epub": ("EPUB", "ebook", "application/epub+zip"),
    ".eml": ("Email (.eml)", "text", "message/rfc822"),
    ".png": ("Image (OCR)", "image", "image/png"),
    ".jpg": ("Image (OCR)", "image", "image/jpeg"),
    ".jpeg": ("Image (OCR)", "image", "image/jpeg"),
    ".tif": ("Image (OCR)", "image", "image/tiff"),
    ".tiff": ("Image (OCR)", "image", "image/tiff"),
    ".bmp": ("Image (OCR)", "image", "image/bmp"),
    ".webp": ("Image (OCR)", "image", "image/webp"),
}

_OFFICE_NS = {
    "w": "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "s": "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}",
    "a": "{http://schemas.openxmlformats.org/drawingml/2006/main}",
}


class UnsupportedFormat(ValueError):
    pass


def formats() -> dict:
    """Supported upload formats, grouped for the UI."""
    groups: dict[str, list[dict]] = {}
    for ext, (label, kind, mime) in _FORMATS.items():
        groups.setdefault(kind, []).append(
            {"ext": ext, "label": label, "kind": kind, "mime": mime})
    return {"formats": [item for v in groups.values() for item in v],
            "groups": [{"kind": k, "label": k, "items": v} for k, v in groups.items()],
            "total": len(_FORMATS), "max_file_bytes": MAX_FILE_BYTES,
            "max_text_chars": MAX_TEXT_CHARS}


def ext_of(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def label_for(ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return _FORMATS.get(ext, (ext.lstrip(".").upper() or "File", "other", ""))[0]


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


class _HTMLText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip() + " ")


def _strip_html(text: str) -> str:
    parser = _HTMLText()
    parser.feed(text)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx(data: bytes) -> str:
    w = _OFFICE_NS["w"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist()
                 if n == "word/document.xml" or re.fullmatch(r"word/(header|footer)\d*\.xml", n)]
        lines: list[str] = []
        for name in sorted(names):
            root = ET.fromstring(z.read(name))
            for para in root.iter(w + "p"):
                text = "".join(t.text or "" for t in para.iter(w + "t"))
                if text.strip():
                    lines.append(text.strip())
        return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    s = _OFFICE_NS["s"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter(s + "si"):
                shared.append("".join(t.text or "" for t in si.iter(s + "t")))
        sheets = sorted(n for n in z.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        lines: list[str] = []
        for name in sheets:
            lines.append(f"[Sheet {name.rsplit('sheet', 1)[-1].split('.')[0]}]")
            root = ET.fromstring(z.read(name))
            for row in root.iter(s + "row"):
                cells: list[str] = []
                for cell in row.iter(s + "c"):
                    value = cell.find(s + "v")
                    inline = cell.find(s + "is")
                    if cell.get("t") == "s" and value is not None:
                        try:
                            text = shared[int(value.text or "0")]
                        except (ValueError, IndexError):
                            text = ""
                    elif inline is not None:
                        text = "".join(t.text or "" for t in inline.iter(s + "t"))
                    else:
                        text = value.text if value is not None else ""
                    if text:
                        cells.append(str(text))
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)


def _pptx(data: bytes) -> str:
    a = _OFFICE_NS["a"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted((n for n in z.namelist()
                         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
        lines: list[str] = []
        for index, name in enumerate(slides, 1):
            root = ET.fromstring(z.read(name))
            texts = [el.text or "" for el in root.iter(a + "t") if (el.text or "").strip()]
            if texts:
                lines.append(f"[Slide {index}] " + " ".join(texts))
        return "\n".join(lines)


def _odf(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if "content.xml" not in z.namelist():
            return ""
        root = ET.fromstring(z.read("content.xml"))
        lines: list[str] = []
        for el in root.iter():
            if _localname(el.tag) in {"p", "h"}:
                text = "".join(el.itertext()).strip()
                if text:
                    lines.append(text)
        return "\n".join(lines)


def _epub(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        pages = sorted(n for n in z.namelist()
                       if n.lower().endswith((".xhtml", ".html", ".htm")))
        lines: list[str] = []
        for name in pages:
            try:
                text = _strip_html(_decode(z.read(name)))
            except (KeyError, UnicodeDecodeError):
                continue
            if text:
                lines.append(text)
        return "\n\n".join(lines)


def _pdf(data: bytes) -> str:
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
                input=data, capture_output=True, timeout=30, check=False)
            if proc.returncode == 0:
                return _decode(proc.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:  # optional pure-python fallback
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise UnsupportedFormat(f"PDF text extraction failed: {str(exc)[:120]}") from exc


def _legacy_office(data: bytes, ext: str) -> str:
    """Best effort for legacy binary Office files via available CLI converters."""
    suffix = ext.lstrip(".")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"input{suffix}"
        src.write_bytes(data)
        for tool in ("antiword", "catdoc", "xls2csv"):
            if shutil.which(tool):
                try:
                    proc = subprocess.run([tool, str(src)], capture_output=True,
                                          timeout=20, check=False)
                    if proc.returncode == 0 and proc.stdout:
                        return _decode(proc.stdout)
                except (OSError, subprocess.TimeoutExpired):
                    continue
        if shutil.which("libreoffice"):
            try:
                subprocess.run(["libreoffice", "--headless", "--convert-to", "txt:Text",
                                "--outdir", tmp, str(src)], capture_output=True,
                               timeout=45, check=False)
                out = Path(tmp) / "input.txt"
                if out.is_file():
                    return _decode(out.read_bytes())
            except (OSError, subprocess.TimeoutExpired):
                pass
    raise UnsupportedFormat(
        f"Legacy {ext} is a binary format. Convert it to the modern .docx/.xlsx/.pptx "
        "or install antiword/libreoffice on the host.")


def _ocr(data: bytes, ext: str) -> str:
    if not shutil.which("tesseract"):
        raise UnsupportedFormat("OCR requires the tesseract CLI on the host.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"image{ext}"
        src.write_bytes(data)
        try:
            proc = subprocess.run(["tesseract", str(src), "stdout", "-l", "eng"],
                                  capture_output=True, timeout=60, check=False)
            if proc.returncode == 0:
                return _decode(proc.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise UnsupportedFormat("OCR did not produce text for this image.")


def _csv(data: bytes, delimiter: str) -> str:
    text = _decode(data)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        return text
    return "\n".join(" | ".join(cell for cell in row if cell) for row in rows[:20_000])


def _rtf(data: bytes) -> str:
    text = _decode(data)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    return re.sub(r"[{}]", "", text).strip()


def _plain(data: bytes, ext: str) -> str:
    text = _decode(data)
    if ext in {".html", ".htm", ".xhtml", ".xml"}:
        return _strip_html(text)
    if ext == ".json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            return text
    if ext in {".csv", ".tsv"}:
        return _csv(data, "\t" if ext == ".tsv" else ",")
    if ext == ".rtf":
        return _rtf(data)
    return text


_PARSERS = {
    ".docx": _docx, ".xlsx": _xlsx, ".xlsm": _xlsx, ".pptx": _pptx,
    ".odt": _odf, ".ods": _odf, ".odp": _odf, ".epub": _epub, ".pdf": _pdf,
}


def parse(filename: str, data: bytes) -> dict:
    """Return extracted text + metadata for one uploaded file."""
    ext = ext_of(filename)
    if ext not in _FORMATS:
        raise UnsupportedFormat(
            f"Unsupported file type '{ext or '(none)'}'. Supported: "
            + ", ".join(sorted(_FORMATS)))
    if not data:
        raise UnsupportedFormat("Uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise UnsupportedFormat(
            f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit")

    label, kind, mime = _FORMATS[ext]
    status = "parsed"
    error: str | None = None
    try:
        if ext in _PARSERS:
            text = _PARSERS[ext](data)
        elif kind == "office-legacy":
            text = _legacy_office(data, ext)
        elif kind == "image":
            text = _ocr(data, ext)
            status = "ocr"
        else:
            text = _plain(data, ext)
    except UnsupportedFormat:
        raise
    except Exception as exc:
        text, status, error = "", "error", f"{type(exc).__name__}: {str(exc)[:220]}"
    text = (text or "").replace("\x00", "").strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n…[truncated]"
    if not text and status == "parsed":
        status, error = "empty", "No extractable text was found in this file."
    return {"text": text, "file_name": Path(filename).name,
            "file_type": ext.lstrip("."), "file_label": label, "kind": kind,
            "mime": mime, "file_size": len(data), "parse_status": status,
            "parse_error": error, "chars": len(text)}
