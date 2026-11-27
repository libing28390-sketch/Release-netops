"""Local document parser for Copilot attachments (Word, Excel, PDF, text).

Parses uploaded files entirely locally without external network calls:
- .docx: python-docx if available, otherwise stdlib zipfile + XML parser
- .xlsx: openpyxl (read-only mode)
- .pdf: pypdf
- .txt / .md / .csv / .log / .json: UTF-8 / GB18030 text decoding
"""

from __future__ import annotations

import io
import os
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_EXTRACTED_CHARS = 24_000

ALLOWED_EXTENSIONS = {
    ".docx",
    ".xlsx",
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".log",
    ".json",
}


class DocumentParseError(ValueError):
    """Raised when an uploaded attachment cannot be safely parsed."""


def _decode_text_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_docx_bytes(raw: bytes) -> str:
    # Prefer python-docx if installed, otherwise parse OOXML word/document.xml directly.
    try:
        import docx  # type: ignore

        doc = docx.Document(io.BytesIO(raw))
        parts: list[str] = []
        for para in doc.paragraphs:
            text = (para.text or "").strip()
            if text:
                parts.append(text)
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except ImportError:
        pass

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            if "word/document.xml" not in zf.namelist():
                raise DocumentParseError("无效的 Word (.docx) 文件：缺少 word/document.xml")
            xml_bytes = zf.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise DocumentParseError("无效的 Word (.docx) 文件格式") from exc

    root = ET.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines: list[str] = []
    for para in root.findall(".//w:p", ns):
        texts = [node.text for node in para.findall(".//w:t", ns) if node.text]
        line = "".join(texts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _parse_xlsx_bytes(raw: bytes) -> str:
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:
        raise DocumentParseError("服务端未安装 openpyxl，暂无法解析 Excel 文件") from exc

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise DocumentParseError(f"无法解析 Excel (.xlsx) 文件: {type(exc).__name__}") from exc

    parts: list[str] = []
    try:
        for sheet_name in wb.sheetnames[:10]:
            ws = wb[sheet_name]
            parts.append(f"[Sheet: {sheet_name}]")
            row_count = 0
            for row in ws.iter_rows(values_only=True):
                cells = [str(cell).strip() if cell is not None else "" for cell in row]
                if not any(cells):
                    continue
                parts.append(" | ".join(cells))
                row_count += 1
                if row_count >= 200:
                    parts.append("... (已截断该工作表后续行)")
                    break
    finally:
        wb.close()
    return "\n".join(parts)


def _parse_pdf_bytes(raw: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise DocumentParseError("服务端未安装 pypdf，暂无法解析 PDF 文件") from exc

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise DocumentParseError(f"无法解析 PDF 文件: {type(exc).__name__}") from exc

    parts: list[str] = []
    for idx, page in enumerate(reader.pages[:50], start=1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"[Page {idx}]\n{text}")
    return "\n\n".join(parts)


def parse_uploaded_document(filename: str, raw: bytes) -> Dict[str, Any]:
    """Parse an uploaded file locally and return bounded text + metadata."""
    safe_name = os.path.basename(str(filename or "").strip()) or "attachment"
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentParseError(
            f"不支持的文件类型 '{ext or '未知'}'，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    if not raw:
        raise DocumentParseError("上传的文件内容为空")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise DocumentParseError(f"文件大小超过上限（最大 {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB）")

    if ext == ".docx":
        extracted = _parse_docx_bytes(raw)
    elif ext == ".xlsx":
        extracted = _parse_xlsx_bytes(raw)
    elif ext == ".pdf":
        extracted = _parse_pdf_bytes(raw)
    else:
        extracted = _decode_text_bytes(raw)

    extracted = extracted.strip()
    truncated = False
    if len(extracted) > MAX_EXTRACTED_CHARS:
        extracted = extracted[:MAX_EXTRACTED_CHARS] + "\n...[文档内容过长，已按上限截断]"
        truncated = True

    return {
        "filename": safe_name,
        "extension": ext,
        "size_bytes": len(raw),
        "char_count": len(extracted),
        "truncated": truncated,
        "text": extracted,
    }
